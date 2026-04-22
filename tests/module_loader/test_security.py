"""Tests for module loader path traversal and security constraints."""

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

class TestThemeSecurity:
    """Theme modules must NOT have collector, routes, or publisher."""

    def test_theme_forbidden_contributions_rejected(self):
        base = {
            "id": "test.badtheme",
            "name": "Bad Theme",
            "description": "d",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "theme",
        }

        for contribution, spec in {
            "collector": "collector.py:Foo",
            "routes": "routes.py",
            "publisher": "pub.py:Foo",
        }.items():
            raw = {
                **base,
                "contributes": {"theme": "theme.json", contribution: spec},
            }
            with pytest.raises(ManifestError, match=contribution):
                validate_manifest(raw, "/path")

    def test_theme_with_static_allowed(self):
        raw = {
            "id": "test.goodtheme",
            "name": "Good Theme",
            "description": "d",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "theme",
            "contributes": {"theme": "theme.json", "static": "static/"},
        }
        info = validate_manifest(raw, "/path")
        assert "static" in info.contributes


class TestThemePathTraversal:
    """Theme contributes['theme'] must not allow path traversal."""

    def test_traversal_blocked_on_load(self, tmp_path):
        """A theme with '../' in contributes.theme must be rejected by the sanitizer."""
        mod_dir = tmp_path / "eviltheme"
        mod_dir.mkdir()
        # Place a valid JSON file at the traversal target to prove the
        # sanitizer blocks it -- without the fix, this would load.
        escape_target = tmp_path / "stolen.json"
        escape_target.write_text(json.dumps(_VALID_THEME))
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "test.eviltheme",
            "name": "Evil Theme",
            "description": "desc",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "theme",
            "contributes": {"theme": "../stolen.json"},
        }))

        app = Flask(__name__)
        app.config["TESTING"] = True
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()

        mod = next(m for m in loader.get_modules() if m.id == "test.eviltheme")
        assert mod.error is not None
        assert "unsafe manifest reference" in mod.error.lower()
        assert mod.theme_data is None

    def test_slash_in_filename_blocked(self, tmp_path):
        """A theme filename containing slashes must be rejected by the sanitizer."""
        mod_dir = tmp_path / "slashtheme"
        mod_dir.mkdir()
        sub = mod_dir / "subdir"
        sub.mkdir()
        (sub / "theme.json").write_text(json.dumps(_VALID_THEME))
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "test.slashtheme",
            "name": "Slash Theme",
            "description": "desc",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "theme",
            "contributes": {"theme": "subdir/theme.json"},
        }))

        app = Flask(__name__)
        app.config["TESTING"] = True
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()

        mod = next(m for m in loader.get_modules() if m.id == "test.slashtheme")
        assert mod.error is not None
        assert "unsafe manifest reference" in mod.error.lower()

    def test_valid_theme_filename_works(self, tmp_path):
        """A well-formed theme filename still loads correctly."""
        mod_dir = tmp_path / "goodtheme"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "test.goodtheme",
            "name": "Good Theme",
            "description": "desc",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "theme",
            "contributes": {"theme": "my-theme.json"},
        }))
        (mod_dir / "my-theme.json").write_text(json.dumps(_VALID_THEME))

        app = Flask(__name__)
        app.config["TESTING"] = True
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()

        mod = next(m for m in loader.get_modules() if m.id == "test.goodtheme")
        assert mod.theme_data is not None
        assert "--bg" in mod.theme_data["dark"]

    def test_disabled_theme_traversal_blocked(self, tmp_path):
        """Disabled themes with traversal in contributes.theme must also be blocked."""
        mod_dir = tmp_path / "disabledevil"
        mod_dir.mkdir()
        # Place a valid theme file at the traversal target so the old
        # unsanitized code would successfully load it.
        escape_target = tmp_path / "stolen_theme.json"
        escape_target.write_text(json.dumps(_VALID_THEME))
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "test.disabledevil",
            "name": "Disabled Evil",
            "description": "desc",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "theme",
            "contributes": {"theme": "../stolen_theme.json"},
        }))

        app = Flask(__name__)
        app.config["TESTING"] = True
        loader = ModuleLoader(
            app,
            search_paths=[str(tmp_path)],
            disabled_ids={"test.disabledevil"},
        )
        loader.load_all()

        mod = next(m for m in loader.get_modules() if m.id == "test.disabledevil")
        assert mod.theme_data is None


