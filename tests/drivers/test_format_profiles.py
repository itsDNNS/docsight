"""Direct, network-free tests for every explicit pure format profile."""

from __future__ import annotations

import json

from bs4 import BeautifulSoup
import pytest

from app.drivers.formats.boundaries import parse_generic_no_docsis
from app.drivers.formats.contract import ParseResult
from app.drivers.formats.fritzbox import parse_fritzbox_data_lua
from app.drivers.formats.pyur import parse_pyur_api_v1
from app.drivers.formats.hitron import (
    parse_hitron_coda4680_json,
    parse_hitron_coda56_json,
)
from app.drivers.formats.html_columnar import parse_cgm4981_columnar_html
from app.drivers.formats.html_rows import (
    parse_arris_html,
    parse_cm1000_html_table,
    parse_cm3500_html,
    parse_sb6183_html,
    parse_sb6190_html,
    parse_tc4400_html,
)
from app.drivers.formats.html_transposed import parse_sb6141_transposed_html
from app.drivers.formats.javascript import (
    parse_cm1000_javascript,
    parse_cm3000_javascript,
)
from app.drivers.formats.sagemcom import (
    parse_f3896lg_rest_json,
    parse_sagemcom_xmo_json,
)
from app.drivers.formats.sercom import parse_sercom_dm1000_json
from app.drivers.formats.surfboard import parse_surfboard_hnap
from app.drivers.formats.vodafone import (
    parse_ultrahub7_json,
    parse_vodafone_station_cga_json,
    parse_vodafone_station_tg_embedded_json,
)
from app.drivers.formats.xml_payloads import parse_ch7465_xml
from tests.drivers.driver_format_cases import (
    ARRIS_SUCCESS,
    CGM4981_SUCCESS,
    CM1000_TABLE_SUCCESS,
    CM3000_SUCCESS,
    CM3500_SUCCESS,
    FRITZ_SUCCESS,
    SB6141_SUCCESS,
    TC_DS_SUCCESS,
    TC_US_SUCCESS,
    TG_SUCCESS,
)
from tests.drivers.f3896lg._data import DOWNSTREAM as F3896_DS, UPSTREAM as F3896_US
from tests.test_hitron_coda_4680_driver import DS_INFO, DS_OFDM, US_INFO, US_OFDMA
from tests.test_hitron_driver import DS_OFDM_DATA, DS_SCQAM_DATA, US_OFDMA_DATA, US_SCQAM_DATA
from tests.test_sb6183_driver import SAMPLE_STATUS_HTML as SB6183_HTML
from tests.test_sb6190_driver import SAMPLE_STATUS_HTML as SB6190_HTML
from tests.test_sercom_dm1000_driver import (
    DS_INFO as SERCOM_DS,
    DS_OFDM as SERCOM_OFDM,
    US_INFO as SERCOM_US,
    US_OFDMA as SERCOM_OFDMA,
)


def _tc_success():
    downstream = BeautifulSoup(TC_DS_SUCCESS, "html.parser").find("table")
    upstream = BeautifulSoup(TC_US_SUCCESS, "html.parser").find("table")
    return parse_tc4400_html(downstream, upstream)


