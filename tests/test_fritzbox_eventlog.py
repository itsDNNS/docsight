"""Tests for FritzBox event log parser."""

import pytest
from app.fritzbox import (
    _parse_event_log, _classify_event, _normalize_timestamp,
    DOCSIS_EVENT_CODES, _DOCSIS_EVENT_PATTERNS,
)


# ── _normalize_timestamp ──

class TestNormalizeTimestamp:
    def test_german_date_format(self):
        result = _normalize_timestamp("15.01.2026 14:30:00")
        assert result == "2026-01-15T14:30:00"

    def test_german_date_no_seconds(self):
        result = _normalize_timestamp("01.02.2026 08:15")
        assert result == "2026-02-01T08:15:00"

    def test_already_iso(self):
        result = _normalize_timestamp("2026-01-15T14:30:00")
        assert result == "2026-01-15T14:30:00"

    def test_unparseable(self):
        result = _normalize_timestamp("garbage")
        assert result == "garbage"


# ── _classify_event ──

class TestClassifyEvent:
    def test_t3_timeout(self):
        assert _classify_event("T3 Timeout detected") == "docsis_error"

    def test_ranging_request(self):
        assert _classify_event("Ranging Request not acknowledged") == "docsis_error"

    def test_sync_loss(self):
        assert _classify_event("SYNC Loss on channel 3") == "docsis_error"

    def test_registration_failed(self):
        assert _classify_event("Registration Failed") == "docsis_error"

    def test_cable_modem_reset(self):
        assert _classify_event("Cable Modem Reboot") == "docsis_error"

    def test_dhcp_failed(self):
        assert _classify_event("DHCP NAK received") == "docsis_error"

    def test_ds_channel_lost(self):
        assert _classify_event("DS Channel Lost") == "docsis_error"

    def test_us_channel_lock(self):
        assert _classify_event("US Channel Lock") == "docsis_error"

    # German patterns
    def test_zeitueberschreitung(self):
        assert _classify_event("Zeitüberschreitung bei Registrierung") == "docsis_error"

    def test_dsl_synchronisierung(self):
        assert _classify_event("DSL-Synchronisierung gestartet") == "docsis_error"

    def test_kabelmodem(self):
        assert _classify_event("Kabelmodem Neustart") == "docsis_error"

    def test_verbindung_getrennt(self):
        assert _classify_event("Verbindung getrennt") == "docsis_error"

    # Connection events (not DOCSIS error but still captured)
    def test_internet_connection(self):
        assert _classify_event("Internet connection established") == "connection"

    def test_cable_keyword(self):
        assert _classify_event("cable modem status") == "connection"

    def test_online_keyword(self):
        assert _classify_event("System online since 2026-01-15") == "connection"

    # Non-matching events
    def test_irrelevant_event(self):
        assert _classify_event("WLAN device connected") is None

    def test_empty_string(self):
        assert _classify_event("") is None


# ── _parse_event_log ──

class TestParseEventLog:
    def test_list_format_entries(self):
        """FritzBox returns log as list of [date, time, message, category]."""
        entries = [
            ["15.01.2026", "14:30:00", "T3 Timeout", "system"],
            ["15.01.2026", "14:31:00", "Internet connection established", "internet"],
            ["15.01.2026", "14:32:00", "WLAN device connected", "wlan"],  # should be filtered
        ]
        result = _parse_event_log(entries, max_entries=100)
        assert len(result) == 2  # T3 and Internet, not WLAN
        assert result[0]["docsis_code"] == "T3"
        assert result[0]["category"] == "docsis_error"
        assert result[1]["category"] == "connection"

    def test_dict_format_entries(self):
        """Some FritzBox APIs return dicts."""
        entries = [
            {"date": "15.01.2026", "time": "10:00:00", "msg": "T4 Timeout", "group": "system"},
        ]
        result = _parse_event_log(entries, max_entries=100)
        assert len(result) == 1
        assert result[0]["docsis_code"] == "T4"

    def test_max_entries_limit(self):
        entries = [
            ["15.01.2026", f"10:{i:02d}:00", "T3 Timeout", "system"]
            for i in range(50)
        ]
        result = _parse_event_log(entries, max_entries=10)
        assert len(result) <= 10

    def test_empty_message_skipped(self):
        entries = [["15.01.2026", "10:00:00", "", "system"]]
        result = _parse_event_log(entries, max_entries=100)
        assert result == []

    def test_timestamp_normalized(self):
        entries = [
            ["15.01.2026", "14:30:00", "T3 Timeout", "system"],
        ]
        result = _parse_event_log(entries, max_entries=100)
        assert result[0]["timestamp"] == "2026-01-15T14:30:00"

    def test_all_docsis_codes_detected(self):
        """Each T1-T6 code should be detected."""
        for code in DOCSIS_EVENT_CODES:
            entries = [
                ["01.01.2026", "00:00:00", f"{code} Timeout something", "system"],
            ]
            result = _parse_event_log(entries, max_entries=100)
            assert len(result) >= 1
            assert result[0]["docsis_code"] == code

    def test_non_docsis_entry_filtered(self):
        entries = [
            ["01.01.2026", "00:00:00", "Firmware update available", "update"],
        ]
        result = _parse_event_log(entries, max_entries=100)
        assert result == []

    def test_invalid_entry_format(self):
        """Non-list, non-dict entries should be skipped."""
        entries = ["just a string", 42, None]
        result = _parse_event_log(entries, max_entries=100)
        assert result == []


# ── DOCSIS_EVENT_CODES ──

class TestDocsisEventCodes:
    def test_all_t_codes_present(self):
        for code in ["T1", "T2", "T3", "T4", "T5", "T6"]:
            assert code in DOCSIS_EVENT_CODES
            assert isinstance(DOCSIS_EVENT_CODES[code], str)

    def test_t3_description(self):
        assert "Ranging" in DOCSIS_EVENT_CODES["T3"] or "timeout" in DOCSIS_EVENT_CODES["T3"].lower()
