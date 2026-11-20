"""Shared value primitives used by the modem format profiles."""

import pytest

from app.drivers.formats.primitives import hz_to_mhz, normalize_mhz, normalize_modulation, parse_number


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("43.3 dBmV", 43.3),
        ("-0.32 dBmV", -0.32),
        ("41.8 dB", 41.8),
        ("4.70 dBmV", 4.70),
        ("38.98", 38.98),
        ("92", 92.0),
        ("35 dB", 35.0),
        ("3 dBmV", 3.0),
        ("5.120 Msym/sec", 5.12),
        ("10.50 dBmV", 10.50),
        ("40.95 dB", 40.95),
        ("33", 33.0),
        ("", 0.0),
        ("Locked", 0.0),
    ],
)
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("495000000 Hz", "495 MHz"),
        ("22800000 Hz", "22.8 MHz"),
        ("706500000 Hz", "706.5 MHz"),
        ("465000000 Hz", "465 MHz"),
        ("24600000 Hz", "24.6 MHz"),
        ("591000000", "591 MHz"),
        ("275600000", "275.6 MHz"),
        (" 275600000", "275.6 MHz"),
        ("  795000000 Hz  ", "795 MHz"),
        (705000000, "705 MHz"),
        (29200000, "29.2 MHz"),
        (36200000, "36.2 MHz"),
        ("0", "0 MHz"),
        ("0 Hz", "0 MHz"),
        (0, "0 MHz"),
        ("", ""),
        ("invalid", "invalid"),
        ("not a number", "not a number"),
    ],
)
def test_hz_to_mhz(raw, expected):
    assert hz_to_mhz(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("807.00 MHz", "807 MHz"),
        ("17.60 MHz", "17.6 MHz"),
        ("100 MHz", "100 MHz"),
        ("unknown", "unknown"),
    ],
)
def test_normalize_mhz(raw, expected):
    assert normalize_mhz(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ""),
        ("", ""),
        (" 256QAM ", "256QAM"),
        ("256qam", "256QAM"),
        ("256-qam", "256QAM"),
        ("256 qam", "256QAM"),
        ("qam256", "256QAM"),
        ("qam_256", "256QAM"),
        ("64 qam", "64QAM"),
        ("4096-qam", "4096QAM"),
        ("qpsk", "QPSK"),
        ("ofdm", "OFDM"),
        ("ofdma", "OFDMA"),
        ("atdma", "ATDMA"),
        ("tdma", "TDMA"),
        ("mystery mode", "MYSTERY MODE"),
    ],
)
def test_normalize_modulation(raw, expected):
    assert normalize_modulation(raw) == expected