SUCCESS_PROFILES = {
    "pyur_api_v1": lambda: parse_pyur_api_v1([{
        "Downstreams": [{"ChannelID": "21", "Modulation": "OFDM", "Frequency": "171 MHz"}],
        "Upstreams": [{"ChannelID": "1", "Modulation": "QAM"}],
    }]),
    "arris_html": lambda: parse_arris_html(ARRIS_SUCCESS),
    "cgm4981_columnar_html": lambda: parse_cgm4981_columnar_html(CGM4981_SUCCESS.replace(" dBmV", "").replace(" dB", "")),
    "ch7465_xml": lambda: parse_ch7465_xml(
        "<root><downstream><chid>7</chid><freq>591 MHz</freq><pow>0</pow><mod>256qam</mod></downstream></root>",
        "<root><upstream><usid>3</usid><freq>29 MHz</freq><power>43.5</power><mod>64qam</mod></upstream></root>",
    ),
    "cm1000_html_table": lambda: parse_cm1000_html_table(CM1000_TABLE_SUCCESS),
    "cm1000_javascript": lambda: parse_cm1000_javascript(
        open("tests/fixtures/cm1000/DocsisStatus.asp.html", encoding="utf-8").read()
    ),
    "cm3000_javascript": lambda: parse_cm3000_javascript(CM3000_SUCCESS),
    "cm3500_html": lambda: parse_cm3500_html(CM3500_SUCCESS),
    "f3896lg_rest_json": lambda: parse_f3896lg_rest_json({
        "downstream": [F3896_DS["downstream"]["channels"][0], F3896_DS["downstream"]["channels"][-1]],
        "upstream": [F3896_US["upstream"]["channels"][0], F3896_US["upstream"]["channels"][-1]],
    }),
    "fritzbox_data_lua": lambda: parse_fritzbox_data_lua(FRITZ_SUCCESS),
    "generic_no_docsis": parse_generic_no_docsis,
    "hitron_coda4680_json": lambda: parse_hitron_coda4680_json({
        "downstream": DS_INFO, "upstream": US_INFO,
        "downstream_ofdm": DS_OFDM, "upstream_ofdma": US_OFDMA,
    }),
    "hitron_coda56_json": lambda: parse_hitron_coda56_json({
        "downstream": DS_SCQAM_DATA[:1], "upstream": US_SCQAM_DATA[:1],
        "downstream_ofdm": DS_OFDM_DATA[:1], "upstream_ofdma": US_OFDMA_DATA[:1],
    }),
    "sagemcom_xmo_json": lambda: parse_sagemcom_xmo_json({
        "downstream": [{"ChannelID": 193, "LockStatus": True, "Frequency": 666000000,
            "SNR": 44.0, "PowerLevel": 7.9, "Modulation": "256-QAM1K-QAM2K-QA",
            "BandWidth": 128000000}],
        "upstream": [{"ChannelID": 41, "LockStatus": True, "Frequency": 104800000,
            "PowerLevel": 38.0, "Modulation": "ofdma"}],
    }),
    "sb6141_transposed_html": lambda: parse_sb6141_transposed_html(SB6141_SUCCESS),
    "sb6183_html": lambda: parse_sb6183_html(SB6183_HTML),
    "sb6190_html": lambda: parse_sb6190_html(SB6190_HTML),
    "sercom_dm1000_json": lambda: parse_sercom_dm1000_json({
        "downstream": SERCOM_DS["nodes"], "downstream_ofdm": SERCOM_OFDM["nodes"],
        "upstream": SERCOM_US["nodes"], "upstream_ofdma": SERCOM_OFDMA["nodes"],
    }),
    "surfboard_hnap": lambda: parse_surfboard_hnap(
        "1^Locked^OFDM PLC^193^957000000^0.1^43.0^9^1^",
        "1^Locked^OFDMA^41^44400000^36200000^43.8^",
    ),
    "tc4400_html": _tc_success,
    "ultrahub7_json": lambda: parse_ultrahub7_json({
        "downstream": [{"ChannelID": "193", "Frequency": "690 MHz", "Modulation": "OFDM", "PowerLevel": "0", "SNRLevel": "41.8"}],
        "upstream": [{"ChannelID": "41", "Frequency": "36.2 MHz", "Modulation": "OFDMA", "PowerLevel": "36.5"}],
    }),
    "vodafone_station_cga_json": lambda: parse_vodafone_station_cga_json({
        "ofdm_downstream": [{"channelid_ofdm": "193", "CentralFrequency_ofdm": "690000000", "power_ofdm": "0", "SNR_ofdm": "41.8"}],
        "ofdma_upstream": [{"channelidup": "41", "CentralFrequency": "36200000", "power": "36.5"}],
    }),
    "vodafone_station_tg_embedded_json": lambda: parse_vodafone_station_tg_embedded_json(TG_SUCCESS),
}


@pytest.mark.parametrize("profile", sorted(SUCCESS_PROFILES))
def test_each_explicit_profile_is_directly_callable_without_transport(profile):
    result = SUCCESS_PROFILES[profile]()
    assert isinstance(result, ParseResult)
    assert result.value is not None


