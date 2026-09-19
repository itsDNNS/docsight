"""PYUR capture contract; only allowlisted channel measurements are recorded."""

from copy import deepcopy
import json
from pathlib import Path

import pytest

from app.analyzer import analyze
from app.drivers.formats.pyur import parse_pyur_api_v1, parse_pyur_device_info


FIXTURE = Path(__file__).resolve().parents[1] / "fixtures/pyur_fast3896/connection.json"


@pytest.fixture
def payload():
    return json.loads(FIXTURE.read_text())


def test_capture_counts_values_and_optional_metadata(payload):
    original = deepcopy(payload)
    result = parse_pyur_api_v1(payload)
    ds, us = result.value["channelDs"], result.value["channelUs"]
    assert [len(ds["docsis30"]), len(ds["docsis31"]), len(us["docsis30"]), len(us["docsis31"])] == [20, 1, 5, 0]
    assert ds["docsis30"][0] == {
        "channelID": 1, "frequency": "618 MHz", "powerLevel": 1.4,
        "modulation": "256QAM", "mer": 41.1, "mse": -41.1,
        "corrErrors": 233, "nonCorrErrors": 0,
    }
    assert ds["docsis31"][0] == {
        "channelID": 21, "type": "OFDM", "frequency": "171 MHz",
        "powerLevel": 5.0, "modulation": "OFDM", "mer": 43.1, "mse": None,
        "corrErrors": 312809955, "nonCorrErrors": 286,
    }
    assert us["docsis30"][0] == {
        "channelID": 1, "frequency": "41 MHz", "powerLevel": 49.0,
        "modulation": "QAM", "symbolRate": 5120,
    }
    assert all(ch["modulation"] == "256QAM" for ch in ds["docsis30"])
    assert all(ch["modulation"] == "QAM" for ch in us["docsis30"])
    assert all("profile_modulation" not in ch and "multiplex" not in ch
               for lane in (ds, us) for channels in lane.values() for ch in channels)
    assert result.diagnostics == ()
    assert payload == original


def test_error_join_uses_row_id_only_and_preserves_large_counters(payload):
    payload[0]["Downstreams"][0]["ChannelID"] = "101"
    payload[0]["CMErrorCodewords"][0]["CorrectableCodewords"] = "9007199254740993"
    expected = parse_pyur_api_v1(payload).value
    payload[0]["CMErrorCodewords"].reverse()
    assert parse_pyur_api_v1(payload).value == expected
    ch = expected["channelDs"]["docsis30"][0]
    assert ch["channelID"] == 101
    assert ch["corrErrors"] == 9007199254740993


@pytest.mark.parametrize("case", ["missing_channel_id", "missing_error_id", "duplicate_error_id", "duplicate_channel_id", "no_errors", "null_errors"])
def test_ambiguous_counter_joins_are_unknown(payload, case):
    ds, errors = payload[0]["Downstreams"], payload[0]["CMErrorCodewords"]
    if case == "missing_channel_id":
        del ds[0]["id"]
    elif case == "missing_error_id":
        del errors[0]["id"]
    elif case == "duplicate_error_id":
        errors.append(dict(errors[0], CorrectableCodewords="999"))
    elif case == "duplicate_channel_id":
        ds[1]["id"] = ds[0]["id"]
    elif case == "no_errors":
        del payload[0]["CMErrorCodewords"]
    else:
        payload[0]["CMErrorCodewords"] = None
    ch = parse_pyur_api_v1(payload).value["channelDs"]["docsis30"][0]
    assert ch["channelID"] == 1
    assert ch["corrErrors"] is None
    assert ch["nonCorrErrors"] is None


@pytest.mark.parametrize("value", [None, "", "garbage", "NaN", "Infinity", float("nan"), float("inf"), -1, "-1", True, "1.2", {}, []])
def test_invalid_counters_stay_unknown(payload, value):
    payload[0]["CMErrorCodewords"][0]["CorrectableCodewords"] = value
    del payload[0]["CMErrorCodewords"][0]["UncorrectableCodewords"]
    ch = parse_pyur_api_v1(payload).value["channelDs"]["docsis30"][0]
    assert ch["corrErrors"] is None
    assert ch["nonCorrErrors"] is None


@pytest.mark.parametrize("value", [None, "", "private-marker", "NaN dBmV", "inf dB", float("nan"), float("inf"), True, {}, [], "1.2 bananas", "1e999"])
def test_invalid_measurements_are_null_without_payload_diagnostics(payload, value):
    row = payload[0]["Downstreams"][0]
    row.update(PowerLevel=value, SNR=value, Frequency=value)
    result = parse_pyur_api_v1(payload)
    ch = result.value["channelDs"]["docsis30"][0]
    assert ch["powerLevel"] is None and ch["mer"] is None and ch["mse"] is None
    assert ch["frequency"] == ""
    assert "private-marker" not in repr(result.diagnostics)


