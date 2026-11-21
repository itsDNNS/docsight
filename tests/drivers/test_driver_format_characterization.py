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
SB_ROW = f"<tr><td>1</td><td>Locked</td><td>{MARK}</td><td>7</td><td>591000000 Hz</td><td>1</td><td>1</td><td>nan</td><td>1</td></tr>"
TC_HEADER = "<tr><th>Channel ID</th><th>Lock Status</th><th>Channel Type</th><th>Modulation</th><th>Frequency</th><th>Power</th><th>SNR</th><th>Corrected</th><th>Uncorrected</th></tr>"
CM1000_HEADER = "<tr><th>Channel</th><th>Lock Status</th><th>Modulation</th><th>Channel ID</th><th>Frequency</th></tr>"
CM1000_BAD_ID_ROW = f"<tr><td>1</td><td>Locked</td><td>256QAM</td><td>{MARK}</td><td>591000000</td></tr>"
PYUR_CHANNEL = {"channelID": 7, "frequency": "", "powerLevel": None, "modulation": "", "mer": None, "mse": None, "corrErrors": 0, "nonCorrErrors": 0}


def _bonded(n: int) -> str:
    return f"<table><tr><th>Downstream Bonded Channels</th></tr>{SB_ROW * n}</table>"


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
    "cm3500_html": lambda n: (_cm3500(f"<h4>Downstream QAM</h4><table><tr></tr>{f'<tr><td>Downstream 1</td><td>nan</td><td>1</td><td>1</td><td>1</td><td>{MARK}</td><td>1</td><td>1</td><td>1</td></tr>' * n}</table>"), EMPTY_SPLIT),
    "f3896lg_rest_json": lambda n: (_f3896([{"lockStatus": True, "channelType": "sc_qam", "frequency": MARK}] * n, []), EMPTY_SPLIT),
    "fritzbox_data_lua": lambda n: (_fritz(_split(us31=[{"channelID": 6, "powerLevel": MARK}] * n)), _split(us31=[{"channelID": 6, "powerLevel": MARK}] * n)),
    "hitron_coda4680_json": lambda n: (_hitron_4680({"/1/Device/CM/DsInfo": {"Freq_List": [{"portId": MARK}] * n}, "/1/Device/CM/UsInfo": {}, "/1/Device/CM/DsOfdm": {}, "/1/Device/CM/UsOfdm": {}}), EMPTY_SPLIT),
    "hitron_coda56_json": lambda n: (_hitron({"/data/dsinfo.asp": [{"portId": MARK}] * n, "/data/usinfo.asp": [], "/data/dsofdminfo.asp": [], "/data/usofdminfo.asp": []}), EMPTY_SPLIT),
    "pyur_api_v1": lambda n: (_pyur([{"Downstreams": [{"ChannelID": MARK}] * n + [{"ChannelID": "7", "id": 1}], "Upstreams": [], "CMErrorCodewords": [{"id": 1, "CorrectableCodewords": 0, "UncorrectableCodewords": 0}]}]), _split([PYUR_CHANNEL])),
    "sagemcom_xmo_json": lambda n: (_sagemcom([{"LockStatus": True, "BandWidth": MARK}] * n, []), EMPTY_SPLIT),
    "sb6141_transposed_html": lambda n: (_page(SB6141Driver, f"<table><tr><th>Downstream</th></tr><tr><td>Channel ID</td>{f'<td>{MARK}</td>' * n}</tr></table>"), EMPTY_SPLIT),
    "sb6183_html": lambda n: (_page(SB6183Driver, _bonded(n)), EMPTY_SPLIT),
    "sb6190_html": lambda n: (_page(SB6190Driver, _bonded(n)), EMPTY_SPLIT),
    "sb8200_cbn_xml": lambda n: (_sb8200_cbn(f"<downstream_table>{f'<downstream><dsid>{MARK}</dsid></downstream>' * n}</downstream_table>", "<upstream_table/>", "<downstreamOFDM_table/>", "<upstreamOFDMA_table/>", "<signal_table/>"), EMPTY_SPLIT),
    "sercom_dm1000_json": lambda n: (_sercom([{"qamD": MARK}] * n, [], [], []), EMPTY_SPLIT),
    "surfboard_hnap": lambda n: (_surfboard("|+|".join([f"1^Locked^256QAM^{MARK}^bad^bad^bad^bad^bad^"] * n), ""), EMPTY_SPLIT),
    "tc4400_html": lambda n: (_tc(f"<table>{TC_HEADER}{f'<tr><td>7</td><td>Locked</td><td>SC-QAM</td><td>{MARK}</td><td>591000000 Hz</td><td>1</td><td>1</td><td>nan</td><td>1</td></tr>' * n}</table>", "<table></table>"), EMPTY_FLAT_31),
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
