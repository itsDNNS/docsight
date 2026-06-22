"""Shared DOCSIS modulation utility contracts."""

import pytest

from app.docsis_utils import canonical_modulation_label, parse_qam_order, qam_rank


@pytest.mark.parametrize(
    ("value", "order"),
    [
        ("QPSK", 4),
        ("qpsk", 4),
        ("4QAM", 4),
        ("8QAM", 8),
        ("16 QAM", 16),
        ("64-QAM", 64),
        ("256QAM", 256),
        ("qam_256", 256),
        ("QAM1024", 1024),
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
