"""Tests for theme registry client."""
import json
from unittest.mock import patch, MagicMock

import pytest

from app.theme_registry import fetch_registry, validate_registry_entry


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
    @patch("app.theme_registry.urllib.request.urlopen")
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

        result = fetch_registry("https://example.com/registry.json")
        assert len(result) == 1
        assert result[0]["id"] == "docsight.theme_neon"

    @patch("app.theme_registry.urllib.request.urlopen")
    def test_returns_empty_on_error(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Network error")
        result = fetch_registry("https://example.com/registry.json")
        assert result == []
