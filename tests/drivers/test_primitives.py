"""Shared value primitives used by the modem format profiles."""

import pytest

from app.drivers.formats.contract import number_reader
from app.drivers.formats.primitives import (
    hz_to_mhz,
    normalize_mhz,
    normalize_modulation,
    parse_first_number,
    parse_mhz_value,
    parse_number,
)


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
        ("0", 0.0),
        ("-0.0 dBmV", 0.0),
        # Empty, unreadable and non-finite cells are unavailable, never a 0 reading.
        *[(raw, None) for raw in (None, "", "   ", "Locked", "inf", "-Infinity dBmV", "nan dB", "1e400")],
    ],
)
def test_parse_number(raw, expected):
    assert parse_number(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("1,234.5 dB", 1234.5), ("-3.2 dBmV", -3.2), ("Ch 5", 5.0), ("", None), ("----", None)],
)
def test_parse_first_number(raw, expected):
    assert parse_first_number(raw) == expected


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
        (591500000.0, "591.5 MHz"),
        ("591000 kHz", "591 MHz"),
        ("1200 MHz", "1200 MHz"),
        ("5120", "5.1 MHz"),
        ("42", "42 MHz"),
        ("0", "0 MHz"),
        ("0 Hz", "0 MHz"),
        (0, "0 MHz"),
        ("", ""),
        ("invalid", "invalid"),
        ("not a number", "not a number"),
        *[(raw, str(raw)) for raw in ("inf", "nan Hz", "1e400", float("inf"), float("nan"))],
    ],
)
def test_hz_to_mhz(raw, expected):
    assert hz_to_mhz(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("591000000 Hz", 591.0),
        ("591000 kHz", 591.0),
        ("807.5 MHz", 807.5),
        ("591000000", 591.0),
        ("5120", 5.12),
        ("42", 42.0),
        ("", 0.0),
        ("n/a", 0.0),
        ("inf", 0.0),
        ("nan MHz", 0.0),
    ],
)
def test_parse_mhz_value(raw, expected):
    assert parse_mhz_value(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("807.00 MHz", "807 MHz"),
        ("17.60 MHz", "17.6 MHz"),
        ("100 MHz", "100 MHz"),
        ("unknown", "unknown"),
        ("", ""),
        ("inf MHz", "inf MHz"),
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


@pytest.mark.parametrize(("value", "kind", "expected", "code"), [
    ("9007199254740993", int, 9007199254740993, None),
    (str(2**63 - 1), int, 2**63 - 1, None),
    ("0", int, 0, None),
    ("-0.5 dBmV", float, -0.5, None),
    ("38.98 dB", float, 38.98, None),
    (7, float, 7, None),
    (10.0, int, 10.0, None),
    *[(value, int, None, "invalid_field") for value in (
        "0.5", "1e3", "inf", "n/a", "-1", "12 codewords", "0 garbage", str(2**63), "9" * 401 + " garbage", 10**400, 0.5, -1,
    )],
    *[(value, float, None, "invalid_field") for value in ("0 garbage", "1.5 dBmV extra", 10**400, float("nan"), True)],
    *[(value, kind, None, "unavailable_field") for value, kind in ((None, float), ("", int), ("  ", float))],
])
def test_number_reader_keeps_exact_values_and_reports_the_rest(value, kind, expected, code):
    diagnostics = []
    assert repr(number_reader(diagnostics, "profile", family="family")(value, "field", kind)) == repr(expected)
    assert [issue.code for issue in diagnostics] == ([code] if code else [])
