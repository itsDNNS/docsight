"""Tests for the CGM4981 driver helpers and channel parsing."""

import pytest

from app.drivers.cgm4981 import _float, _modulation


class TestFloat:
    """_float() should return None for blank/unparseable input."""

    def test_normal_value(self):
        assert _float("44.1 dB") == 44.1

    def test_negative(self):
        assert _float("-6.2 dBmV") == -6.2

    def test_integer(self):
        assert _float("256") == 256.0

    def test_blank(self):
        assert _float("") is None

    def test_no_number(self):
        assert _float("N/A") is None

    def test_whitespace(self):
        assert _float("   ") is None

    def test_zero_is_real(self):
        assert _float("0.0 dBmV") == 0.0


class TestModulation:
    """_modulation() must return the project-standard format."""

    def test_256qam(self):
        assert _modulation("256 QAM") == "256QAM"

    def test_64qam(self):
        assert _modulation("64QAM") == "64QAM"

    def test_ofdm(self):
        assert _modulation("OFDM") == "OFDM"

    def test_ofdma(self):
        assert _modulation("OFDMA") == "OFDMA"

    def test_qam_bare(self):
        assert _modulation("QAM") == "QAM"

    def test_case_insensitive(self):
        assert _modulation("256 qam") == "256QAM"

    def test_empty(self):
        assert _modulation("") == ""
