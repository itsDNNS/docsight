"""Tests for import parser (Excel/CSV -> Incident Journal)."""

import pytest
from datetime import datetime

from app.import_parser import (
    _extract_year_context,
    _normalize_date,
    _parse_csv,
    _detect_mapping,
    _col_letter,
    _is_date_like,
    _find_header_row,
    parse_file,
    MONTH_HEADER_RE,
)


# ── Helper ──

def _make_csv_bytes(text, encoding="utf-8"):
    """Encode CSV text to bytes for parser input."""
    return text.encode(encoding)


# ── Year Rollover Detection (_extract_year_context) ──

class TestExtractYearContext:
    def test_explicit_year_in_month_header(self):
        """Month header with explicit year: 'November (2023)' -> year=2023."""
        rows = [
            ["November (2023)", "", "", ""],
            ["", "03.11.", "Outage", "Details"],
            ["", "10.11.", "Repair", "Fixed"],
        ]
        year_map = _extract_year_context(rows)
        assert year_map[1] == 2023
        assert year_map[2] == 2023

    def test_year_rollover_dec_to_jan(self):
        """Dec -> Jan without explicit year should increment year."""
        rows = [
            ["November (2023)", "", "", ""],
            ["", "03.11.", "Event A", ""],
            ["Dezember", "", "", ""],
            ["", "15.12.", "Event B", ""],
            ["Januar", "", "", ""],
            ["", "05.01.", "Event C", ""],
        ]
        year_map = _extract_year_context(rows)
        # Nov 2023 data
        assert year_map[1] == 2023
        # Dec 2023 data
        assert year_map[3] == 2023
        # Jan -> rollover to 2024
        assert year_map[5] == 2024

    def test_no_rollover_within_same_year(self):
        """Months ascending within the same year should keep the year."""
        rows = [
            ["März (2024)", "", "", ""],
            ["", "10.03.", "Event A", ""],
            ["April", "", "", ""],
            ["", "05.04.", "Event B", ""],
            ["Mai", "", "", ""],
            ["", "20.05.", "Event C", ""],
        ]
        year_map = _extract_year_context(rows)
        assert year_map[1] == 2024
        assert year_map[3] == 2024
        assert year_map[5] == 2024

    def test_multiple_rollovers(self):
        """2023 -> 2024 -> 2025 across multiple year boundaries."""
        rows = [
            ["November (2023)", "", "", ""],
            ["", "01.11.", "A", ""],
            ["Dezember", "", "", ""],
            ["", "01.12.", "B", ""],
            ["Januar", "", "", ""],       # rollover -> 2024
            ["", "01.01.", "C", ""],
            ["November", "", "", ""],
            ["", "01.11.", "D", ""],
            ["Dezember", "", "", ""],
            ["", "01.12.", "E", ""],
            ["Januar", "", "", ""],       # rollover -> 2025
            ["", "01.01.", "F", ""],
        ]
        year_map = _extract_year_context(rows)
        assert year_map[1] == 2023   # Nov 2023
        assert year_map[3] == 2023   # Dec 2023
        assert year_map[5] == 2024   # Jan 2024
        assert year_map[7] == 2024   # Nov 2024
        assert year_map[9] == 2024   # Dec 2024
        assert year_map[11] == 2025  # Jan 2025

    def test_month_header_row_also_in_year_map(self):
        """Month-header rows should also be in year_map (they may contain data)."""
        rows = [
            ["November (2023)", "", "", ""],
            ["", "03.11.", "Event", ""],
        ]
        year_map = _extract_year_context(rows)
        assert year_map[0] == 2023
        assert year_map[1] == 2023

    def test_no_month_headers_returns_empty(self):
        """Rows without any month headers should return empty year map."""
        rows = [
            ["Datum", "Titel", "Beschreibung"],
            ["15.01.2024", "Event A", "Details"],
        ]
        year_map = _extract_year_context(rows)
        assert year_map == {}

    def test_first_header_no_year_infers_from_nearby_dates(self):
        """First month header without year should infer from nearby date data."""
        rows = [
            ["März", "", "", ""],
            ["", "10.03.2024", "Event A", ""],
            ["", "15.03.2024", "Event B", ""],
        ]
        year_map = _extract_year_context(rows)
        # Should infer 2024 from the DD.MM.YYYY date in the next rows
        assert year_map[1] == 2024
        assert year_map[2] == 2024