EMPTY_OR_MISSING_PROFILES = {
    "pyur_api_v1": lambda: parse_pyur_api_v1([{"Downstreams": [], "Upstreams": []}]),
    "arris_html": lambda: parse_arris_html(""),
    "cgm4981_columnar_html": lambda: parse_cgm4981_columnar_html(""),
    "ch7465_xml": lambda: parse_ch7465_xml("<root/>", "<root/>"),
    "cm1000_html_table": lambda: parse_cm1000_html_table(""),
    "cm1000_javascript": lambda: parse_cm1000_javascript(""),
    "cm3000_javascript": lambda: parse_cm3000_javascript(""),
    "cm3500_html": lambda: parse_cm3500_html(""),
    "f3896lg_rest_json": lambda: parse_f3896lg_rest_json({}),
    "fritzbox_data_lua": lambda: parse_fritzbox_data_lua({}),
    "generic_no_docsis": parse_generic_no_docsis,
    "hitron_coda4680_json": lambda: parse_hitron_coda4680_json({}),
    "hitron_coda56_json": lambda: parse_hitron_coda56_json({}),
    "sagemcom_xmo_json": lambda: parse_sagemcom_xmo_json({}),
    "sb6141_transposed_html": lambda: parse_sb6141_transposed_html(""),
    "sb6183_html": lambda: parse_sb6183_html(""),
    "sb6190_html": lambda: parse_sb6190_html(""),
    "sercom_dm1000_json": lambda: parse_sercom_dm1000_json({}),
    "surfboard_hnap": lambda: parse_surfboard_hnap("", ""),
    "tc4400_html": lambda: parse_tc4400_html(None, None),
    "ultrahub7_json": lambda: parse_ultrahub7_json({}),
    "vodafone_station_cga_json": lambda: parse_vodafone_station_cga_json({}),
    "vodafone_station_tg_embedded_json": lambda: parse_vodafone_station_tg_embedded_json(""),
}


NULL_PROFILES = {
    "arris_html": lambda: parse_arris_html(None),
    "cgm4981_columnar_html": lambda: parse_cgm4981_columnar_html(None),
    "ch7465_xml": lambda: parse_ch7465_xml(None, None),
    "cm1000_html_table": lambda: parse_cm1000_html_table(None),
    "cm1000_javascript": lambda: parse_cm1000_javascript(None),
    "cm3000_javascript": lambda: parse_cm3000_javascript(None),
    "cm3500_html": lambda: parse_cm3500_html(None),
    "f3896lg_rest_json": lambda: parse_f3896lg_rest_json(None),
    "fritzbox_data_lua": lambda: parse_fritzbox_data_lua(None),
    "hitron_coda4680_json": lambda: parse_hitron_coda4680_json(None),
    "hitron_coda56_json": lambda: parse_hitron_coda56_json(None),
    "sagemcom_xmo_json": lambda: parse_sagemcom_xmo_json(None),
    "sb6141_transposed_html": lambda: parse_sb6141_transposed_html(None),
    "sb6183_html": lambda: parse_sb6183_html(None),
    "sb6190_html": lambda: parse_sb6190_html(None),
    "sercom_dm1000_json": lambda: parse_sercom_dm1000_json(None),
    "surfboard_hnap": lambda: parse_surfboard_hnap(None, None),
    "tc4400_html": lambda: parse_tc4400_html(None, None),
    "ultrahub7_json": lambda: parse_ultrahub7_json(None),
    "vodafone_station_cga_json": lambda: parse_vodafone_station_cga_json(None),
    "vodafone_station_tg_embedded_json": lambda: parse_vodafone_station_tg_embedded_json(None),
}


def _assert_payload_safe_result(result):
    assert isinstance(result, ParseResult)
    for issue in result.diagnostics:
        assert issue.family and issue.profile and issue.code
        assert not hasattr(issue, "message")


@pytest.mark.parametrize("profile", sorted(EMPTY_OR_MISSING_PROFILES))
def test_each_profile_handles_empty_or_missing_payload(profile):
    _assert_payload_safe_result(EMPTY_OR_MISSING_PROFILES[profile]())


