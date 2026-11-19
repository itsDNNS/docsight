"""Tests for the generic module downloader."""

import pytest

from app.module_download import is_trusted_url, validate_registry_entry, fetch_registry


@pytest.mark.parametrize("url,expected", [
    ("https://raw.githubusercontent.com/user/repo/main/file", True),
    ("https://api.github.com/repos/user/repo/contents/dir", True),
    ("https://github.com/user/repo", True),
    ("http://raw.githubusercontent.com/user/repo/main/file", False),
    ("https://evil.com/malicious", False),
    ("https://localhost:8080/steal", False),
    ("file:///etc/passwd", False),
    ("gopher://internal:25/", False),
    ("", False),
    (None, False),
])
def test_is_trusted_url(url, expected):
    assert is_trusted_url(url) is expected


class TestValidateRegistryEntry:
    def test_valid_entry(self):
        entry = {"id": "test", "name": "Test", "version": "1.0.0",
                 "download_url": "https://example.com", "min_app_version": "2026.2"}
        assert validate_registry_entry(entry) is True

    def test_missing_field(self):
        entry = {"id": "test", "name": "Test"}
        assert validate_registry_entry(entry) is False


class TestFetchRegistry:
    def test_returns_empty_on_invalid_url(self):
        result = fetch_registry("https://invalid.example.com/nonexistent", key="modules")
        assert result == []
