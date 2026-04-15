"""Tests for _version_newer date-based version comparison."""

import pytest

from app.web import _version_newer


class TestVersionNewer:
    """_version_newer compares date-based versions: YYYY-MM-DD.N"""

    def test_later_date_is_newer(self):
        assert _version_newer("2026-02-16.1", "2026-02-13.8") is True

    def test_earlier_date_is_not_newer(self):
        assert _version_newer("2026-02-13.1", "2026-02-16.1") is False

    def test_same_date_higher_build_is_newer(self):
        assert _version_newer("2026-02-16.2", "2026-02-16.1") is True

    def test_same_date_lower_build_is_not_newer(self):
        assert _version_newer("2026-02-16.1", "2026-02-16.2") is False

    def test_same_version_is_not_newer(self):
        assert _version_newer("2026-02-16.1", "2026-02-16.1") is False

    # Edge case: two-digit build number (the bug this fix addresses)
    def test_build_10_greater_than_9(self):
        assert _version_newer("2026-02-16.10", "2026-02-16.9") is True

    def test_build_9_not_greater_than_10(self):
        assert _version_newer("2026-02-16.9", "2026-02-16.10") is False

    def test_build_100_greater_than_99(self):
        assert _version_newer("2026-02-16.100", "2026-02-16.99") is True

    # Date without build suffix
    def test_date_only_newer(self):
        assert _version_newer("2026-03-01", "2026-02-28") is True

    def test_date_only_not_newer(self):
        assert _version_newer("2026-02-28", "2026-03-01") is False

    def test_date_only_equal(self):
        assert _version_newer("2026-02-28", "2026-02-28") is False

    # Mixed: one with build, one without
    def test_same_date_with_build_vs_without(self):
        assert _version_newer("2026-02-16.1", "2026-02-16") is True

    def test_same_date_without_build_vs_with(self):
        assert _version_newer("2026-02-16", "2026-02-16.1") is False

    # Year rollover
    def test_year_boundary(self):
        assert _version_newer("2027-01-01.1", "2026-12-31.5") is True
