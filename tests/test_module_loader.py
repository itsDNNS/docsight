# tests/test_module_loader.py
import json
import os
import tempfile

import pytest
from app.module_loader import ModuleInfo, validate_manifest, ManifestError, discover_modules, register_module_config


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


class TestDiscoverModules:
    """Test directory scanning for manifest.json files."""

    def _make_module(self, base_dir, name, manifest_data):
        """Helper: create a module directory with manifest.json."""
        mod_dir = os.path.join(base_dir, name)
        os.makedirs(mod_dir, exist_ok=True)
        with open(os.path.join(mod_dir, "manifest.json"), "w") as f:
            json.dump(manifest_data, f)
        return mod_dir

    def _valid_manifest(self, mod_id="test.module", **overrides):
        """Helper: return a minimal valid manifest dict."""
        m = {
            "id": mod_id,
            "name": "Test",
            "description": "Test module",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "integration",
            "contributes": {},
        }
        m.update(overrides)
        return m

    def test_discover_from_single_directory(self):
        with tempfile.TemporaryDirectory() as d:
            self._make_module(d, "mod_a", self._valid_manifest("test.mod_a"))
            modules = discover_modules(search_paths=[d])
            assert len(modules) == 1
            assert modules[0].id == "test.mod_a"

    def test_discover_from_multiple_directories(self):
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            self._make_module(d1, "mod_a", self._valid_manifest("test.mod_a"))
            self._make_module(d2, "mod_b", self._valid_manifest("test.mod_b"))
            modules = discover_modules(search_paths=[d1, d2])
            ids = {m.id for m in modules}
            assert ids == {"test.mod_a", "test.mod_b"}

    def test_skip_directory_without_manifest(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "no_manifest"))
            modules = discover_modules(search_paths=[d])
            assert len(modules) == 0

    def test_skip_invalid_manifest(self):
        """Invalid manifests are skipped, not raised."""
        with tempfile.TemporaryDirectory() as d:
            self._make_module(d, "bad", {"id": "bad"})  # missing fields
            self._make_module(d, "good", self._valid_manifest("test.good"))
            modules = discover_modules(search_paths=[d])
            assert len(modules) == 1
            assert modules[0].id == "test.good"

    def test_skip_nonexistent_directory(self):
        """Non-existent search paths are silently skipped."""
        modules = discover_modules(search_paths=["/nonexistent/path"])
        assert len(modules) == 0

    def test_duplicate_id_keeps_first(self):
        """If two modules share an ID, keep the first one found."""
        with tempfile.TemporaryDirectory() as d1, tempfile.TemporaryDirectory() as d2:
            self._make_module(d1, "mod", self._valid_manifest("test.dup", name="First"))
            self._make_module(d2, "mod", self._valid_manifest("test.dup", name="Second"))
            modules = discover_modules(search_paths=[d1, d2])
            assert len(modules) == 1
            assert modules[0].name == "First"

    def test_broken_json_skipped(self):
        """Malformed JSON is skipped gracefully."""
        with tempfile.TemporaryDirectory() as d:
            mod_dir = os.path.join(d, "broken")
            os.makedirs(mod_dir)
            with open(os.path.join(mod_dir, "manifest.json"), "w") as f:
                f.write("{not valid json")
            modules = discover_modules(search_paths=[d])
            assert len(modules) == 0


class TestRegisterModuleConfig:
    """Test module config defaults registration."""

    def test_register_config_defaults(self):
        """Module config defaults are added to DEFAULTS."""
        from app import config as cfg
        original_defaults = dict(cfg.DEFAULTS)
        try:
            register_module_config({"my_mod_enabled": False, "my_mod_url": "http://example.com"})
            assert cfg.DEFAULTS["my_mod_enabled"] is False
            assert cfg.DEFAULTS["my_mod_url"] == "http://example.com"
        finally:
            # Restore
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)

    def test_register_bool_keys(self):
        """Boolean config keys are auto-detected and added to BOOL_KEYS."""
        from app import config as cfg
        original = set(cfg.BOOL_KEYS)
        try:
            register_module_config({"my_feat_enabled": False, "my_feat_url": ""})
            assert "my_feat_enabled" in cfg.BOOL_KEYS
            assert "my_feat_url" not in cfg.BOOL_KEYS
        finally:
            cfg.BOOL_KEYS.clear()
            cfg.BOOL_KEYS.update(original)

    def test_register_int_keys(self):
        """Integer config keys are auto-detected and added to INT_KEYS."""
        from app import config as cfg
        original = set(cfg.INT_KEYS)
        try:
            register_module_config({"my_interval": 300, "my_name": "test"})
            assert "my_interval" in cfg.INT_KEYS
            assert "my_name" not in cfg.INT_KEYS
        finally:
            cfg.INT_KEYS.clear()
            cfg.INT_KEYS.update(original)

    def test_does_not_overwrite_existing_defaults(self):
        """Module config must not overwrite existing core config keys."""
        from app import config as cfg
        register_module_config({"poll_interval": 999})
        assert cfg.DEFAULTS["poll_interval"] != 999  # unchanged
