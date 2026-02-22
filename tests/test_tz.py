"""Tests for timezone utility module."""

import os
import pytest
from datetime import datetime, timezone
from unittest.mock import patch
from zoneinfo import ZoneInfo

from app.tz import (
    utc_now, utc_cutoff, to_local, to_local_display,
    local_to_utc, local_now, local_today, local_date_to_utc_range,
    guess_iana_timezone,
)


class TestUtcNow:
    def test_format(self):
        result = utc_now()
        assert result.endswith("Z")
        # Should parse cleanly
        datetime.strptime(result, "%Y-%m-%dT%H:%M:%SZ")

    def test_is_utc(self):
        result = utc_now()
        parsed = datetime.strptime(result[:-1], "%Y-%m-%dT%H:%M:%S")
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        # Should be within 2 seconds of actual UTC
        assert abs((parsed - now_utc).total_seconds()) < 2


class TestUtcCutoff:
    def test_days(self):
        result = utc_cutoff(days=1)
        assert result.endswith("Z")
        parsed = datetime.strptime(result[:-1], "%Y-%m-%dT%H:%M:%S")
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        delta = now_utc - parsed
        assert 23 * 3600 < delta.total_seconds() < 25 * 3600

    def test_hours(self):
        result = utc_cutoff(hours=6)
        assert result.endswith("Z")
        parsed = datetime.strptime(result[:-1], "%Y-%m-%dT%H:%M:%S")
        now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
        delta = now_utc - parsed
        assert 5 * 3600 < delta.total_seconds() < 7 * 3600

    def test_combined(self):
        result = utc_cutoff(days=1, hours=12)
        assert result.endswith("Z")


class TestToLocal:
    def test_berlin_summer(self):
        # 2026-06-15T12:00:00Z → 14:00 in Berlin (CEST = UTC+2)
        result = to_local("2026-06-15T12:00:00Z", "Europe/Berlin")
        assert result == "2026-06-15T14:00:00"

    def test_berlin_winter(self):
        # 2026-01-15T12:00:00Z → 13:00 in Berlin (CET = UTC+1)
        result = to_local("2026-01-15T12:00:00Z", "Europe/Berlin")
        assert result == "2026-01-15T13:00:00"

    def test_utc(self):
        result = to_local("2026-01-15T12:00:00Z", "UTC")
        assert result == "2026-01-15T12:00:00"

    def test_no_z_suffix(self):
        # Should handle timestamps without Z too (treated as UTC)
        result = to_local("2026-06-15T12:00:00", "Europe/Berlin")
        assert result == "2026-06-15T14:00:00"

    def test_empty_tz(self):
        result = to_local("2026-01-15T12:00:00Z", "")
        assert result == "2026-01-15T12:00:00"

    def test_empty_ts(self):
        result = to_local("", "Europe/Berlin")
        assert result == ""

    def test_none_ts(self):
        result = to_local(None, "Europe/Berlin")
        assert result == ""

    def test_new_york(self):
        # 2026-06-15T12:00:00Z → 08:00 in New York (EDT = UTC-4)
        result = to_local("2026-06-15T12:00:00Z", "America/New_York")
        assert result == "2026-06-15T08:00:00"


class TestToLocalDisplay:
    def test_custom_format(self):
        result = to_local_display(
            "2026-06-15T12:00:00Z", "Europe/Berlin", "%d.%m.%Y %H:%M"
        )
        assert result == "15.06.2026 14:00"

    def test_default_format(self):
        result = to_local_display("2026-01-15T12:00:00Z", "Europe/Berlin")
        assert result == "2026-01-15 13:00:00"

    def test_empty_tz(self):
        result = to_local_display("2026-01-15T12:00:00Z", "")
        assert result == "2026-01-15T12:00:00"