# ── Month-Header Rows with Data ──

class TestMonthHeaderRowsWithData:
    def test_month_header_with_data_not_skipped(self):
        """Row where col 0 is a month header but other cols have data should be parsed."""
        csv_text = (
            "Monat;Datum;Ereignis;Details\n"
            "November (2023);03.11.;Server down;Production outage\n"
            ";10.11.;Recovery;Back online\n"
        )
        result = parse_file(_make_csv_bytes(csv_text), "test.csv")
        # Both data rows should be present
        assert result["total"] == 2
        titles = [r["title"] for r in result["rows"]]
        assert "Server down" in titles
        assert "Recovery" in titles

    def test_month_header_without_data_skipped(self):
        """Row where col 0 is a month header and other cols are empty SHOULD be skipped."""
        csv_text = (
            "Monat;Datum;Ereignis;Details\n"
            "November (2023);;;\n"
            ";03.11.2023;Server down;Production outage\n"
            ";10.11.2023;Recovery;Back online\n"
        )
        result = parse_file(_make_csv_bytes(csv_text), "test.csv")
        # The month-header-only row should be skipped
        assert result["total"] == 2
        titles = [r["title"] for r in result["rows"]]
        assert "Server down" in titles
        assert "Recovery" in titles

    def test_month_header_regex_matches_expected_formats(self):
        """Verify MONTH_HEADER_RE matches various valid month header formats."""
        assert MONTH_HEADER_RE.match("November (2023)")
        assert MONTH_HEADER_RE.match("November(2023)")
        assert MONTH_HEADER_RE.match("November")
        assert MONTH_HEADER_RE.match("Dezember")
        assert MONTH_HEADER_RE.match("März")
        assert MONTH_HEADER_RE.match("Maerz")
        assert MONTH_HEADER_RE.match("januar")
        assert MONTH_HEADER_RE.match("FEBRUAR")
        # Should not match
        assert not MONTH_HEADER_RE.match("November 2023 extra text")
        assert not MONTH_HEADER_RE.match("Not a month")
        assert not MONTH_HEADER_RE.match("03.11.2023")


# ── Date Normalization (_normalize_date) ──

class TestNormalizeDate:
    def test_iso_format_passthrough(self):
        """ISO format 'YYYY-MM-DD' should pass through unchanged."""
        assert _normalize_date("2024-01-15", None) == "2024-01-15"

    def test_iso_format_valid_date(self):
        """Valid ISO date should work."""
        assert _normalize_date("2024-12-31", None) == "2024-12-31"

    def test_iso_format_invalid_date(self):
        """Invalid ISO date should return None."""
        assert _normalize_date("2024-02-30", None) is None

    def test_german_dd_mm_yyyy(self):
        """German DD.MM.YYYY format should convert to ISO."""
        assert _normalize_date("15.01.2024", None) == "2024-01-15"

    def test_german_dd_mm_yyyy_single_digits(self):
        """Single digit day/month in DD.MM.YYYY."""
        assert _normalize_date("5.1.2024", None) == "2024-01-05"

    def test_german_dd_mm_with_context_year(self):
        """DD.MM. format with context year should use that year."""
        assert _normalize_date("15.01. ", 2024) == "2024-01-15"

    def test_german_dd_mm_without_context_year(self):
        """DD.MM. format without context year should use current year."""
        result = _normalize_date("15.01. ", None)
        current_year = datetime.now().year
        assert result == f"{current_year}-01-15"

    def test_date_range_takes_start_date(self):
        """Date range 'DD.MM. - DD.MM.' should take the start date."""
        assert _normalize_date("15.01. - 17.01.", 2024) == "2024-01-15"

    def test_date_range_with_em_dash(self):
        """Date range with em-dash separator."""
        assert _normalize_date("15.01.\u2014 17.01.", 2024) == "2024-01-15"

    def test_date_range_with_en_dash(self):
        """Date range with en-dash separator."""
        assert _normalize_date("15.01.\u2013 17.01.", 2024) == "2024-01-15"

    def test_invalid_date_returns_none(self):
        """Completely invalid date string should return None."""
        assert _normalize_date("99.99.9999", None) is None

    def test_empty_string_returns_none(self):
        """Empty string should return None."""
        assert _normalize_date("", None) is None

    def test_none_returns_none(self):
        """None input should return None."""
        assert _normalize_date(None, None) is None

    def test_whitespace_only_returns_none(self):
        """Whitespace-only string should return None."""
        assert _normalize_date("   ", None) is None

    def test_non_date_text_returns_none(self):
        """Random text should return None."""
        assert _normalize_date("hello world", None) is None

    def test_german_dd_mm_yyyy_invalid_day(self):
        """Invalid day in DD.MM.YYYY should return None."""
        assert _normalize_date("32.01.2024", None) is None

    def test_german_dd_mm_yyyy_invalid_month(self):
        """Invalid month in DD.MM.YYYY should return None."""
        assert _normalize_date("15.13.2024", None) is None


