"""Shared DOCSIS modulation utility contracts."""

import pytest

from app.docsis_utils import (
    canonical_modulation_label,
    modulation_threshold_key,
    parse_qam_order,
    qam_rank,
    stored_or_classified_family,
    to_float,
)


@pytest.mark.parametrize(
    ("value", "order"),
    [
        ("QPSK", 4),
        ("qpsk", 4),
        ("4QAM", 4),
        ("8QAM", 8),
        ("16 QAM", 16),
        ("64-QAM", 64),
        ("64qam", 64),
        ("256QAM", 256),
        ("qam_256", 256),
        ("QAM1024", 1024),
        ("1024QAM", 1024),
    ],
)
def test_parse_qam_order_supported_driver_formats(value, order):
    assert parse_qam_order(value) == order


@pytest.mark.parametrize("value", [None, "", "OFDM", "OFDMA", "SC-QAM", "unknown", "profile 256QAM"])
def test_parse_qam_order_unparseable_values(value):
    assert parse_qam_order(value) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("QPSK", ("4QAM", 4)),
        ("256-QAM", ("256QAM", 256)),
        ("qam_256", ("256QAM", 256)),
        ("OFDM", ("OFDM", None)),
        ("OFDMA", ("OFDMA", None)),
        ("", ("Unknown", None)),
    ],
)
def test_canonical_modulation_label(value, expected):
    assert canonical_modulation_label(value) == expected


@pytest.mark.parametrize(
    ("value", "rank"),
    [
        ("QPSK", 1),
        ("4QAM", 1),
        ("16QAM", 3),
        ("64-QAM", 5),
        ("qam_256", 7),
        ("4096QAM", 11),
        ("OFDMA", 0),
    ],
)
def test_qam_rank_uses_shared_parser(value, rank):
    assert qam_rank(value) == rank


def test_classify_channel_family_keeps_degraded_ofdm_profiles_on_ofdm_family():
    from app.docsis_utils import classify_channel_family, channel_type_label

    channel = {
        "docsis_version": "3.1",
        "profile_modulation": "256QAM",
        "modulation": "",
    }

    assert classify_channel_family("ds", channel) == "ofdm"
    assert channel_type_label("ds", channel) == "OFDM"


def test_classify_channel_family_distinguishes_us31_sc_qam_from_ofdma():
    from app.docsis_utils import classify_channel_family, sc_qam_capacity_family

    sc_qam = {"docsis_version": "3.1", "multiplex": "ATDMA", "modulation": "64QAM"}
    ofdma = {"docsis_version": "3.1", "type": "OFDMA", "profile_modulation": "64QAM"}

    assert classify_channel_family("us", sc_qam) == "sc_qam"
    assert sc_qam_capacity_family("us", sc_qam) == "sc_qam"
    assert classify_channel_family("us", ofdma) == "ofdma"
    assert sc_qam_capacity_family("us", ofdma) == "unsupported"


@pytest.mark.parametrize(
    ("modulation", "section", "key"),
    [
        ("OFDM", {"256QAM": {}, "4096QAM": {}, "_default": "256QAM"}, "4096QAM"),
        ("OFDMA", {"256QAM": {}, "4096QAM": {}, "_default": "256QAM"}, "4096QAM"),
        ("4096QAM", {"256QAM": {}, "4096QAM": {}, "_default": "256QAM"}, "4096QAM"),
        ("UNKNOWN", {"256QAM": {}, "_default": "256QAM"}, "256QAM"),
    ],
)
def test_modulation_threshold_key(modulation, section, key):
    assert modulation_threshold_key(modulation, section) == key


@pytest.mark.parametrize(("value", "number"), [("3.5", 3.5), ("-7.2", -7.2), (None, None), ("", None), ("bad", None)])
def test_to_float(value, number):
    assert to_float(value) == number


@pytest.mark.parametrize(("direction", "family"), [("ds", "sc_qam"), ("ds", "ofdm"), ("us", "sc_qam"), ("us", "ofdma")])
@pytest.mark.parametrize("legacy_fields", [
    {"type": "OFDM", "modulation": "4096QAM", "docsis_version": "3.1"},
    {"type": "SC-QAM", "modulation": "256QAM", "docsis_version": "3.0"},
    {"profile_modulation": "256QAM", "docsis_version": "3.1"},
])
def test_stored_family_is_authoritative_when_valid_for_the_direction(direction, family, legacy_fields):
    assert stored_or_classified_family(direction, {**legacy_fields, "channel_family": family}) == family


@pytest.mark.parametrize(
    ("direction", "channel", "family"),
    [
        ("ds", {"modulation": "256QAM", "docsis_version": "3.1"}, "sc_qam"),
        ("ds", {"type": "256QAM", "docsis_version": "3.1"}, "ofdm"),
        ("ds", {"type": "SC-QAM", "docsis_version": "3.1"}, "sc_qam"),
        ("ds", {"modulation": "1024QAM", "docsis_version": "3.1"}, "ofdm"),
        ("ds", {"modulation": "4096QAM", "docsis_version": "3.1"}, "ofdm"),
        ("ds", {"type": "OFDM", "modulation": "1024QAM", "docsis_version": "3.1"}, "ofdm"),
        ("ds", {"type": "OFDM", "modulation": "4096QAM", "docsis_version": "3.1"}, "ofdm"),
        ("ds", {"profile_modulation": "256QAM", "docsis_version": "3.1"}, "ofdm"),
        ("ds", {"channel_type": "OFDM", "modulation": "256QAM"}, "ofdm"),
        ("ds", {}, "unknown"),
        ("us", {"profile_modulation": "64QAM", "docsis_version": "3.1"}, "ofdma"),
        ("us", {"modulation": "64QAM", "docsis_version": "3.0"}, "sc_qam"),
    ],
)
@pytest.mark.parametrize("metadata", ["missing", None, "unknown", "invalid", "OFDM", [], {}])
def test_stored_family_falls_back_to_classification(direction, channel, family, metadata):
    stored = channel if metadata == "missing" else {**channel, "channel_family": metadata}
    assert stored_or_classified_family(direction, stored) == family


@pytest.mark.parametrize(("direction", "other_direction_family"), [("ds", "ofdma"), ("us", "ofdm")])
def test_stored_family_of_the_other_direction_is_reclassified(direction, other_direction_family):
    channel = {"modulation": "64QAM", "docsis_version": "3.0", "channel_family": other_direction_family}
    assert stored_or_classified_family(direction, channel) == "sc_qam"