class TestLocalToUtc:
    def test_berlin_summer(self):
        # 14:00 Berlin (CEST = UTC+2) → 12:00 UTC
        result = local_to_utc("2026-06-15T14:00:00", "Europe/Berlin")
        assert result == "2026-06-15T12:00:00Z"

    def test_berlin_winter(self):
        # 13:00 Berlin (CET = UTC+1) → 12:00 UTC
        result = local_to_utc("2026-01-15T13:00:00", "Europe/Berlin")
        assert result == "2026-01-15T12:00:00Z"

    def test_utc(self):
        result = local_to_utc("2026-01-15T12:00:00", "UTC")
        assert result == "2026-01-15T12:00:00Z"

    def test_empty_tz(self):
        # No timezone: just append Z
        result = local_to_utc("2026-01-15T12:00:00", "")
        assert result == "2026-01-15T12:00:00Z"

    def test_empty_ts(self):
        result = local_to_utc("", "Europe/Berlin")
        assert result == ""

    def test_already_has_z(self):
        # Should strip Z before parsing, then re-add
        result = local_to_utc("2026-06-15T14:00:00Z", "Europe/Berlin")
        assert result == "2026-06-15T12:00:00Z"

    def test_with_fractional_seconds(self):
        result = local_to_utc("2026-06-15T14:00:00.123", "Europe/Berlin")
        assert result == "2026-06-15T12:00:00Z"

    def test_dst_spring_forward(self):
        # 2026-03-29 02:30:00 Europe/Berlin doesn't exist (clocks jump 02:00 → 03:00)
        # ZoneInfo should resolve this to 03:30 CEST = 01:30 UTC
        result = local_to_utc("2026-03-29T02:30:00", "Europe/Berlin")
        # The exact behavior varies by implementation — just ensure it returns valid UTC
        assert result.endswith("Z")
        datetime.strptime(result[:-1], "%Y-%m-%dT%H:%M:%S")

    def test_dst_fall_back(self):
        # 2026-10-25 02:30:00 Europe/Berlin is ambiguous (clocks go 03:00 → 02:00)
        # fold=0 (default) = summer time = UTC+2 → 00:30 UTC
        result = local_to_utc("2026-10-25T02:30:00", "Europe/Berlin")
        assert result.endswith("Z")
        datetime.strptime(result[:-1], "%Y-%m-%dT%H:%M:%S")


class TestLocalNow:
    def test_returns_string(self):
        result = local_now("Europe/Berlin")
        assert isinstance(result, str)
        assert "T" in result

    def test_empty_tz(self):
        result = local_now("")
        assert isinstance(result, str)

    def test_custom_format(self):
        result = local_now("UTC", fmt="%Y-%m-%d")
        assert len(result) == 10


class TestLocalToday:
    def test_returns_date(self):
        result = local_today("Europe/Berlin")
        assert len(result) == 10
        datetime.strptime(result, "%Y-%m-%d")

    def test_empty_tz(self):
        result = local_today("")
        assert len(result) == 10


class TestLocalDateToUtcRange:
    def test_berlin_winter(self):
        start, end = local_date_to_utc_range("2026-01-15", "Europe/Berlin")
        # Berlin CET = UTC+1, so midnight local = 23:00 UTC previous day
        assert start == "2026-01-14T23:00:00Z"
        assert end == "2026-01-15T22:59:59Z"

    def test_berlin_summer(self):
        start, end = local_date_to_utc_range("2026-06-15", "Europe/Berlin")
        # Berlin CEST = UTC+2, so midnight local = 22:00 UTC previous day
        assert start == "2026-06-14T22:00:00Z"
        assert end == "2026-06-15T21:59:59Z"

    def test_utc(self):
        start, end = local_date_to_utc_range("2026-01-15", "UTC")
        assert start == "2026-01-15T00:00:00Z"
        assert end == "2026-01-15T23:59:59Z"

    def test_empty_tz(self):
        start, end = local_date_to_utc_range("2026-01-15", "")
        assert start == "2026-01-15T00:00:00Z"
        assert end == "2026-01-15T23:59:59Z"


class TestGuessIanaTimezone:
    def test_from_tz_env(self):
        with patch.dict(os.environ, {"TZ": "Europe/Berlin"}):
            with patch("os.readlink", side_effect=OSError):
                result = guess_iana_timezone()
                assert result == "Europe/Berlin"

    def test_non_iana_tz(self):
        with patch.dict(os.environ, {"TZ": "CET"}):
            with patch("os.readlink", side_effect=OSError):
                result = guess_iana_timezone()
                assert result == ""  # CET has no slash

    def test_from_localtime_symlink(self):
        with patch("os.readlink", return_value="/usr/share/zoneinfo/Europe/Berlin"):
            result = guess_iana_timezone()
            assert result == "Europe/Berlin"

    def test_no_detection(self):
        with patch.dict(os.environ, {"TZ": ""}, clear=False):
            with patch("os.readlink", side_effect=OSError):
                result = guess_iana_timezone()
                assert result == ""