# ── CSV Parsing (_parse_csv) ──

class TestParseCsv:
    def test_semicolon_delimited(self):
        """Semicolon-delimited CSV should be parsed correctly."""
        csv_text = "Datum;Titel;Beschreibung\n15.01.2024;Event A;Details A\n20.01.2024;Event B;Details B\n"
        rows, header_idx = _parse_csv(_make_csv_bytes(csv_text))
        assert len(rows) == 3
        assert rows[0] == ["Datum", "Titel", "Beschreibung"]
        assert rows[1] == ["15.01.2024", "Event A", "Details A"]
        assert header_idx == 0

    def test_comma_delimited(self):
        """Comma-delimited CSV should be parsed correctly."""
        csv_text = "Date,Title,Description\n2024-01-15,Event A,Details A\n2024-01-20,Event B,Details B\n"
        rows, header_idx = _parse_csv(_make_csv_bytes(csv_text))
        assert len(rows) == 3
        assert rows[0] == ["Date", "Title", "Description"]
        assert rows[1] == ["2024-01-15", "Event A", "Details A"]

    def test_tab_delimited(self):
        """Tab-delimited CSV should be parsed correctly."""
        csv_text = "Date\tTitle\tDescription\n2024-01-15\tEvent A\tDetails A\n2024-01-20\tEvent B\tDetails B\n"
        rows, header_idx = _parse_csv(_make_csv_bytes(csv_text))
        assert len(rows) == 3
        assert rows[0] == ["Date", "Title", "Description"]
        assert rows[1] == ["2024-01-15", "Event A", "Details A"]

    def test_utf8_encoding(self):
        """UTF-8 encoded CSV with German characters should parse correctly."""
        csv_text = "Datum;Ereignis;Beschreibung\n15.01.2024;Störung;Netzwerk-Ausfall\n"
        rows, _ = _parse_csv(_make_csv_bytes(csv_text, "utf-8"))
        assert rows[1][1] == "Störung"
        assert rows[1][2] == "Netzwerk-Ausfall"

    def test_latin1_encoding(self):
        """Latin-1 encoded CSV with German characters should parse correctly."""
        csv_text = "Datum;Ereignis;Beschreibung\n15.01.2024;Störung;Netzwerk-Ausfall\n"
        rows, _ = _parse_csv(_make_csv_bytes(csv_text, "latin-1"))
        assert rows[1][1] == "Störung"
        assert rows[1][2] == "Netzwerk-Ausfall"

    def test_utf8_bom_encoding(self):
        """UTF-8 with BOM should parse correctly."""
        csv_text = "Datum;Titel;Beschreibung\n15.01.2024;Event A;Details\n"
        bom = b"\xef\xbb\xbf"
        raw = bom + csv_text.encode("utf-8")
        rows, _ = _parse_csv(raw)
        # BOM should be stripped (utf-8-sig handles this)
        assert "Datum" in rows[0][0]

    def test_cp1252_encoding(self):
        """CP1252 (Windows) encoded CSV should parse correctly."""
        csv_text = "Datum;Ereignis\n15.01.2024;Störung\n"
        rows, _ = _parse_csv(_make_csv_bytes(csv_text, "cp1252"))
        assert rows[1][1] == "Störung"

    def test_empty_csv_returns_empty_rows(self):
        """Empty CSV should return empty row list."""
        rows, header_idx = _parse_csv(b"")
        assert rows == []
        assert header_idx is None

    def test_header_row_detection(self):
        """Header row with multiple non-empty cells should be detected."""
        csv_text = "Datum;Titel;Beschreibung\n15.01.2024;Event;Details\n"
        _, header_idx = _parse_csv(_make_csv_bytes(csv_text))
        assert header_idx == 0

    def test_month_header_not_detected_as_header_row(self):
        """Month header row should not be detected as the data header."""
        csv_text = "November (2023);;;\n;03.11.;Event A;Details\n;10.11.;Event B;Info\n"
        rows, header_idx = _parse_csv(_make_csv_bytes(csv_text))
        # The month header has content only in col 0, so header detection
        # should skip it and find the first data row with >= 2 non-empty cells
        assert header_idx == 1