@pytest.mark.parametrize("frequency,expected", [("618 MHz", "618 MHz"), ("618000000 Hz", "618 MHz"), ("618000 kHz", "618 MHz"), ("41  MHz", "41 MHz"), ("30.125 MHz", "30.125 MHz"), (618, ""), ("618", ""), ("-1 MHz", "")])
def test_frequency_units_are_explicit_without_magnitude_guessing(payload, frequency, expected):
    payload[0]["Downstreams"][0]["Frequency"] = frequency
    assert parse_pyur_api_v1(payload).value["channelDs"]["docsis30"][0]["frequency"] == expected


@pytest.mark.parametrize("modulation,expected", [(None, ""), ("future-mode", ""), ("not OFDM", ""), ("QAM", "QAM"), ("QAM256", "256QAM"), ("ofdm", "OFDM")])
def test_unknown_modulation_does_not_invent_qam_or_ofdm(payload, modulation, expected):
    payload[0]["Downstreams"][0]["Modulation"] = modulation
    data = parse_pyur_api_v1(payload).value
    lane = "docsis31" if expected == "OFDM" else "docsis30"
    ch = data["channelDs"][lane][0]
    assert ch["modulation"] == expected
    assert "profile_modulation" not in ch


@pytest.mark.parametrize("bad", [None, {}, [], [None], [{}], [{}, {}], [{"Downstreams": {}, "Upstreams": []}], [{"Downstreams": [], "Upstreams": None}], [{"Downstreams": [], "Upstreams": [], "CMErrorCodewords": {}}]])
def test_malformed_top_level_fails_visibly(bad):
    with pytest.raises(ValueError, match="PYUR"):
        parse_pyur_api_v1(bad)


def test_missing_channel_number_is_not_replaced_with_join_id(payload):
    del payload[0]["Downstreams"][0]["ChannelID"]
    result = parse_pyur_api_v1(payload)
    assert len(result.value["channelDs"]["docsis30"]) == 19
    assert result.diagnostics


def test_analyzer_integration_keeps_unknowns(payload):
    payload[0]["CMErrorCodewords"] = []
    result = analyze(parse_pyur_api_v1(payload).value)
    assert len(result["ds_channels"]) == 21
    assert len(result["us_channels"]) == 5
    ds = result["ds_channels"][0]
    assert ds["power"] == 1.4 and ds["snr"] == 41.1
    assert ds["correctable_errors"] is None
    assert all(ch["modulation"] == "QAM" for ch in result["us_channels"])
    assert "profile_modulation" not in result["ds_channels"][-1]


def test_zero_values_and_absent_symbol_rate_stay_distinct(payload):
    payload[0]["Downstreams"][0].update(PowerLevel="0 dBmV", SNR="0 dB")
    del payload[0]["Upstreams"][0]["SymbolRate"]
    payload[0]["Upstreams"][1]["SymbolRate"] = None
    data = parse_pyur_api_v1(payload).value
    assert data["channelDs"]["docsis30"][0]["powerLevel"] == 0
    assert data["channelDs"]["docsis30"][0]["mer"] == 0
    assert "symbolRate" not in data["channelUs"]["docsis30"][0]
    assert data["channelUs"]["docsis30"][1]["symbolRate"] is None


def test_non_object_rows_and_unusable_channel_arrays(payload):
    payload[0]["Downstreams"].append(None)
    payload[0]["Upstreams"].append([])
    payload[0]["CMErrorCodewords"].append("private-marker")
    result = parse_pyur_api_v1(payload)
    assert len(result.value["channelDs"]["docsis30"]) == 20
    assert "private-marker" not in repr(result)
    with pytest.raises(ValueError, match="PYUR"):
        parse_pyur_api_v1([{"Downstreams": [None, {}], "Upstreams": []}])


def test_oversized_channel_arrays_fail(payload):
    payload[0]["Upstreams"] = [{}] * 257
    with pytest.raises(ValueError, match="PYUR"):
        parse_pyur_api_v1(payload)


@pytest.mark.parametrize("value", [None, True, float("inf"), "", "invalid\ntext", [], {}])
def test_device_unknown_values_are_absent(value):
    result = parse_pyur_device_info([{"device": {
        "modelname": value, "uptime": value, "running": {"version": value},
        "main": None, "unrelated": "synthetic-private-marker",
    }}])
    assert result.value == {"manufacturer": "Sagemcom"}


def test_device_main_version_fallback_and_uptime_zero():
    assert parse_pyur_device_info([{"device": {"main": {"version": "synthetic-main"}, "uptime": 0}}]).value == {
        "manufacturer": "Sagemcom", "sw_version": "synthetic-main", "uptime_seconds": 0,
    }


@pytest.mark.parametrize("uptime", ["NaN", "-1", "1.5"])
def test_invalid_uptime_does_not_drop_valid_version(uptime):
    assert parse_pyur_device_info([{"device": {"main": {"version": "1.5"}, "uptime": uptime}}]).value == {
        "manufacturer": "Sagemcom", "sw_version": "1.5",
    }
