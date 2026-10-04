"""Home line status view model."""

from app.analyzer import _get_ds_power_thresholds, _get_snr_thresholds, _get_us_power_thresholds
from app.line_status import build_line_status


def _ds(channel_id, power=4.0, snr=38.0, health="good", detail="", family="sc_qam", modulation="256QAM"):
    return {"channel_id": channel_id, "channel_family": family, "power": power, "snr": snr,
            "modulation": modulation, "health": health, "health_detail": detail}


def _us(channel_id, power=44.5, health="good", detail="", family="sc_qam", modulation="64QAM"):
    channel = {"channel_id": channel_id, "channel_family": family, "power": power,
               "modulation": "OFDMA" if family == "ofdma" else modulation, "health": health, "health_detail": detail}
    if family == "ofdma":
        channel["profile_modulation"] = "256QAM"
    return channel


def _analysis(ds, us, health="good"):
    return {"summary": {"health": health}, "ds_channels": ds, "us_channels": us}


def test_without_channels_there_is_no_line_status():
    assert build_line_status(_analysis([], [])) is None
    assert build_line_status(None) is None


def test_all_good_has_no_callouts():
    status = build_line_status(_analysis([_ds(1), _ds(2)], [_us(1)]))

    assert status["health"] == "good"
    assert (status["within"], status["total"], status["deviating"]) == (3, 3, 0)
    assert status["primary"] is None
    assert all(block["callout"] is None and block["more"] == [] for block in status["directions"])
    assert status["directions"][0]["counts"] == {"good": 2, "tolerated": 0, "warning": 0, "critical": 0}


def test_ofdma_power_below_target_is_explained_with_the_rating_thresholds():
    status = build_line_status(_analysis(
        [_ds(1)],
        [_us(1), _us(5, power=41.7, health="tolerated", detail="power tolerated low", family="ofdma")],
        health="tolerated",
    ))
    limits = _get_us_power_thresholds("OFDMA")
    upstream = status["directions"][1]
    callout = upstream["callout"]

    assert [seg["channel_id"] for seg in upstream["segments"]] == [5, 1]
    assert callout["channel_id"] == 5 and callout["family"] == "OFDMA" and callout["modulation"] == "256QAM"
    measurement = callout["measurement"]
    assert measurement["metric"] == "power" and measurement["unit"] == "dBmV"
    assert (measurement["target_min"], measurement["target_max"]) == (limits["good_min"], limits["good_max"])
    assert measurement["delta"] == round(41.7 - limits["good_min"], 1)
    ruler = measurement["ruler"]
    assert ruler["marker"] < ruler["good"]["left"]
    assert callout["link"] == "#channels?mode=timeline&dir=us&channel=5"
    assert status["primary"] is callout


def test_downstream_power_above_target_reports_a_positive_delta():
    status = build_line_status(_analysis([_ds(3, power=15.6, health="warning", detail="power warning")], []))
    limits = _get_ds_power_thresholds("256QAM", channel_family="sc_qam")

    measurement = status["directions"][0]["callout"]["measurement"]
    assert measurement["delta"] == round(15.6 - limits["good_max"], 1)
    assert measurement["ruler"]["marker"] > measurement["ruler"]["good"]["left"] + measurement["ruler"]["good"]["width"]


def test_low_snr_uses_the_minimum_target():
    status = build_line_status(_analysis([_ds(7, snr=31.0, health="warning", detail="snr warning")], []))
    limits = _get_snr_thresholds("256QAM", channel_family="sc_qam")

    measurement = status["directions"][0]["callout"]["measurement"]
    assert measurement["metric"] == "snr" and measurement["target_max"] is None
    assert measurement["target_min"] == limits["good_min"]
    assert measurement["delta"] == round(31.0 - limits["good_min"], 1)


def test_modulation_only_deviation_has_no_measurement():
    status = build_line_status(_analysis([], [_us(2, health="warning", detail="modulation warning", modulation="16QAM")]))

    callout = status["directions"][0]["callout"]
    assert callout["measurement"] is None
    assert callout["modulation"] == "16QAM"


def test_worst_deviation_comes_first_and_others_are_counted():
    status = build_line_status(_analysis(
        [
            _ds(22, power=14.4, health="tolerated", detail="power tolerated"),
            _ds(23, power=15.6, health="warning", detail="power warning"),
            _ds(1),
        ],
        [_us(5, power=37.2, health="critical", detail="power critical low", family="ofdma")],
        health="critical",
    ))
    downstream, upstream = status["directions"]

    assert downstream["callout"]["channel_id"] == 23
    assert downstream["more"] == [{"channel_id": 22, "health": "tolerated"}]
    assert status["primary"]["channel_id"] == 5 and status["primary"]["direction"] == "us"
    assert (status["within"], status["deviating"]) == (1, 3)


def test_upstream_without_ofdma_reports_the_missing_family():
    status = build_line_status(_analysis([_ds(1)], [_us(1), _us(2)]))
    downstream, upstream = status["directions"]

    assert upstream["missing_family"] == "OFDMA"
    assert downstream["missing_family"] is None
    assert (status["within"], status["total"]) == (3, 3)


def test_upstream_with_ofdma_has_no_missing_family():
    status = build_line_status(_analysis([], [_us(1), _us(5, family="ofdma")]))

    assert status["directions"][0]["missing_family"] is None


def test_segments_carry_the_stable_channel_selector():
    from app.channel_selector import channel_selector

    ds = _ds(1)
    ds["frequency"] = "602 MHz"
    status = build_line_status(_analysis([ds], []))

    assert status["directions"][0]["segments"][0]["selector"] == channel_selector(ds)
