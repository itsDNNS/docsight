"""Tests for theme registry client."""
import json
from unittest.mock import patch, MagicMock

import pytest

from app.theme_registry import download_theme, fetch_registry
from app.module_download import validate_registry_entry


@pytest.mark.parametrize("files,valid", [
    ([], False),
    (["manifest.json"], False),
    (["theme.json"], False),
    (["manifest.json", "theme.json"], True),
])
def test_download_theme_validation_leaves_cleanup_to_caller(tmp_path, files, valid):
    target = tmp_path / "theme"
    target.mkdir()
    sentinel = target / "partial.json"
    sentinel.write_text("{}", encoding="utf-8")
    for name in files:
        (target / name).write_text("{}", encoding="utf-8")
    url = "https://api.github.com/repos/example/themes/contents/theme"

    with patch("app.theme_registry.download_github_directory", return_value=True) as download, \
         patch("shutil.rmtree") as remove:
        assert download_theme(url, str(target), 17) is valid
        download.assert_called_once_with(url, str(target), 17)
        remove.assert_not_called()
    assert sentinel.read_text(encoding="utf-8") == "{}"


class TestValidateRegistryEntry:
    def test_valid_entry(self):
        entry = {
            "id": "docsight.theme_neon",
            "name": "Neon",
            "description": "Neon theme",
            "version": "1.0.0",
            "author": "Community",
            "download_url": "https://example.com/neon",
            "min_app_version": "2026.2",
        }
        assert validate_registry_entry(entry) is True

    def test_missing_id_invalid(self):
        entry = {"name": "Neon", "version": "1.0.0"}
        assert validate_registry_entry(entry) is False


class TestFetchRegistry:
    @patch("app.module_download.urllib.request.urlopen")
    def test_fetches_and_parses_registry(self, mock_urlopen):
        registry = {
            "version": 1,
            "themes": [
                {
                    "id": "docsight.theme_neon",
                    "name": "Neon",
                    "description": "d",
                    "version": "1.0.0",
                    "author": "a",
                    "download_url": "https://example.com/neon",
                    "min_app_version": "2026.2",
                }
            ],
        }
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(registry).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = fetch_registry("https://raw.githubusercontent.com/user/repo/main/registry.json")
        assert len(result) == 1
        assert result[0]["id"] == "docsight.theme_neon"

    @patch("app.module_download.urllib.request.urlopen")
    def test_returns_empty_on_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Network error")
        result = fetch_registry("https://raw.githubusercontent.com/user/repo/main/registry.json")
        assert result == []

    def test_rejects_untrusted_url(self):
        result = fetch_registry("https://example.com/registry.json")
        assert result == []