# ── Column Mapping Detection (_detect_mapping) ──

class TestDetectMapping:
    def test_german_headers(self):
        """German header keywords should be recognized."""
        headers = ["Datum", "Ereignis", "Beschreibung"]
        mapping = _detect_mapping(headers, [], None)
        assert mapping["date"] == 0
        assert mapping["title"] == 1
        assert mapping["description"] == 2

    def test_english_headers(self):
        """English header keywords should be recognized."""
        headers = ["Date", "Title", "Description"]
        mapping = _detect_mapping(headers, [], None)
        assert mapping["date"] == 0
        assert mapping["title"] == 1
        assert mapping["description"] == 2

    def test_alternative_german_headers(self):
        """Alternative German keywords: Tag, Betreff, Notiz."""
        headers = ["Tag", "Betreff", "Notiz"]
        mapping = _detect_mapping(headers, [], None)
        assert mapping["date"] == 0
        assert mapping["title"] == 1
        assert mapping["description"] == 2

    def test_alternative_english_headers(self):
        """Alternative English keywords: When, Subject, Notes."""
        headers = ["When", "Subject", "Notes"]
        mapping = _detect_mapping(headers, [], None)
        assert mapping["date"] == 0
        assert mapping["title"] == 1
        assert mapping["description"] == 2

    def test_no_headers_data_detection(self):
        """Without headers, columns should be detected from data content."""
        rows = [
            ["15.01.2024", "Server outage", "The main server went down"],
            ["20.01.2024", "Recovery", "Service restored after maintenance"],
            ["25.01.2024", "Update", "Applied critical security patches to infrastructure"],
        ]
        mapping = _detect_mapping([], rows, None)
        assert mapping.get("date") == 0
        # Title should be the shorter text column, description the longer one
        assert "title" in mapping
        assert "description" in mapping

    def test_empty_headers_empty_rows(self):
        """Empty headers and empty rows should return empty mapping."""
        mapping = _detect_mapping([], [], None)
        assert mapping == {}

    def test_partial_header_match_falls_back_to_data(self):
        """If only date is matched by header, title/desc should come from data analysis."""
        headers = ["Datum", "Col B", "Col C"]
        rows = [
            ["Datum", "Col B", "Col C"],
            ["15.01.2024", "Short", "A much longer description for this event"],
            ["20.01.2024", "Brief", "Another lengthy description with many words"],
            ["25.01.2024", "Quick", "Detailed explanation of what happened exactly"],
        ]
        mapping = _detect_mapping(headers, rows, 0)
        assert mapping["date"] == 0
        # title and description should be inferred from data
        assert "title" in mapping
        assert "description" in mapping

    def test_case_insensitive_headers(self):
        """Header matching should be case-insensitive."""
        headers = ["DATUM", "TITEL", "BESCHREIBUNG"]
        mapping = _detect_mapping(headers, [], None)
        assert mapping["date"] == 0
        assert mapping["title"] == 1
        assert mapping["description"] == 2


# ── Helper Functions ──

