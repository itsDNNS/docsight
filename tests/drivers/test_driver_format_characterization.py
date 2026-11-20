"""Exact characterization assertions for current modem parser seams."""

from __future__ import annotations

from collections import Counter

from app.drivers.formats import FORMAT_PROFILE_MODULES
from tests.drivers.driver_format_cases import CASES, CASE_BY_ID


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
