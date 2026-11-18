"""Tests for the generic module downloader."""


from app.module_download import is_trusted_url, validate_registry_entry, fetch_registry


class TestIsTrustedUrl:
    def test_github_raw(self):
        assert is_trusted_url("https://raw.githubusercontent.com/user/repo/main/file") is True

    def test_github_api(self):
        assert is_trusted_url("https://api.github.com/repos/user/repo/contents/dir") is True

    def test_http_rejected(self):
        assert is_trusted_url("http://raw.githubusercontent.com/user/repo/main/file") is False

    def test_untrusted_host(self):
        assert is_trusted_url("https://evil.com/malicious") is False

    def test_empty_string(self):
        assert is_trusted_url("") is False

    def test_none(self):
        assert is_trusted_url(None) is False


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
