"""Exact characterization assertions for current modem parser seams."""

from __future__ import annotations

from collections import Counter
import logging

from bs4 import BeautifulSoup
import pytest

from app.drivers.cm8200 import CM8200Driver
from app.drivers.formats import FORMAT_PROFILE_MODULES
from app.drivers.sb6141 import SB6141Driver
from app.drivers.sb6183 import SB6183Driver
from app.drivers.sb6190 import SB6190Driver
from tests.drivers.driver_format_cases import (
    CASES, CASE_BY_ID, EMPTY_FLAT_31, EMPTY_SPLIT,
    _cgm, _cgm_html, _ch7465, _cm1000, _cm3000, _cm3000_html, _cm3500, _f3896, _fritz, _hitron,
    _hitron_4680, _page, _poll, _pyur, _sagemcom, _sb8200_cbn, _sercom, _split, _surfboard,
    _tc, _ultrahub, _vodafone_cga, _vodafone_tg,
)


FAMILIES_WITHOUT_DOCSIS_31_CHANNELS = {
    "ch7465_xml",
    "cm1000_javascript",
    "generic_no_docsis",
    "sb6141_transposed_html",
    "sb6183_html",
    "sb6190_html",
}


def _has_ofdm_or_ofdma(output) -> bool:
    if isinstance(output, dict):
        if output.get("type") in {"OFDM", "OFDMA"}:
            return True
        return any(_has_ofdm_or_ofdma(value) for value in output.values())
    if isinstance(output, list):
        return any(_has_ofdm_or_ofdma(value) for value in output)
    return False


def test_case_registry_is_complete_and_has_three_boundary_cases_per_family():
    assert Counter(case.family for case in CASES) == {family: 3 for family in FORMAT_PROFILE_MODULES}
    assert list(CASE_BY_ID) == sorted(CASE_BY_ID)


def test_each_current_parser_observation_matches_the_frozen_normalized_structure():
    mismatches = {}
    for case in CASES:
        actual = case.observe().output
        if actual != case.expected:
            mismatches[case.case_id] = {"expected": case.expected, "actual": actual}
    assert mismatches == {}


def test_supported_docsis31_families_have_ofdm_or_ofdma_in_success_output():
    covered = {
        case.family
        for case in CASES
        if ".success" in case.case_id and _has_ofdm_or_ofdma(case.expected)
    }
    assert covered == set(FORMAT_PROFILE_MODULES) - FAMILIES_WITHOUT_DOCSIS_31_CHANNELS


def test_fritzbox_boundary_preserves_order_duplicates_and_missing_channel_ids():
    output = CASE_BY_ID["fritzbox_data_lua.success_duplicates_missing_id"].observe().output
    channels = output["channelDs"]["docsis30"]
    assert [channel.get("channelID") for channel in channels] == [1, 1, None]
    assert len(channels) == 3
    assert channels[0]["powerLevel"] == 0
    assert channels[1]["powerLevel"] is None
    assert "channelID" not in channels[2]


def test_malformed_diagnostics_are_stable_across_repeated_observation():
    for case in CASES:
        if ".malformed" not in case.case_id:
            continue
        assert case.observe().diagnostics == case.observe().diagnostics


MARK = "RAWCELLMARKER"  # A raw cell value that must never reach the log.


def _tr(*cells) -> str:
    return "<tr>" + "".join(f"<td>{cell}</td>" for cell in cells) + "</tr>"


# The Arris profile rejects this row by its channel ID; the SB profiles keep it without the corrected count.
SB_ROW = _tr(MARK, "Locked", "QAM256", 7, "591000000 Hz", 1, 1, MARK, 1)
SB_CHANNEL = {"channelID": 7, "frequency": "591 MHz", "powerLevel": 1.0, "mer": 1.0, "mse": -1.0, "modulation": "QAM256", "corrErrors": None, "nonCorrErrors": 1}
TC_CHANNEL = {"channelID": "7", "type": "256QAM", "frequency": "591 MHz", "powerLevel": 1.0, "mse": -1.0, "mer": 1.0, "corrErrors": None, "nonCorrErrors": 1}
TC_HEADER = "<tr><th>Channel ID</th><th>Lock Status</th><th>Channel Type</th><th>Modulation</th><th>Frequency</th><th>Power</th><th>SNR</th><th>Corrected</th><th>Uncorrected</th></tr>"
CM1000_HEADER = "<tr><th>Channel</th><th>Lock Status</th><th>Modulation</th><th>Channel ID</th><th>Frequency</th></tr>"
CM1000_BAD_ID_ROW = f"<tr><td>1</td><td>Locked</td><td>256QAM</td><td>{MARK}</td><td>591000000</td></tr>"
PYUR_CHANNEL = {"channelID": 7, "frequency": "", "powerLevel": None, "modulation": "", "mer": None, "mse": None, "corrErrors": 0, "nonCorrErrors": 0}


