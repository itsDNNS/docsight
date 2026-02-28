"""Tests for BNetzA CSV parser."""

import pytest
from app.modules.bnetz.csv_parser import parse_bnetz_csv, _parse_de_float, _convert_date


class TestHelpers:
    def test_parse_de_float(self):
        assert _parse_de_float("883,29") == 883.29
        assert _parse_de_float("1.000,00") == 1000.0
        assert _parse_de_float("50,00") == 50.0
        assert _parse_de_float("15,40") == 15.4

    def test_parse_de_float_invalid(self):
        assert _parse_de_float("abc") is None

    def test_convert_date_german(self):
        assert _convert_date("04.02.2025") == "2025-02-04"
        assert _convert_date("29.01.2025") == "2025-01-29"

    def test_convert_date_iso(self):
        assert _convert_date("2025-02-04") == "2025-02-04"


class TestCsvParser:
    def test_valid_csv_semicolon(self):
        csv = (
            "Datum;Uhrzeit;Download (Mbit/s);Upload (Mbit/s)\n"
            "15.03.2026;14:00;235,50;38,50\n"
            "16.03.2026;15:00;242,10;39,10\n"
            "17.03.2026;16:00;238,80;37,80\n"
        )
        result = parse_bnetz_csv(csv)
        assert result["measurement_count"] == 3
        assert len(result["measurements_download"]) == 3
        assert len(result["measurements_upload"]) == 3
        assert result["measurements_download"][0]["mbps"] == 235.5
        assert result["measurements_upload"][0]["mbps"] == 38.5
        assert result["download_measured_avg"] == pytest.approx(238.8, abs=0.01)
        assert result["upload_measured_avg"] == pytest.approx(38.47, abs=0.01)
        assert result["date"] == "2026-03-17"  # latest date
        assert result["provider"] == "CSV Import"
        assert result["verdict_download"] == "unknown"
        assert result["verdict_upload"] == "unknown"

    def test_valid_csv_comma_delimiter(self):
        csv = (
            "Datum,Uhrzeit,Download,Upload\n"
            "2026-03-15,14:00,235.5,38.5\n"
            "2026-03-16,15:00,242.1,39.1\n"
        )
        result = parse_bnetz_csv(csv)
        assert result["measurement_count"] == 2
        assert result["measurements_download"][0]["mbps"] == 235.5

    def test_download_only(self):
        csv = (
            "Datum;Uhrzeit;Download (Mbit/s)\n"
            "15.03.2026;14:00;235,50\n"
            "16.03.2026;15:00;242,10\n"
        )
        result = parse_bnetz_csv(csv)
        assert len(result["measurements_download"]) == 2
        assert len(result["measurements_upload"]) == 0
        assert result["upload_measured_avg"] is None

    def test_german_locale_numbers(self):
        csv = (
            "Datum;Uhrzeit;Download (Mbit/s);Upload (Mbit/s)\n"
            "15.03.2026;14:00;1.000,50;50,25\n"
        )
        result = parse_bnetz_csv(csv)
        assert result["measurements_download"][0]["mbps"] == 1000.5
        assert result["measurements_upload"][0]["mbps"] == 50.25

    def test_empty_csv(self):
        with pytest.raises(ValueError, match="Empty CSV content"):
            parse_bnetz_csv("")

    def test_empty_csv_whitespace(self):
        with pytest.raises(ValueError, match="Empty CSV content"):
            parse_bnetz_csv("   ")

    def test_header_only(self):
        csv = "Datum;Uhrzeit;Download (Mbit/s);Upload (Mbit/s)\n"
        with pytest.raises(ValueError, match="No valid measurement rows"):
            parse_bnetz_csv(csv)

    def test_no_speed_columns(self):
        csv = "Name;Datum;Uhrzeit\nTest;15.03.2026;14:00\n"
        with pytest.raises(ValueError, match="must contain at least"):
            parse_bnetz_csv(csv)

    def test_malformed_rows_skipped(self):
        csv = (
            "Datum;Uhrzeit;Download (Mbit/s);Upload (Mbit/s)\n"
            "15.03.2026;14:00;235,50;38,50\n"
            ";;abc;xyz\n"  # invalid speeds -> skipped
            "16.03.2026;15:00;242,10;39,10\n"
        )
        result = parse_bnetz_csv(csv)
        assert result["measurement_count"] == 2

    def test_empty_rows_skipped(self):
        csv = (
            "Datum;Uhrzeit;Download (Mbit/s);Upload (Mbit/s)\n"
            "15.03.2026;14:00;235,50;38,50\n"
            ";;;\n"
            "\n"
            "16.03.2026;15:00;242,10;39,10\n"
        )
        result = parse_bnetz_csv(csv)
        assert result["measurement_count"] == 2

    def test_tariff_fields_null_for_csv(self):
        csv = (
            "Datum;Uhrzeit;Download (Mbit/s);Upload (Mbit/s)\n"
            "15.03.2026;14:00;235,50;38,50\n"
        )
        result = parse_bnetz_csv(csv)
        assert result["tariff"] is None
        assert result["download_max"] is None
        assert result["upload_max"] is None
