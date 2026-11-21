"""Tests for BNetzA Breitbandmessung PDF parser."""

import itertools

import pytest
from unittest.mock import patch, MagicMock
from app.modules.bnetz.parser import parse_bnetz_pdf

# Ensure pypdf.PdfReader is importable for patching


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
_MOCK_PAGE2_DEVIATION = _MOCK_PAGE2.replace("wurde keine", "wurde eine")
# Overall result in the published wording, with abbreviations between "Abweichung" and "festgestellt"
_PUBLISHED = ('Ergebnis\nEs wurde {} "erhebliche, kontinuierliche oder regelmäßig wiederkehrende Abweichung der\n'
              'Geschwindigkeit" von Festnetz-Internetzugängen i.S.v. § 57 Abs. 4 Satz 1 Nr. 1 TKG entsprechend\n'
              'der Allgemeinverfügung 99/2021 der Bundesnetzagentur festgestellt.')
_DOWNLOAD = "Ergebnis der Messkampagne im Download\n{}"
# Text extraction variants of a heading line: (prefix, what follows the heading)
_HEADING_VARIANTS = {"plain": ("", "\n"), "indent": ("  ", "\n"), "nbsp": ("\u00a0", "\u00a0\n"),
                     "merged": ("", " "), "page-marker": ("", " Seite 3 von 10\n")}


# Sentences stating a deviation, with the directions it applies to; negations elsewhere must not mask it
_STATED_DEVIATIONS = [
    *((template.format(d=d, other=other), d) for d, other in (("Download", "Upload"), ("Upload", "Download"))
      for template in ("Eine Abweichung im {d} wurde festgestellt",
                       "Keine Unterbrechung, eine Abweichung im {d} wurde festgestellt",
                       "Im {other} wurde keine Abweichung festgestellt, im {d} wurde eine Abweichung festgestellt",
                       "Im {d} wurde keine Abweichung festgestellt, im {d} wurde eine Abweichung festgestellt",
                       "Es gab keine Verbindungsabbrüche (eine Abweichung im {d} wurde dennoch festgestellt)",
                       "Eine Abweichung wurde festgestellt und betrifft nur den {d}, im {other} wurde keine Abweichung "
                       "festgestellt",
                       "Es wurde eine Abweichung im {d} als\nErgebnis der Messkampagne festgestellt",
                       "Verbindungsabbrüche: keine\nErgebnis der Messkampagne im Einzelnen\n"
                       "Eine Abweichung im {d} wurde festgestellt")),
    ("Eine Abweichung im Download und im Upload wurde festgestellt", "Download Upload"),
]


def _vary(section, variant):
    prefix, after_heading = _HEADING_VARIANTS[variant]
    return prefix + section.replace("\n", after_heading, 1)


def _checklist_section(direction, deviation):
    """Per-direction result in the published layout: a criteria checklist precedes the verdict sentence."""
    criteria = "".join(
        f"Die {speed} Geschwindigkeit wird an der geforderten Zahl von Messtagen und in einem\n"
        f"ausreichenden Anteil der Messungen dieser Kampagne erreicht oder nicht unterschritten:\n"
        f"- Kriterium wurde {'nicht ' if deviation else ''}erreicht.\n"
        for speed in ("vertraglich vereinbarte maximale", "normalerweise zur Verfügung stehende",
                      "vertraglich vereinbarte minimale"))
    return (f"Ergebnis der Messkampagne im {direction}\n"
            "Die Messungen dieser Kampagne liefern zu den Kriterien für den Nachweis einer erheblichen,\n"
            "kontinuierlichen oder regelmäßig wiederkehrenden Abweichung der Geschwindigkeit die folgenden\n"
            "Ergebnisse. Für die Annahme einer solchen Abweichung genügt es, wenn ein Kriterium nicht\n"
            f"erreicht wurde.\n{criteria}"
            "Eine erhebliche, kontinuierliche oder regelmäßig wiederkehrende Abweichung der\n"
            f"Datenübertragungsrate im {direction} wurde {'' if deviation else 'nicht '}festgestellt.")