def _bonded(n: int, row: str = SB_ROW) -> str:
    return f"<table><tr><th>Downstream Bonded Channels</th></tr>{row * n}</table>"


def _cm1000_table(table_id: str, header: str, row: str, n: int) -> str:
    return f"<table id='{table_id}'>{header}{row * n}</table>"


# Each entry polls the public driver with n identical malformed downstream rows and returns
# (parsed value, expected value); the expected value is what the driver returned before.
# A key may name a variant after the format, as in "format:variant".
MALFORMED_ROWS = {
    "arris_html": lambda n: (_poll(CM8200Driver("https://modem.invalid", "admin", "password"), "_fetch_status_page", return_value=BeautifulSoup(_bonded(n), "html.parser")), EMPTY_SPLIT),
    "cgm4981_columnar_html": lambda n: (_cgm(_cgm_html({"Channel ID": [MARK] * n, "Lock Status": ["Locked"] * n}, {}, {})), EMPTY_SPLIT),
    "ch7465_xml": lambda n: (_ch7465(f"<root>{f'<downstream><chid>{MARK}</chid></downstream>' * n}</root>", "<root/>"), {"docsis": "3.0", "downstream": [], "upstream": []}),
    "cm1000_html_table": lambda n: (_cm1000(_cm1000_table("dsTable", CM1000_HEADER, CM1000_BAD_ID_ROW, n)), EMPTY_SPLIT),
    "cm1000_html_table:header_without_channel": lambda n: (_cm1000(_cm1000_table("dsTable", "<tr><th>Lock Status</th><th>Frequency</th></tr>", f"<tr><td>Locked</td><td>{MARK}</td></tr>", n)), EMPTY_SPLIT),
    "cm1000_html_table:short_row": lambda n: (_cm1000(_cm1000_table("dsTable", CM1000_HEADER, f"<tr><td>1</td><td>Locked</td><td>{MARK}</td></tr>", n)), EMPTY_SPLIT),
    "cm1000_html_table:one_row_per_table": lambda n: (_cm1000("".join(_cm1000_table(table_id, CM1000_HEADER, CM1000_BAD_ID_ROW, 1) for table_id in ("dsTable", "d31dsTable")[:n])), EMPTY_SPLIT),
    "cm1000_javascript": lambda n: (_cm1000(f"<script>function InitDsTableTagValue(){{var tagValueList='{n}|{f'1|Locked|256QAM|{MARK}|591000000|1|1|' * n}';}}</script>"), EMPTY_SPLIT),
    "cm3000_javascript": lambda n: (_cm3000(_cm3000_html(f"{n}|" + f"1|Locked|QAM256|{MARK}|591000000 Hz|x|y|z|q|" * n, "", "", "")), EMPTY_SPLIT),
    "cm3500_html": lambda n: (_cm3500(f"<h4>Downstream QAM</h4><table><tr></tr>{_tr('Downstream 1', 'inf', 1, 1, 1, MARK, 1, 1, 1) * n}</table>"), EMPTY_SPLIT),
    "cm3500_html:ofdm_frequency_edge": lambda n: (_cm3500(f"<h4>Downstream OFDM</h4><table><tbody>{_tr('Downstream 1', MARK, 190, 3800, 'inf', 324, 47, 40, 41) * n}</tbody></table>"), EMPTY_SPLIT),
    "f3896lg_rest_json": lambda n: (_f3896([{"lockStatus": True, "channelType": "sc_qam", "frequency": MARK}] * n, []), EMPTY_SPLIT),
    "fritzbox_data_lua": lambda n: (_fritz(_split(us31=[{"channelID": 6, "powerLevel": MARK} for _ in range(n)])), _split(us31=[{"channelID": 6, "powerLevel": None}] * n)),
    "hitron_coda4680_json": lambda n: (_hitron_4680({"/1/Device/CM/DsInfo": {"Freq_List": [{"portId": MARK}] * n}, "/1/Device/CM/UsInfo": {}, "/1/Device/CM/DsOfdm": {}, "/1/Device/CM/UsOfdm": {}}), EMPTY_SPLIT),
    "hitron_coda56_json": lambda n: (_hitron({"/data/dsinfo.asp": [{"portId": MARK}] * n, "/data/usinfo.asp": [], "/data/dsofdminfo.asp": [], "/data/usofdminfo.asp": []}), EMPTY_SPLIT),
    "pyur_api_v1": lambda n: (_pyur([{"Downstreams": [{"ChannelID": MARK}] * n + [{"ChannelID": "7", "id": 1}], "Upstreams": [], "CMErrorCodewords": [{"id": 1, "CorrectableCodewords": 0, "UncorrectableCodewords": 0}]}]), _split([PYUR_CHANNEL])),
    "sagemcom_xmo_json": lambda n: (_sagemcom([{"LockStatus": True, "BandWidth": MARK}] * n, []), EMPTY_SPLIT),
    "sb6141_transposed_html": lambda n: (_page(SB6141Driver, f"<table><tr><th>Downstream</th></tr><tr><td>Channel ID</td>{f'<td>{MARK}</td>' * n}</tr></table>"), EMPTY_SPLIT),
    "sb6183_html": lambda n: (_page(SB6183Driver, _bonded(n)), _split([SB_CHANNEL] * n)),
    "sb6190_html": lambda n: (_page(SB6190Driver, _bonded(n)), _split([SB_CHANNEL | {"frequency": "591000000 MHz"}] * n)),
    "sb8200_cbn_xml": lambda n: (_sb8200_cbn(f"<downstream_table>{f'<downstream><dsid>{MARK}</dsid></downstream>' * n}</downstream_table>", "<upstream_table/>", "<downstreamOFDM_table/>", "<upstreamOFDMA_table/>", "<signal_table/>"), EMPTY_SPLIT),
    "sercom_dm1000_json": lambda n: (_sercom([{"qamD": MARK}] * n, [], [], []), EMPTY_SPLIT),
    "surfboard_hnap": lambda n: (_surfboard("|+|".join([f"1^Locked^256QAM^{MARK}^bad^bad^bad^bad^bad^"] * n), ""), EMPTY_SPLIT),
    "tc4400_html": lambda n: (_tc(f"<table>{TC_HEADER}{_tr(7, 'Locked', 'SC-QAM', '256QAM', '591000000 Hz', 1, 1, MARK, 1) * n}</table>", "<table></table>"), {**EMPTY_FLAT_31, "downstream": [TC_CHANNEL] * n}),
    "ultrahub7_json": lambda n: (_ultrahub([{"ChannelID": MARK}] * n, []), EMPTY_FLAT_31),
    "vodafone_station_cga_json": lambda n: (_vodafone_cga({"downstream": [{"channelid": [MARK]}] * n}), EMPTY_SPLIT),
    "vodafone_station_tg_embedded_json": lambda n: (_vodafone_tg(f"<script>json_dsData=[{','.join([f'{{\"ChannelID\":\"{MARK}\"}}'] * n)}];json_usData=[];</script>"), EMPTY_SPLIT),
}


