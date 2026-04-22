"""Tests for theme module behavior and loading."""

# tests/test_module_loader.py
import importlib
import json
import os
import tempfile
import textwrap

import pytest
from flask import Flask
from app.module_loader import ModuleInfo, validate_manifest, ManifestError, discover_modules, register_module_config, merge_module_i18n, load_module_routes, load_module_collector, load_module_publisher, load_module_driver, setup_module_static, setup_module_templates, ModuleLoader

_VALID_THEME = {
    "dark": {
        "--bg": "#1f2937", "--surface": "#1f2937", "--card": "#1f2937",
        "--text": "#f0f0f0", "--accent": "#a855f7",
        "--good": "#10b981", "--warn": "#f59e0b", "--crit": "#ef4444",
    },
    "light": {
        "--bg": "#ffffff", "--surface": "#ffffff", "--card": "#f9fafb",
        "--text": "#111827", "--accent": "#9333ea",
        "--good": "#059669", "--warn": "#d97706", "--crit": "#dc2626",
    },
}

class TestThemeContributes:
    """Test theme module loading and validation."""

    def test_theme_is_valid_contributes(self):
        from app.module_loader import VALID_CONTRIBUTES
        assert "theme" in VALID_CONTRIBUTES

    def test_manifest_with_theme_contributes_valid(self):
        raw = {
            "id": "test.mytheme",
            "name": "My Theme",
            "description": "A test theme",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "theme",
            "contributes": {"theme": "theme.json"},
        }
        info = validate_manifest(raw, "/path")
        assert "theme" in info.contributes

    def test_module_info_has_theme_data_field(self):
        info = ModuleInfo(
            id="test.theme", name="T", description="d", version="1.0.0",
            author="a", min_app_version="2026.2", type="theme",
            contributes={"theme": "theme.json"}, path="/tmp",
        )
        assert info.theme_data is None

    def test_validate_theme_valid(self):
        from app.module_loader import validate_theme
        data = {
            "dark": {"--bg": "#1f2937", "--text": "#f0f0f0", "--accent": "#a855f7"},
            "light": {"--bg": "#ffffff", "--text": "#111827", "--accent": "#9333ea"},
        }
        validate_theme(data)  # Should not raise

    def test_validate_theme_invalid_shapes(self):
        from app.module_loader import validate_theme

        invalid_cases = [
            ({"light": {"--bg": "#ffffff"}}, "dark"),
            ({"dark": {"--bg": "#1f2937"}}, "light"),
            ({"dark": {}, "light": {"--bg": "#fff"}}, "empty"),
            ({"dark": {"--bg": 123}, "light": {"--bg": "#fff"}}, "string"),
        ]

        for data, error_match in invalid_cases:
            with pytest.raises(ManifestError, match=error_match):
                validate_theme(data)

    def test_validate_theme_with_meta(self):
        from app.module_loader import validate_theme
        data = {
            "meta": {"family": "dark-first"},
            "dark": {"--bg": "#1f2937"},
            "light": {"--bg": "#ffffff"},
        }
        validate_theme(data)  # meta is optional, should not raise


_VALID_THEME = {
    "dark": {
        "--bg": "#1f2937", "--surface": "#1f2937", "--card": "#1f2937",
        "--text": "#f0f0f0", "--accent": "#a855f7",
        "--good": "#10b981", "--warn": "#f59e0b", "--crit": "#ef4444",
    },
    "light": {
        "--bg": "#ffffff", "--surface": "#ffffff", "--card": "#f9fafb",
        "--text": "#111827", "--accent": "#9333ea",
        "--good": "#059669", "--warn": "#d97706", "--crit": "#dc2626",
    },
}


class TestThemeLoading:
    """Test theme module discovery and loading."""

    def test_theme_module_loads_data(self, tmp_path):
        mod_dir = tmp_path / "mytheme"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "test.mytheme",
            "name": "My Theme",
            "description": "desc",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "theme",
            "contributes": {"theme": "theme.json"},
        }))
        (mod_dir / "theme.json").write_text(json.dumps(_VALID_THEME))

        app = Flask(__name__)
        app.config["TESTING"] = True
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()

        mod = next(m for m in loader.get_modules() if m.id == "test.mytheme")
        assert mod.theme_data is not None
        assert "--bg" in mod.theme_data["dark"]
        assert "--bg" in mod.theme_data["light"]

    def test_theme_missing_file_sets_error(self, tmp_path):
        mod_dir = tmp_path / "badtheme"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "test.badtheme",
            "name": "Bad Theme",
            "description": "desc",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "theme",
            "contributes": {"theme": "theme.json"},
        }))
        # No theme.json file!

        app = Flask(__name__)
        app.config["TESTING"] = True
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()

        mod = next(m for m in loader.get_modules() if m.id == "test.badtheme")
        assert mod.error is not None
        assert "not found" in mod.error.lower()

    def test_theme_invalid_json_sets_error(self, tmp_path):
        mod_dir = tmp_path / "invalidtheme"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "test.invalidtheme",
            "name": "Invalid Theme",
            "description": "desc",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "theme",
            "contributes": {"theme": "theme.json"},
        }))
        (mod_dir / "theme.json").write_text(json.dumps({"dark": {}}))  # Missing light

        app = Flask(__name__)
        app.config["TESTING"] = True
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()

        mod = next(m for m in loader.get_modules() if m.id == "test.invalidtheme")
        assert mod.error is not None


class TestGetThemeModules:
    """Test the get_theme_modules helper."""

    def test_returns_theme_modules_only(self, tmp_path):
        # Theme module
        mod_t = tmp_path / "theme1"
        mod_t.mkdir()
        (mod_t / "manifest.json").write_text(json.dumps({
            "id": "test.theme1", "name": "Theme 1", "description": "d",
            "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
            "type": "theme", "contributes": {"theme": "theme.json"},
        }))
        (mod_t / "theme.json").write_text(json.dumps(_VALID_THEME))

        # Regular module
        mod_r = tmp_path / "regular"
        mod_r.mkdir()
        (mod_r / "manifest.json").write_text(json.dumps({
            "id": "test.regular", "name": "R", "description": "d",
            "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
            "type": "integration", "contributes": {},
        }))

        app = Flask(__name__)
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()

        theme_mods = loader.get_theme_modules()
        assert len(theme_mods) == 1
        assert theme_mods[0].id == "test.theme1"

    def test_returns_empty_when_no_themes(self, tmp_path):
        mod_r = tmp_path / "regular"
        mod_r.mkdir()
        (mod_r / "manifest.json").write_text(json.dumps({
            "id": "test.regular", "name": "R", "description": "d",
            "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
            "type": "integration", "contributes": {},
        }))

        app = Flask(__name__)
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()

        assert loader.get_theme_modules() == []