def _verdicts(pages):
    with patch("pypdf.PdfReader", return_value=_make_mock_reader([_MOCK_PAGE1, *pages])):
        result = parse_bnetz_pdf(b"fake pdf bytes")
    return result["verdict_download"], result["verdict_upload"]


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

    @pytest.mark.parametrize("pages, expected", [
        # Per-direction results take precedence over the overall statement
        ([_MOCK_PAGE2, _MOCK_PAGE3_DL.replace("im Download wurde nicht", "im Download wurde")], ("deviation", "ok")),
        ([_MOCK_PAGE2_DEVIATION, _MOCK_PAGE3_DL.replace("wurde nicht", "nicht")], ("ok", "ok")),
        ([_MOCK_PAGE2, _MOCK_PAGE3_DEVIATION], ("deviation", "deviation")),
        ([_PUBLISHED.format("eine"), _DOWNLOAD.format("Eine Abweichung im Download wurde nicht festgestellt.")],
         ("ok", "deviation")),
        # Only the overall statement
        ([_MOCK_PAGE2], ("ok", "ok")),
        ([_MOCK_PAGE2_DEVIATION], ("deviation", "deviation")),
        ([_PUBLISHED.format("keine")], ("ok", "ok")),
        ([_PUBLISHED.format("eine")], ("deviation", "deviation")),
        ([_vary(_PUBLISHED.format("eine"), "merged")], ("deviation", "deviation")),
        # Only "Ergebnis der Messkampagne im Download/Upload" or a bare "Ergebnis" line starts a section
        (["Ergebnis der Messkampagne im Einzelnen\nEs wurde eine Abweichung festgestellt."], ("unknown", "unknown")),
        ([_DOWNLOAD.format("Es wurde eine Abweichung im Download als\nErgebnis der Messkampagne festgestellt.")],
         ("deviation", "unknown")),
        ([_DOWNLOAD.format("Eine Abweichung im Download wurde nicht festgestellt.\nErgebnis der Messkampagne im "
                           "Einzelnen\nEine Abweichung wurde festgestellt.")], ("deviation", "unknown")),
        ([_DOWNLOAD.format("Verbindungsabbrüche: keine\nErgebnis der Messkampagne im Einzelnen\n"
                           "Eine Abweichung im Download wurde festgestellt.")], ("deviation", "unknown")),
        (["Ergebnis\nEs wurde keine Abweichung im Upload, aber eine Abweichung im Download festgestellt."],
         ("deviation", "ok")),
        (["Ergebnis\nEs wurde keine Abweichung im Upload und eine Abweichung im Download festgestellt."],
         ("deviation", "ok")),
        (["Ergebnis\nEs wurde weder im Download noch im Upload eine Abweichung festgestellt."],
         ("deviation", "deviation")),
        (["Ergebnis\nEs wurde keine Abweichung im Download und Upload festgestellt."], ("ok", "deviation")),
        (["Ergebnis\nEs wurde keine Abweichung im Upload, jedoch im Download festgestellt."], ("deviation", "ok")),
        (["Ergebnis\nIm Upload wurde keine Abweichung festgestellt, im Download wurde eine Abweichung festgestellt."],
         ("deviation", "ok")),
        (["Ergebnis\nEs gab keine Verbindungsabbrüche (eine Abweichung im Download wurde dennoch festgestellt)."],
         ("deviation", "unknown")),
        (["Ergebnis\nEine Abweichung wurde festgestellt und betrifft ausschließlich den Download, im Upload wurde "
          "keine Abweichung festgestellt."], ("deviation", "deviation")),
        (["Ergebnis\nEs wurde eine Abweichung nicht festgestellt."], ("ok", "ok")),
        (["Ergebnis\nEs wurde jedoch keine Abweichung festgestellt."], ("ok", "ok")),
        (["Ergebnis\nEine Abweichung konnte nicht festgestellt werden."], ("ok", "ok")),
        # A missing direction falls back to the overall statement
        ([_MOCK_PAGE2, _MOCK_PAGE3_DEVIATION.split("Ergebnis der Messkampagne im Upload")[0]], ("deviation", "ok")),
        # Per-direction wording, line breaks and hyphenation
        (["Ergebnis der Messkampagne\nim Download\nEine erhebliche Ab-\nweichung im Download wurde fest-\ngestellt."],
         ("deviation", "unknown")),
        ([_DOWNLOAD.format("Eine Abweichung im Download konnte nicht festgestellt werden.")], ("ok", "unknown")),
        ([_DOWNLOAD.format("Keine Abweichung im Download wurde festgestellt.")], ("ok", "unknown")),
        ([_DOWNLOAD.format("Eine Abweichung im Download wurde festgestellt und konnte nicht behoben werden.")],
         ("deviation", "unknown")),
        ([_DOWNLOAD.format("Keine Unterbrechung, eine Abweichung im Download wurde festgestellt.")],
         ("deviation", "unknown")),
        ([_DOWNLOAD.format("Eine Abweichung im Download wurde festgestellt (eine Ursache wurde nicht festgestellt).")],
         ("deviation", "unknown")),
        # Any deviation statement for a direction wins
        ([_MOCK_PAGE3_DL, _MOCK_PAGE3_DEVIATION], ("deviation", "deviation")),
        ([_DOWNLOAD.format("Eine Abweichung im Download wurde nicht festgestellt.\n"
                           + _DOWNLOAD.format("Eine Abweichung im Download wurde festgestellt."))],
         ("deviation", "unknown")),
        (["Ergebnis der Messkampagne im Upload\nEine Abweichung im Upload wurde nicht festgestellt.",
          "Ergebnis\nEine Abweichung im Download und im Upload wurde festgestellt."], ("deviation", "deviation")),
        # Prose mentioning "Ergebnis" mid-sentence is not a result heading
        (["Hinweis: Zum Ergebnis wurde bisher keine Abweichung festgestellt.", _PUBLISHED.format("eine")],
         ("deviation", "deviation")),
        (["Hinweis: Das Ergebnis, ob eine Abweichung vorliegt, wird erst später festgestellt.",
          _PUBLISHED.format("keine")], ("ok", "ok")),
        # No result statement at all
        ([_MOCK_PAGE4_DL, _MOCK_PAGE5_UL], ("unknown", "unknown")),
        # Published layout with criteria checklists, under each heading extraction variant
        *[([_PUBLISHED.format("eine"), _vary(_checklist_section("Download", False), variant) + "\n"
            + _checklist_section("Upload", True)], ("ok", "deviation")) for variant in _HEADING_VARIANTS],
    ], ids=["mixed-directions", "per-direction-short", "per-direction-deviation", "published-download-ok",
            "overall", "overall-deviation", "published-ok", "published-deviation", "published-merged-heading",
            "overall-other-heading", "wrapped-continuation", "subheading-in-section",
            "keine-before-subheading",
            "overall-mixed-directions", "overall-mixed-negation", "overall-ambiguous", "overall-elliptical",
            "overall-contrast-elliptical", "overall-comma-findings", "overall-parenthesis",
            "overall-directionless-deviation", "overall-negated-verb", "overall-adverb",
            "overall-konnte-nicht", "download-only", "heading-break-hyphenation", "download-konnte-nicht",
            "download-keine", "download-unrelated-negation", "download-unrelated-keine", "download-negated-parenthesis",
            "deviation-wins-across-pages", "deviation-wins-on-page", "shared-finding-after-ok",
            "prose-note-then-deviation", "prose-note-then-ok", "no-verdict",
            *(f"published-checklist-{variant}" for variant in _HEADING_VARIANTS)])
    def test_verdict(self, pages, expected):
        assert _verdicts(pages) == expected

    @pytest.mark.parametrize("statement, suffix, variant", list(itertools.product(
        _STATED_DEVIATIONS,
        ["", " und konnte nicht behoben werden", "; eine Ursache wurde nicht genannt",
         " (eine Ursache wurde nicht festgestellt)"],
        _HEADING_VARIANTS)))
    def test_stated_deviation_is_never_ok(self, statement, suffix, variant):
        sentence, deviating = statement
        verdicts = _verdicts([_vary(_DOWNLOAD.format(f"{sentence}{suffix}."), variant)])

        for direction, verdict in zip(("Download", "Upload"), verdicts):
            if direction in deviating:
                assert verdict == "deviation"

    def test_direction_without_measurements_has_no_average(self, caplog):
        pages = [_MOCK_PAGE1, _MOCK_PAGE2, _MOCK_PAGE3_DL, _MOCK_PAGE4_DL]
        with patch("pypdf.PdfReader", return_value=_make_mock_reader(pages)), caplog.at_level("INFO"):
            result = parse_bnetz_pdf(b"fake pdf bytes")

        assert result["measurements_upload"] == []
        assert result["upload_measured_avg"] is None
        assert "UL avg=n/a" in caplog.text

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