@pytest.mark.parametrize("rows", [1, 2])
@pytest.mark.parametrize("case", sorted(MALFORMED_ROWS))
def test_driver_poll_logs_one_payload_free_warning_per_diagnostic_and_keeps_parsed_values(case, rows, caplog):
    with caplog.at_level(logging.DEBUG):
        actual, expected = MALFORMED_ROWS[case](rows)
    assert actual == expected
    records = [record for record in caplog.records if case.partition(":")[0] in record.getMessage()]
    assert [record.levelno for record in records] == [logging.WARNING]
    assert records[0].getMessage().endswith(f"rows={rows})")
    assert MARK not in caplog.text


def test_cm1000_logs_tag_values_it_rejects_before_falling_back_to_the_table(caplog):
    with caplog.at_level(logging.WARNING):
        assert CASE_BY_ID["cm1000_javascript.malformed_row_width"].observe().output == EMPTY_SPLIT
    assert "cm1000_javascript parser reported invalid_framing (direction=None, field=InitDsTableTagValue, rows=1)" in caplog.messages


def test_healthy_fixtures_log_no_parser_warning():
    noisy = {
        case.case_id for case in CASES if ".success" in case.case_id
        and any("parser reported" in item.get("message", "") for item in case.observe().diagnostics)
    }
    assert noisy == set()