@pytest.mark.parametrize("profile", sorted(NULL_PROFILES))
def test_each_payload_profile_handles_null_payload(profile):
    _assert_payload_safe_result(NULL_PROFILES[profile]())


MALFORMED_PROFILES = {
    "arris_html": lambda: parse_arris_html("<table><tr><td>bad</td></tr></table>"),
    "cgm4981_columnar_html": lambda: parse_cgm4981_columnar_html(">Downstream<<tr><th>Channel ID</th><td><div class=\"netWidth\">bad</div></td></tr>"),
    "ch7465_xml": lambda: parse_ch7465_xml("<root>", "<root/>"),
    "cm1000_html_table": lambda: parse_cm1000_html_table("<table id=dsTable><tr><td>bad</td></tr></table>"),
    "cm1000_javascript": lambda: parse_cm1000_javascript("function InitDsTableTagValue(){var tagValueList='1|short';}"),
    "cm3000_javascript": lambda: parse_cm3000_javascript("function InitDsTableTagValue(){var tagValueList='1|1|Locked|QAM|bad|bad|bad|bad|bad|';}"),
    "cm3500_html": lambda: parse_cm3500_html("<h4>Downstream QAM</h4><table><tr><td>bad</td></tr></table>"),
    "f3896lg_rest_json": lambda: parse_f3896lg_rest_json({"downstream": [], "upstream": [{"lockStatus": True, "channelType": "ofdma", "power": "bad"}]}),
    "fritzbox_data_lua": lambda: parse_fritzbox_data_lua({"channelUs": {"docsis31": [{"powerLevel": None}]}}),
    "generic_no_docsis": parse_generic_no_docsis,
    "hitron_coda4680_json": lambda: parse_hitron_coda4680_json({"downstream": {"Freq_List": [{}]}}),
    "hitron_coda56_json": lambda: parse_hitron_coda56_json({"downstream": [{}]}),
    "sagemcom_xmo_json": lambda: parse_sagemcom_xmo_json({"downstream": [], "upstream": [{"LockStatus": True, "Modulation": None}]}),
    "sb6141_transposed_html": lambda: parse_sb6141_transposed_html(SB6141_SUCCESS.replace("<td>7</td>", "<td>bad</td>", 1)),
    "sb6183_html": lambda: parse_sb6183_html("<table><tr><th>Downstream Bonded</th></tr><tr><td>bad</td></tr></table>"),
    "sb6190_html": lambda: parse_sb6190_html("<table><tr><th>Downstream Bonded</th></tr><tr><td>bad</td></tr></table>"),
    "sercom_dm1000_json": lambda: parse_sercom_dm1000_json({"downstream": [{"qamD": "256QAM"}]}),
    "surfboard_hnap": lambda: parse_surfboard_hnap("1^Locked^QAM^bad^bad^bad^bad^bad^bad^", ""),
    "tc4400_html": lambda: parse_tc4400_html(None, None),
    "ultrahub7_json": lambda: parse_ultrahub7_json({"downstream": [{"ChannelID": "bad"}], "upstream": []}),
    "vodafone_station_cga_json": lambda: parse_vodafone_station_cga_json({"downstream": [None]}),
    "vodafone_station_tg_embedded_json": lambda: parse_vodafone_station_tg_embedded_json("json_dsData=[{bad}];"),
}


@pytest.mark.parametrize("profile", sorted(MALFORMED_PROFILES))
def test_each_profile_handles_empty_missing_or_malformed_input_without_payload_diagnostics(profile):
    result = MALFORMED_PROFILES[profile]()
    assert isinstance(result, ParseResult)
    for issue in result.diagnostics:
        assert issue.family and issue.profile and issue.code
        assert not hasattr(issue, "message")


