"""Tests for BNetzA Breitbandmessung PDF parser."""

import pytest
from unittest.mock import patch, MagicMock
from app.modules.bnetz.parser import parse_bnetz_pdf

# Ensure pypdf.PdfReader is importable for patching
import pypdf


# Mock PDF text simulating real BNetzA Messprotokoll structure
_MOCK_PAGE1 = """Messprotokoll der Breitbandmessung vom 15.03.2026
Angaben zum Internetzugangsdienst
Anbieter: Telekom
Tarifname: MagentaZuhause 250
Datenübertragungsrate (DÜR) im Download Datenübertragungsrate (DÜR) im Upload
Maximal: 250,00 Mbit/s Maximal: 40,00 Mbit/s
Normalerweise: 200,00 Mbit/s Normalerweise: 30,00 Mbit/s
Minimal: 150,00 Mbit/s Minimal: 10,00 Mbit/s
Seite 1 von 10"""

_MOCK_PAGE2 = """Details der Messkampagne
Start Messkampagne: 10.03.2026 - 14:00 Uhr
Ende Messkampagne: 15.03.2026 - 20:00 Uhr
Anzahl Messungen: 5
Ergebnis
Es wurde keine erhebliche, kontinuierliche oder regelmäßig wiederkehrende Abweichung der
Geschwindigkeit festgestellt.
Seite 2 von 10"""

_MOCK_PAGE3_DL = """Ergebnis der Messkampagne im Download
Eine erhebliche Abweichung der Datenübertragungsrate im Download wurde nicht festgestellt.
Ergebnis der Messkampagne im Upload
Eine erhebliche Abweichung der Datenübertragungsrate im Upload wurde nicht festgestellt.
Seite 3 von 10"""

_MOCK_PAGE4_DL = """Überblick der Messungen im Download
Nr. Datum Uhrzeit gemessene DÜR
1 10.03.2026 14:00 235,50 Mbit/s
2 11.03.2026 15:00 242,10 Mbit/s
3 12.03.2026 16:00 238,80 Mbit/s
4 13.03.2026 17:00 245,00 Mbit/s
5 15.03.2026 20:00 240,30 Mbit/s
Seite 4 von 10"""

_MOCK_PAGE5_UL = """Überblick der Messungen im Upload
Nr. Datum Uhrzeit gemessene DÜR
1 10.03.2026 14:00 38,50 Mbit/s
2 11.03.2026 15:00 39,10 Mbit/s
3 12.03.2026 16:00 37,80 Mbit/s
4 13.03.2026 17:00 40,00 Mbit/s
5 15.03.2026 20:00 38,30 Mbit/s
Seite 5 von 10"""

# Deviation variant
_MOCK_PAGE3_DEVIATION = """Ergebnis der Messkampagne im Download
Eine erhebliche Abweichung der Datenübertragungsrate im Download wurde festgestellt.
Ergebnis der Messkampagne im Upload
Eine erhebliche Abweichung der Datenübertragungsrate im Upload wurde festgestellt.
Seite 3 von 10"""


def _make_mock_reader(page_texts):
    """Create a mock PdfReader that returns given page texts."""
    mock_reader = MagicMock()
    mock_pages = []
    for text in page_texts:
        page = MagicMock()
        page.extract_text.return_value = text
        mock_pages.append(page)
    mock_reader.pages = mock_pages
    return mock_reader


class TestBnetzParser:
    def test_valid_pdf_no_deviation(self):
        pages = [_MOCK_PAGE1, _MOCK_PAGE2, _MOCK_PAGE3_DL, _MOCK_PAGE4_DL, _MOCK_PAGE5_UL]
        with patch("pypdf.PdfReader", return_value=_make_mock_reader(pages)):
            result = parse_bnetz_pdf(b"fake pdf bytes")

        assert result["date"] == "2026-03-15"
        assert result["provider"] == "Telekom"
        assert result["tariff"] == "MagentaZuhause 250"
        assert result["download_max"] == 250.0
        assert result["upload_max"] == 40.0
        assert result["download_normal"] == 200.0
        assert result["upload_normal"] == 30.0
        assert result["download_min"] == 150.0
        assert result["upload_min"] == 10.0
        assert result["measurement_count"] == 5
        assert len(result["measurements_download"]) == 5
        assert len(result["measurements_upload"]) == 5
        assert result["measurements_download"][0]["mbps"] == 235.5
        assert result["download_measured_avg"] == pytest.approx(240.34, abs=0.01)
        assert result["upload_measured_avg"] == pytest.approx(38.74, abs=0.01)
        assert result["verdict_download"] == "ok"
        assert result["verdict_upload"] == "ok"
        assert result["campaign_start"] == "2026-03-10"
        assert result["campaign_end"] == "2026-03-15"

    def test_valid_pdf_with_deviation(self):
        pages = [_MOCK_PAGE1, _MOCK_PAGE2, _MOCK_PAGE3_DEVIATION, _MOCK_PAGE4_DL, _MOCK_PAGE5_UL]
        with patch("pypdf.PdfReader", return_value=_make_mock_reader(pages)):
            result = parse_bnetz_pdf(b"fake pdf bytes")

        assert result["verdict_download"] == "deviation"
        assert result["verdict_upload"] == "deviation"

    def test_invalid_pdf_not_bnetz(self):
        mock_reader = _make_mock_reader(["This is just a random PDF document."])
        with patch("pypdf.PdfReader", return_value=mock_reader):
            with pytest.raises(ValueError, match="Not a BNetzA"):
                parse_bnetz_pdf(b"fake pdf bytes")

    def test_invalid_pdf_no_date(self):
        mock_reader = _make_mock_reader(["Messprotokoll der Breitbandmessung vom"])
        with patch("pypdf.PdfReader", return_value=mock_reader):
            with pytest.raises(ValueError, match="Cannot find measurement date"):
                parse_bnetz_pdf(b"fake pdf bytes")

    def test_corrupt_pdf(self):
        with patch("pypdf.PdfReader", side_effect=Exception("corrupt")):
            with pytest.raises(ValueError, match="Cannot read PDF"):
                parse_bnetz_pdf(b"not a pdf")

    def test_real_pdf_if_available(self):
        """Integration test with real BNetzA PDF (skipped if not available)."""
        import os
        pdf_path = "/tmp/bnetz_example.pdf"
        if not os.path.exists(pdf_path):
            pytest.skip("Real BNetzA PDF not available at /tmp/bnetz_example.pdf")

        with open(pdf_path, "rb") as f:
            result = parse_bnetz_pdf(f.read())

        assert result["date"] == "2025-02-04"
        assert result["provider"] == "Vodafone"
        assert result["tariff"] == "GigaZuhause 1000 Kabel Nov 2023"
        assert result["download_max"] == 1000.0
        assert result["upload_max"] == 50.0
        assert result["measurement_count"] == 30
        assert len(result["measurements_download"]) == 30
        assert len(result["measurements_upload"]) == 30
        assert result["verdict_download"] == "deviation"
        assert result["verdict_upload"] == "deviation"