def _first_downstream(output) -> dict:
    return (output["channelDs"]["docsis30"] if "channelDs" in output else output["downstream"])[0]


# Each entry polls one format with `cell` as the frequency and every measurement of one downstream channel.
MEASUREMENT_CELLS = {
    "cgm4981_columnar_html": lambda c: _cgm(_cgm_html({"Channel ID": ["7"], "Lock Status": ["Locked"], "Power Level": [c], "SNR": [c]}, {}, {"Channel ID": ["7"], "Correctable Codewords": [c], "Uncorrectable Codewords": [c]})),
    "sagemcom_xmo_json": lambda c: _sagemcom([_sagemcom_row(c)], []),
    "arris_html": lambda c: _poll(CM8200Driver("https://modem.invalid", "admin", "password"), "_fetch_status_page", return_value=BeautifulSoup(_bonded(1, _tr(7, "Locked", "QAM256", c, c, c, c, c)), "html.parser")),
    # No trailing delimiter, so an empty last cell must still complete the row.
    "cm3000_javascript": lambda c: _cm3000(_cm3000_html(f"1|1|Locked|QAM256|7|{c}|{c}|{c}|{c}|{c}", "", "", "")),
    "cm3500_html": lambda c: _cm3500(f"<h4>Downstream QAM</h4><table><tr></tr>{_tr('Downstream 1', 7, c, c, c, 'QAM256', 1, c, c)}</table>"),
    "sb6141_transposed_html": lambda c: _page(SB6141Driver, "<table><tr><th>Downstream</th></tr>" + "".join(_tr(label, value) for label, value in (("Channel ID", 7), ("Frequency", c), ("Signal to Noise Ratio", c), ("Power Level", c))) + f"</table><table><tr><th>Codewords</th></tr>{_tr('Correctable', c)}{_tr('Uncorrectable', c)}</table>"),
    "sb6183_html": lambda c: _page(SB6183Driver, _bonded(1, _tr(1, "Locked", "QAM256", 7, c, c, c, c, c))),
    "sb6190_html": lambda c: _page(SB6190Driver, _bonded(1, _tr(1, "Locked", "QAM256", 7, c, c, c, c, c))),
    "tc4400_html": lambda c: _tc(f"<table>{TC_HEADER}{_tr(7, 'Locked', 'SC-QAM', '256QAM', c, c, c, c, c)}</table>", "<table></table>"),
}
MEASUREMENTS = ("powerLevel", "corrErrors", "nonCorrErrors", "mer", "mse")
# CGM4981 reads power and SNR by pattern, so only its codeword cells are checked for unreadable text.
CELL_KEYS = {"cgm4981_columnar_html": ("corrErrors", "nonCorrErrors")}


def test_cgm4981_oversized_numbers_are_unavailable():
    huge = "9" * 400
    rows = {"Channel ID": ["7"], "Lock Status": ["Locked"], "Frequency": [huge], "Power Level": [huge], "SNR": [huge]}
    output = _cgm(_cgm_html(rows, rows, {}))
    ds, us = _first_downstream(output), output["channelUs"]["docsis30"][0]
    assert [ds["frequency"], ds["powerLevel"], ds["mer"], ds["mse"], us["frequency"], us["powerLevel"]] == ["", None, None, None, "", None]


def _sagemcom_row(reading=None) -> dict:
    row = {"ChannelID": 7, "LockStatus": True, "Frequency": 591000000, "Modulation": "Qam256", "BandWidth": 8000000}
    keys = ("PowerLevel", "SNR", "CorrectableCodewords", "UncorrectableCodewords")
    return row if reading is None else row | dict.fromkeys(keys, reading)


def _assert_unavailable_and_reported(channel, keys, level, caplog):
    assert {key: channel[key] for key in keys if key in channel} == dict.fromkeys(set(keys) & set(channel))
    assert {record.levelno for record in caplog.records if "parser reported" in record.getMessage()} == {level}
    assert MARK not in caplog.text