class TestHelpers:
    def test_col_letter_single(self):
        """Single-letter column names A-Z."""
        assert _col_letter(0) == "A"
        assert _col_letter(1) == "B"
        assert _col_letter(25) == "Z"

    def test_col_letter_double(self):
        """Double-letter column names AA, AB, etc."""
        assert _col_letter(26) == "AA"
        assert _col_letter(27) == "AB"

    def test_is_date_like_iso(self):
        assert _is_date_like("2024-01-15")

    def test_is_date_like_german_full(self):
        assert _is_date_like("15.01.2024")

    def test_is_date_like_german_short(self):
        assert _is_date_like("15.01. ")

    def test_is_date_like_range(self):
        assert _is_date_like("15.01. - 17.01.")

    def test_is_date_like_not_date(self):
        assert not _is_date_like("hello")
        assert not _is_date_like("12345")

    def test_find_header_row_skips_month_headers(self):
        """_find_header_row should skip month-header rows."""
        rows = [
            ["November (2023)", "", "", ""],
            ["", "Datum", "Titel", "Beschreibung"],
            ["", "03.11.", "Event", "Details"],
        ]
        assert _find_header_row(rows) == 1

    def test_find_header_row_none_if_no_multi_col(self):
        """Return None if no row has >= 2 non-empty cells (excluding month headers)."""
        rows = [
            ["November (2023)", "", "", ""],
            ["", "", "", ""],
        ]
        assert _find_header_row(rows) is None


# ── Full Integration Tests ──

class TestIntegrationDennisExcelFormat:
    """Simulate Dennis' Excel structure:
    Column A: month headers, Column B: dates, Column C: events, Column D: details.
    """

    def _build_dennis_csv(self):
        """Build CSV mimicking the real spreadsheet layout."""
        lines = [
            # Row 0: column headers
            "Monat;Datum;Ereignis;Details",
            # Row 1: November header with data on the same row
            "November (2023);03.11.;Server down;Production outage",
            # Row 2: normal data row under November
            ";10.11.;Recovery;Back online",
            # Row 3: December header, no data
            "Dezember;;;",
            # Row 4-5: December data
            ";01.12.;Maintenance;Scheduled downtime",
            ";15.12.;DNS issue;Resolved within 2h",
            # Row 6: January header (no year -> should rollover to 2024)
            "Januar;;;",
            # Row 7-8: January data
            ";05.01.;New Year outage;ISP problems",
            ";20.01.;Cable swap;Technician visit",
            # Row 9: February (no year, still 2024)
            "Februar;;;",
            # Row 10: February data
            ";14.02.;Speed drop;50% reduction",
            # Row 11: March with explicit year
            "März (2024);;;",
            # Row 12: March data
            ";01.03.;Upgrade;New modem installed",
        ]
        return ";".join([""] * 0) + "\n".join(lines) + "\n"

    def test_full_parse_year_assignment(self):
        """All entries should get the correct year through month headers."""
        csv_bytes = _make_csv_bytes(self._build_dennis_csv())
        result = parse_file(csv_bytes, "incidents.csv")

        rows = result["rows"]
        # Collect all parsed dates
        dates = {r["title"]: r["date"] for r in rows if r.get("date")}

        # November 2023
        assert dates.get("Server down") == "2023-11-03"
        assert dates.get("Recovery") == "2023-11-10"

        # December 2023
        assert dates.get("Maintenance") == "2023-12-01"
        assert dates.get("DNS issue") == "2023-12-15"

        # January 2024 (rollover!)
        assert dates.get("New Year outage") == "2024-01-05"
        assert dates.get("Cable swap") == "2024-01-20"

        # February 2024
        assert dates.get("Speed drop") == "2024-02-14"

        # March 2024 (explicit year confirmation)
        assert dates.get("Upgrade") == "2024-03-01"

    def test_full_parse_month_header_row_with_data_included(self):
        """The 'November (2023)' row also has data in cols B/C/D, so it must be parsed."""
        csv_bytes = _make_csv_bytes(self._build_dennis_csv())
        result = parse_file(csv_bytes, "incidents.csv")

        titles = [r["title"] for r in result["rows"]]
        assert "Server down" in titles

    def test_full_parse_empty_month_headers_skipped(self):
        """Month header rows with no data (Dezember, Januar, etc.) should be skipped."""
        csv_bytes = _make_csv_bytes(self._build_dennis_csv())
        result = parse_file(csv_bytes, "incidents.csv")

        # No row should have "Dezember", "Januar", etc. as a title
        titles = [r["title"] for r in result["rows"]]
        for month in ["Dezember", "Januar", "Februar", "März (2024)"]:
            assert month not in titles

    def test_full_parse_total_count(self):
        """Total number of parsed entries should match expected data rows."""
        csv_bytes = _make_csv_bytes(self._build_dennis_csv())
        result = parse_file(csv_bytes, "incidents.csv")

        # 8 data rows: Server down, Recovery, Maintenance, DNS issue,
        # New Year outage, Cable swap, Speed drop, Upgrade
        assert result["total"] == 8

    def test_full_parse_no_skipped_entries(self):
        """All entries have valid dates, so none should be skipped."""
        csv_bytes = _make_csv_bytes(self._build_dennis_csv())
        result = parse_file(csv_bytes, "incidents.csv")
        assert result["skipped"] == 0

    def test_full_parse_mapping_detected(self):
        """Column mapping should detect Datum, Ereignis, Details."""
        csv_bytes = _make_csv_bytes(self._build_dennis_csv())
        result = parse_file(csv_bytes, "incidents.csv")

        assert "date" in result["mapping"]
        assert "title" in result["mapping"]
        assert "description" in result["mapping"]