def test_locked_active_and_docsis31_status_rules_are_profile_specific():
    unlocked = ARRIS_SUCCESS.replace("<td>Locked</td>", "<td>Not Locked</td>")
    assert parse_arris_html(unlocked).value["channelDs"]["docsis30"] == []

    inactive = parse_hitron_coda56_json({
        "downstream_ofdm": [{"plclock": "NO"}],
        "upstream_ofdma": [{"state": "DISABLED"}],
    }).value
    assert inactive["channelDs"]["docsis31"] == []
    assert inactive["channelUs"]["docsis31"] == []

    success = parse_arris_html(ARRIS_SUCCESS).value
    assert success["channelDs"]["docsis31"][0]["type"] == "OFDM"
    assert success["channelUs"]["docsis31"][0]["type"] == "OFDMA"


@pytest.mark.parametrize("parse", [
    lambda: parse_hitron_coda56_json({"upstream_ofdma": [{"state": "OPERATE"}]}),
    lambda: parse_hitron_coda4680_json({"upstream_ofdma": {"OFDMAs_List": [{"state": "OPERATE"}]}}),
])
def test_hitron_ofdma_row_dropped_as_invalid_reports_only_the_invalid_row(parse):
    assert [issue.code for issue in parse().diagnostics] == ["invalid_row"]


def _lanes(value: dict) -> list[dict]:
    if "downstream" in value:
        return value["downstream"] + value["upstream"]
    return [channel for side in ("channelDs", "channelUs") for lane in value[side].values() for channel in lane]


_ABSENT = object()


def _present(**fields):
    return {key: value for key, value in fields.items() if value is not _ABSENT}


def _rows(reading, ids, frequencies):
    return list(zip(ids, frequencies or (reading,) * len(ids)))


def _cga(reading, ids=("7",), frequencies=None):
    lanes = {
        "downstream": lambda cid, freq: _present(channelid=cid, CentralFrequency=freq, power=reading, SNR=reading),
        "ofdm_downstream": lambda cid, freq: _present(
            channelid_ofdm=cid, CentralFrequency_ofdm=freq, power_ofdm=reading, SNR_ofdm=reading,
        ),
        "upstream": lambda cid, freq: _present(channelidup=cid, CentralFrequency=freq, power=reading),
        "ofdma_upstream": lambda cid, freq: _present(channelidup=cid, CentralFrequency=freq, power=reading),
    }
    rows = _rows(reading, ids, frequencies)
    return parse_vodafone_station_cga_json({lane: [row(*r) for r in rows] for lane, row in lanes.items()})


def _tg(reading, ids=(7,), frequencies=None):
    rows = json.dumps([
        _present(ChannelID=cid, Frequency=freq, PowerLevel=reading, SNRLevel=reading)
        for cid, freq in _rows(reading, ids, frequencies)
    ])
    return parse_vodafone_station_tg_embedded_json(f"<script>json_dsData={rows};json_usData={rows};</script>")


def _ultrahub7(reading, ids=("7",), frequencies=None):
    rows = [
        _present(ChannelID=cid, Frequency=freq, PowerLevel=reading, SNRLevel=reading)
        for cid, freq in _rows(reading, ids, frequencies)
    ]
    return parse_ultrahub7_json({"downstream": rows, "upstream": rows})


# Each profile keeps its established form of a missing frequency so channel history continues.
@pytest.mark.parametrize(("parse", "missing_frequency", "lanes"), [
    (_ultrahub7, "0 MHz", 2), (_cga, "", 4), (_tg, "", 2),
])
@pytest.mark.parametrize(("reading", "power", "frequency"), [
    *[(reading, power, reading) for reading, power in (
        (0, "0.0"), (-0.0, "0.0"), ("-0.0 dBmV", "-0.0"),
        (_ABSENT, "None"), (None, "None"), ("", "None"), (" ", "None"), ("N/A", "None"), (False, "None"),
    )],
    # A non-finite frequency drops the row (see below), so these readings go with a missing frequency.
    *[(reading, "None", _ABSENT) for reading in ("NaN", "Infinity", "1e400")],
])
def test_vodafone_keeps_zero_power_and_reports_unreadable_readings_as_none(
    parse, missing_frequency, lanes, reading, power, frequency,
):
    channels = _lanes(parse(reading, frequencies=(frequency,)).value)
    assert [
        (channel["frequency"], repr(channel["powerLevel"]), channel.get("mer"), channel.get("mse"))
        for channel in channels
    ] == [(missing_frequency, power, None, None)] * lanes