@pytest.mark.parametrize("cell", [MARK, "inf", "-Infinity", "nan", "1e400", ""])
@pytest.mark.parametrize("case", sorted(MEASUREMENT_CELLS))
def test_unreadable_measurement_cells_are_reported_and_unavailable_instead_of_zero(case, cell, caplog):
    with caplog.at_level(logging.DEBUG):
        channel = _first_downstream(MEASUREMENT_CELLS[case](cell))
    _assert_unavailable_and_reported(channel, CELL_KEYS.get(case, MEASUREMENTS), logging.WARNING if cell else logging.DEBUG, caplog)


# JSON readings that are missing, not finite or not numbers are unavailable too.
@pytest.mark.parametrize(("reading", "level"), [
    (None, logging.DEBUG), (float("inf"), logging.WARNING), (float("nan"), logging.WARNING), (True, logging.WARNING),
])
def test_sagemcom_missing_or_non_finite_json_readings_are_unavailable(reading, level, caplog):
    with caplog.at_level(logging.DEBUG):
        output = _sagemcom([_sagemcom_row(reading)], [_sagemcom_row(reading)])
    _assert_unavailable_and_reported(_first_downstream(output), MEASUREMENTS, level, caplog)
    assert output["channelUs"]["docsis30"][0]["powerLevel"] is None


@pytest.mark.parametrize("zero", ["0", 0])
@pytest.mark.parametrize("case", sorted(MEASUREMENT_CELLS))
def test_measurements_the_modem_reports_as_zero_stay_zero(case, zero):
    channel = _first_downstream(MEASUREMENT_CELLS[case](zero))
    keys = set(MEASUREMENTS) & set(channel)
    assert {key: channel[key] for key in keys} == dict.fromkeys(keys, 0)


@pytest.mark.parametrize(("raw", "power", "level"), [
    *[(raw, None, logging.DEBUG) for raw in ({}, {"powerLevel": None}, {"powerLevel": " "})],
    *[({"powerLevel": bad}, None, logging.WARNING) for bad in (MARK, "inf", "nan")],
    ({"powerLevel": "0"}, "6.0", None), ({"powerLevel": 0}, "6.0", None),
])
def test_fritzbox_upstream_31_power_is_unavailable_when_missing_or_unreadable(raw, power, level, caplog):
    with caplog.at_level(logging.DEBUG):
        channel = _fritz(_split(us31=[{"channelID": 5, **raw}]))["channelUs"]["docsis31"][0]
    assert channel["powerLevel"] == power
    assert [record.levelno for record in caplog.records if "fritzbox_data_lua" in record.getMessage()] == ([level] if level else [])
    assert MARK not in caplog.text


@pytest.mark.parametrize(("ds", "us"), [(None, []), ([], None), ([], MARK), ({}, [])])
def test_sagemcom_reports_a_channel_list_that_is_not_a_list_as_an_invalid_payload(ds, us, caplog):
    with caplog.at_level(logging.WARNING), pytest.raises(ValueError, match="invalid Sagemcom channel payload"):
        _sagemcom(ds, us)
    assert "sagemcom_xmo_json parser reported invalid_framing" in caplog.text
    assert MARK not in caplog.text


CM3500_OFDM_ROWS = {
    "Downstream OFDM": ("channelDs", ("Downstream 1", "4K", 190, 3800, 135, 324, 47, 40, 41), 4),
    "Upstream OFDM": ("channelUs", ("Upstream 0", "2K", 32, 640, 74, 773, 29.8, 64.8, 42.25), 6),
}


# The first row is skipped for an unreadable frequency edge or for being cut short.
@pytest.mark.parametrize("cut", [False, True])
@pytest.mark.parametrize("heading", sorted(CM3500_OFDM_ROWS))
def test_cm3500_ofdm_channels_keep_their_number_when_an_earlier_row_is_skipped(heading, cut):
    lane, row, edge = CM3500_OFDM_ROWS[heading]
    first = row[:5] if cut else row[:edge] + ("inf",) + row[edge + 1:]
    output = _cm3500(f"<h4>{heading}</h4><table><tbody>{_tr(*first)}{_tr(*row)}</tbody></table>")
    assert [channel["channelID"] for channel in output[lane]["docsis31"]] == [201]