class TestContributesPathTraversal:
    """All contributes-based file references must reject traversal."""

    def test_collector_traversal_blocked(self, tmp_path):
        """Collector spec with traversal filename must be rejected."""
        from app.module_loader import load_module_collector

        evil_file = tmp_path / "evil.py"
        evil_file.write_text("class Evil: pass")

        mod_dir = tmp_path / "mymod"
        mod_dir.mkdir()

        with pytest.raises(ValueError, match="Unsafe manifest reference"):
            load_module_collector("test.mod", str(mod_dir), "../evil.py:Evil")

    def test_routes_traversal_blocked(self, tmp_path):
        """Routes file with traversal must be rejected."""
        from app.module_loader import load_module_routes
        from flask import Flask

        evil_file = tmp_path / "evil_routes.py"
        evil_file.write_text("EXECUTED = True")

        mod_dir = tmp_path / "mymod"
        mod_dir.mkdir()

        app = Flask(__name__)
        with pytest.raises(ValueError, match="Unsafe manifest reference"):
            load_module_routes(app, "test.mod", str(mod_dir), "../evil_routes.py")

    def test_thresholds_traversal_blocked(self, tmp_path):
        """Thresholds with traversal filename must fail to load."""
        from app.module_loader import ModuleLoader

        stolen = tmp_path / "stolen.json"
        stolen.write_text(json.dumps({
            "downstream_power": {"_default": [0, 10]},
            "upstream_power": {"_default": [35, 55]},
            "snr": {"_default": [30, 100]},
        }))
        mod_dir = tmp_path / "evilmod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "test.evilmod",
            "name": "Evil",
            "description": "d",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "analysis",
            "contributes": {"thresholds": "../stolen.json"},
        }))

        app = Flask(__name__)
        app.config["TESTING"] = True
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()

        mod = next(m for m in loader.get_modules() if m.id == "test.evilmod")
        assert mod.error is not None
        assert "unsafe manifest reference" in mod.error.lower()

    def test_i18n_traversal_blocked(self, tmp_path):
        """i18n with traversal must be rejected."""
        mod_dir = tmp_path / "i18nmod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "test.i18nmod",
            "name": "i18n Evil",
            "description": "d",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "integration",
            "contributes": {"i18n": "../../etc"},
        }))

        app = Flask(__name__)
        app.config["TESTING"] = True
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()

        mod = next(m for m in loader.get_modules() if m.id == "test.i18nmod")
        assert mod.error is not None
        assert "unsafe manifest subpath" in mod.error.lower()

    def test_publisher_traversal_blocked(self, tmp_path):
        """Publisher spec with traversal filename must be rejected."""
        from app.module_loader import load_module_publisher

        mod_dir = tmp_path / "mymod"
        mod_dir.mkdir()

        with pytest.raises(ValueError, match="Unsafe manifest reference"):
            load_module_publisher("test.mod", str(mod_dir), "../evil.py:Evil")

    def test_driver_traversal_blocked(self, tmp_path):
        """Driver spec with traversal filename must be rejected."""
        from app.module_loader import load_module_driver

        mod_dir = tmp_path / "mymod"
        mod_dir.mkdir()

        with pytest.raises(ValueError, match="Unsafe manifest reference"):
            load_module_driver("test.mod", str(mod_dir), "../evil.py:Evil")

    def test_static_traversal_blocked(self, tmp_path):
        """Static dir with traversal must be rejected."""
        mod_dir = tmp_path / "staticmod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "test.staticmod",
            "name": "Static Evil",
            "description": "d",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "integration",
            "contributes": {"static": "../../../var/www", "routes": "routes.py"},
        }))
        (mod_dir / "routes.py").write_text("")

        app = Flask(__name__)
        app.config["TESTING"] = True
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()

        mod = next(m for m in loader.get_modules() if m.id == "test.staticmod")
        assert mod.error is not None
        assert "unsafe manifest subpath" in mod.error.lower()


def test_driver_in_valid_contributes():
    from app.module_loader import VALID_CONTRIBUTES
    assert "driver" in VALID_CONTRIBUTES


class TestLoadModuleDriver:
    """Tests for load_module_driver()."""

    def test_valid_driver_spec(self, tmp_path):
        driver_code = textwrap.dedent('''
            from app.drivers.base import ModemDriver

            class TestDriver(ModemDriver):
                def login(self): pass
                def get_docsis_data(self): return {}
                def get_device_info(self): return {}
                def get_connection_info(self): return {}
        ''')
        driver_file = tmp_path / "driver.py"
        driver_file.write_text(driver_code)
        cls = load_module_driver("test.mod", str(tmp_path), "driver.py:TestDriver")
        assert cls is not None
        assert cls.__name__ == "TestDriver"

    def test_missing_colon_returns_none(self, tmp_path):
        cls = load_module_driver("test.mod", str(tmp_path), "driver.py")
        assert cls is None

    def test_missing_file_returns_none(self, tmp_path):
        cls = load_module_driver("test.mod", str(tmp_path), "missing.py:Foo")
        assert cls is None

    def test_missing_class_returns_none(self, tmp_path):
        driver_file = tmp_path / "driver.py"
        driver_file.write_text("class Other: pass")
        cls = load_module_driver("test.mod", str(tmp_path), "driver.py:Missing")
        assert cls is None


class TestDriverModuleSecurity:
    def test_driver_module_forbidden_contributions_rejected(self):
        base = {
            "id": "community.mydriver",
            "name": "My Driver",
            "description": "A driver",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "driver",
        }

        for contribution, spec in {
            "collector": "collector.py:Foo",
            "publisher": "pub.py:Foo",
        }.items():
            raw = {
                **base,
                "contributes": {"driver": "driver.py:MyDriver", contribution: spec},
            }
            with pytest.raises(ManifestError, match="must not contribute"):
                validate_manifest(raw, "/path")

    def test_driver_module_with_only_driver_is_valid(self):
        raw = {
            "id": "community.mydriver",
            "name": "My Driver",
            "description": "A driver",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "driver",
            "contributes": {"driver": "driver.py:MyDriver"},
        }
        info = validate_manifest(raw, "/path")
        assert info.type == "driver"
