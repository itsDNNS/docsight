"""Exact characterization assertions for current modem parser seams."""

from __future__ import annotations

from collections import Counter

from tests.drivers.driver_format_cases import CASES, CASE_BY_ID


EXPECTED_FAMILIES = {
    "arris_html",
    "cgm4981_columnar_html",
    "ch7465_xml",
    "cm1000_html_table",
    "cm1000_javascript",
    "cm3000_javascript",
    "cm3500_html",
    "f3896lg_rest_json",
    "fritzbox_data_lua",
    "generic_no_docsis",
    "hitron_coda4680_json",
    "hitron_coda56_json",
    "sagemcom_xmo_json",
    "sb6141_transposed_html",
    "sb6183_html",
    "sb6190_html",
    "sb8200_cbn_xml",
    "sercom_dm1000_json",
    "surfboard_hnap",
    "tc4400_html",
    "ultrahub7_json",
    "vodafone_station_cga_json",
    "vodafone_station_tg_embedded_json",
}

FAMILIES_WITH_DOCSIS_31_CHANNELS = {
    "arris_html",
    "cgm4981_columnar_html",
    "cm1000_html_table",
    "cm3000_javascript",
    "cm3500_html",
    "f3896lg_rest_json",
    "fritzbox_data_lua",
    "hitron_coda4680_json",
    "hitron_coda56_json",
    "sagemcom_xmo_json",
    "sb8200_cbn_xml",
    "sercom_dm1000_json",
    "surfboard_hnap",
    "tc4400_html",
    "ultrahub7_json",
    "vodafone_station_cga_json",
    "vodafone_station_tg_embedded_json",
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
    counts = Counter(case.family for case in CASES)
    assert set(counts) == EXPECTED_FAMILIES
    assert counts == {family: 3 for family in EXPECTED_FAMILIES}
    assert len(CASE_BY_ID) == len(CASES) == 69
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
    assert covered == FAMILIES_WITH_DOCSIS_31_CHANNELS


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
