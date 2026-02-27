# tests/test_module_loader.py
import pytest
from app.module_loader import ModuleInfo, validate_manifest, ManifestError


class TestValidateManifest:
    """Test manifest.json validation."""

    def test_valid_minimal_manifest(self):
        """Minimal valid manifest with only required fields."""
        raw = {
            "id": "docsight.test",
            "name": "Test Module",
            "description": "A test module",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "integration",
            "contributes": {},
        }
        info = validate_manifest(raw, "/some/path")
        assert info.id == "docsight.test"
        assert info.name == "Test Module"
        assert info.version == "1.0.0"
        assert info.type == "integration"
        assert info.builtin is False

    def test_valid_full_manifest(self):
        """Full manifest with all optional fields."""
        raw = {
            "id": "docsight.weather",
            "name": "Weather",
            "description": "Weather overlay",
            "version": "1.0.0",
            "author": "DOCSight Team",
            "homepage": "https://github.com/itsDNNS/docsight",
            "license": "MIT",
            "minAppVersion": "2026.2",
            "type": "integration",
            "contributes": {
                "collector": "collector.py:WeatherCollector",
                "routes": "routes.py",
                "settings": "templates/settings.html",
                "tab": "templates/tab.html",
                "card": "templates/card.html",
                "i18n": "i18n/",
                "static": "static/",
            },
            "config": {"weather_enabled": False},
            "menu": {"label_key": "weather.name", "icon": "thermometer", "order": 50},
        }
        info = validate_manifest(raw, "/modules/weather")
        assert info.id == "docsight.weather"
        assert info.contributes["collector"] == "collector.py:WeatherCollector"
        assert info.config == {"weather_enabled": False}
        assert info.menu["icon"] == "thermometer"

    def test_missing_required_field_raises(self):
        """Missing 'id' should raise ManifestError."""
        raw = {
            "name": "No ID",
            "description": "x",
            "version": "1.0.0",
            "author": "x",
            "minAppVersion": "2026.2",
            "type": "integration",
            "contributes": {},
        }
        with pytest.raises(ManifestError, match="id"):
            validate_manifest(raw, "/path")

    def test_invalid_type_raises(self):
        """Invalid module type should raise ManifestError."""
        raw = {
            "id": "test.mod",
            "name": "x",
            "description": "x",
            "version": "1.0.0",
            "author": "x",
            "minAppVersion": "2026.2",
            "type": "invalid_type",
            "contributes": {},
        }
        with pytest.raises(ManifestError, match="type"):
            validate_manifest(raw, "/path")

    def test_invalid_id_format_raises(self):
        """ID with spaces or special chars should raise."""
        raw = {
            "id": "bad id!",
            "name": "x",
            "description": "x",
            "version": "1.0.0",
            "author": "x",
            "minAppVersion": "2026.2",
            "type": "integration",
            "contributes": {},
        }
        with pytest.raises(ManifestError, match="id"):
            validate_manifest(raw, "/path")

    def test_builtin_flag_from_path(self):
        """Modules under app/modules/ should be marked as builtin."""
        raw = {
            "id": "docsight.weather",
            "name": "x",
            "description": "x",
            "version": "1.0.0",
            "author": "x",
            "minAppVersion": "2026.2",
            "type": "integration",
            "contributes": {},
        }
        info = validate_manifest(raw, "/app/app/modules/weather")
        assert info.builtin is True

        info2 = validate_manifest(raw, "/modules/weather")
        assert info2.builtin is False