class TestIntegrationEdgeCases:
    def test_file_too_large(self):
        """Files exceeding MAX_FILE_SIZE should raise ValueError."""
        big_bytes = b"x" * (5 * 1024 * 1024 + 1)
        with pytest.raises(ValueError, match="File too large"):
            parse_file(big_bytes, "big.csv")

    def test_unsupported_format(self):
        """Unsupported file extensions should raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported file format"):
            parse_file(b"data", "file.json")

    def test_empty_file(self):
        """Empty file should raise ValueError."""
        with pytest.raises(ValueError, match="File is empty"):
            parse_file(b"", "empty.csv")

    def test_columns_letters_in_result(self):
        """Result should include Excel-style column letters."""
        csv_text = "Datum;Titel;Beschreibung\n15.01.2024;Event;Details\n"
        result = parse_file(_make_csv_bytes(csv_text), "test.csv")
        assert result["columns"] == ["A", "B", "C"]

    def test_rows_without_date_marked_as_skipped(self):
        """Rows without a parseable date should be marked as skipped."""
        csv_text = "Datum;Titel;Beschreibung\nno-date;Event A;Details\n15.01.2024;Event B;Info\n"
        result = parse_file(_make_csv_bytes(csv_text), "test.csv")
        skipped_rows = [r for r in result["rows"] if r.get("skipped")]
        non_skipped = [r for r in result["rows"] if not r.get("skipped")]
        assert len(skipped_rows) == 1
        assert skipped_rows[0]["title"] == "Event A"
        assert len(non_skipped) == 1
        assert non_skipped[0]["title"] == "Event B"

    def test_none_string_cleaned_up(self):
        """Title or description of literal 'None' should be cleaned to empty string."""
        csv_text = "Datum;Titel;Beschreibung\n15.01.2024;None;None\n"
        result = parse_file(_make_csv_bytes(csv_text), "test.csv")
        # The row has no title and no description after cleanup, and a valid date,
        # but since title and desc are both empty, the row may or may not be kept.
        # The parser keeps it because raw_date is non-empty.
        for row in result["rows"]:
            assert row["title"] != "None"
            assert row["description"] != "None"

    def test_all_empty_rows_skipped(self):
        """Completely empty data rows should be skipped entirely."""
        csv_text = "Datum;Titel;Beschreibung\n;;;\n;;;\n15.01.2024;Event;Details\n"
        result = parse_file(_make_csv_bytes(csv_text), "test.csv")
        assert result["total"] == 1
        assert result["rows"][0]["title"] == "Event"