@pytest.mark.parametrize(("parse", "ids", "frequencies", "kept", "lanes"), [
    (_cga, (7, 193.0), None, [7, 193], 4),
    (_cga, (None, "7"), None, [0, 7], 4),
    *[(_cga, (bad, "7"), None, [7], 4) for bad in (True, False, [7], {"bad": 7}, "Infinity")],
    (_ultrahub7, (float("inf"), "7"), None, ["7"], 2),
    (_tg, ("Infinity", 7), None, [7], 2),
    # A non-empty list or object as frequency is malformed on the CGA variant; elsewhere it reads as missing.
    (_cga, ("7",), ([591],), [], 4), (_cga, ("7",), ({"MHz": 591},), [], 4), (_cga, ("7",), ([],), [7], 4),
    (_tg, (7,), ([591],), [7], 2), (_ultrahub7, ("7",), ([591],), ["7"], 2),
    # A non-finite frequency is invalid, so it cannot shadow a row with the same ID and a missing frequency.
    *[(parse, (cid, cid), (bad, _ABSENT), [kept], lanes)
      for parse, cid, kept, lanes in ((_cga, "7", 7, 4), (_tg, 7, 7, 2), (_ultrahub7, "7", "7", 2))
      for bad in ("NaN", "Infinity", "1e400")],
])
def test_vodafone_drops_only_rows_with_invalid_ids_or_malformed_frequency(parse, ids, frequencies, kept, lanes):
    result = parse("1.5", ids, frequencies)
    assert [channel["channelID"] for channel in _lanes(result.value)] == kept * lanes
    assert [issue.code for issue in result.diagnostics] == ["invalid_channel"] * (len(ids) - len(kept)) * lanes


@pytest.mark.parametrize(("chid", "freq", "power", "mer", "expected"), [
    ("7", "602000000", None, None, [(None, None)] * 2),
    ("7", "591 MHz", "N/A", None, [(None, None)] * 2),
    ("7", "591 MHz", "nan", None, [(None, None)] * 2),
    ("7", "591 MHz", "1.5", "N/A", [(1.5, None)] * 2),
    ("7", "591 MHz", "1.5", "Infinity", [(1.5, None)] * 2),
    ("7", None, None, None, []),
    ("7", "Unlocked", "N/A", None, []),
    ("7", "591MHz", None, None, [(None, None)] * 2),
    ("7", "+591 MHz", None, None, [(None, None)] * 2),
    ("7", "591 MHz Unlocked", "N/A", None, []),
    ("7", "1" + "0" * 400 + " MHz", None, None, []),
    pytest.param("7", "9" * 1_000_001 + " MHz", None, None, [], id="frequency-beyond-decimal-range"),
    pytest.param("7", "9" * 1_000_001 + " MHz", "1.5", None, [(1.5, None)] * 2, id="same-frequency-with-power"),
    ("0", "591 MHz", "N/A", None, []),
    ("0", None, "N/A", None, []),
])
def test_ch7465_unreadable_readings_are_none_and_only_plausible_rows_are_kept(chid, freq, power, mer, expected):
    def row(id_tag, power_tag):
        fields = ((id_tag, chid), ("freq", freq), (power_tag, power), ("RxMER", mer))
        return "".join(f"<{tag}>{text}</{tag}>" for tag, text in fields if text is not None)

    result = parse_ch7465_xml(
        f"<root><downstream>{row('chid', 'pow')}</downstream></root>",
        f"<root><upstream>{row('usid', 'power')}</upstream></root>",
    )
    channels = result.value["downstream"] + result.value["upstream"]
    assert [(channel["powerLevel"], channel.get("mer")) for channel in channels] == expected
    assert [issue.code for issue in result.diagnostics] == ([] if expected else ["invalid_channel"] * 2)


def test_result_and_diagnostics_are_immutable_contract_objects():
    result = parse_ch7465_xml("<root>", "<root/>")
    with pytest.raises(AttributeError):
        result.value = {}
    with pytest.raises(AttributeError):
        result.diagnostics[0].code = "changed"
