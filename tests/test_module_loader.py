# tests/test_module_loader.py
import importlib
import json
import os
import tempfile

import pytest
from flask import Flask
from app.module_loader import ModuleInfo, validate_manifest, ManifestError, discover_modules, register_module_config, merge_module_i18n, load_module_routes, load_module_collector, setup_module_static, setup_module_templates, ModuleLoader


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


class TestMergeModuleI18n:
    """Test module i18n merging into global translations."""

    def test_merge_translations(self):
        with tempfile.TemporaryDirectory() as d:
            i18n_dir = os.path.join(d, "i18n")
            os.makedirs(i18n_dir)
            with open(os.path.join(i18n_dir, "en.json"), "w") as f:
                json.dump({"greeting": "Hello from module"}, f)
            with open(os.path.join(i18n_dir, "de.json"), "w") as f:
                json.dump({"greeting": "Hallo vom Modul"}, f)

            merge_module_i18n("test.mymod", i18n_dir)

            from app.i18n import get_translations
            en = get_translations("en")
            de = get_translations("de")
            assert en.get("test.mymod.greeting") == "Hello from module"
            assert de.get("test.mymod.greeting") == "Hallo vom Modul"

    def test_missing_i18n_dir_skipped(self):
        """Non-existent i18n directory is silently skipped."""
        merge_module_i18n("test.missing", "/nonexistent/i18n")
        # Should not raise


class TestLoadModuleRoutes:
    """Test dynamic Blueprint loading from module routes.py."""

    def _make_routes_file(self, mod_dir, content):
        """Write a routes.py file."""
        with open(os.path.join(mod_dir, "routes.py"), "w") as f:
            f.write(content)

    def test_load_blueprint_from_routes(self):
        """Load a Blueprint from a module's routes.py."""
        app = Flask(__name__)
        with tempfile.TemporaryDirectory() as d:
            mod_dir = os.path.join(d, "testmod")
            os.makedirs(mod_dir)
            self._make_routes_file(mod_dir, """
from flask import Blueprint, jsonify
bp = Blueprint("testmod_bp", __name__)

@bp.route("/api/modules/test.mod/hello")
def hello():
    return jsonify({"msg": "hello"})
""")
            load_module_routes(app, "test.mod", mod_dir, "routes.py")
            with app.test_client() as c:
                resp = c.get("/api/modules/test.mod/hello")
                assert resp.status_code == 200
                assert resp.get_json()["msg"] == "hello"

    def test_missing_routes_file_skipped(self):
        """Non-existent routes.py is gracefully handled."""
        app = Flask(__name__)
        # Should not raise
        load_module_routes(app, "test.missing", "/nonexistent", "routes.py")

    def test_routes_file_without_blueprint_logged(self):
        """routes.py that doesn't export bp/blueprint is warned."""
        app = Flask(__name__)
        with tempfile.TemporaryDirectory() as d:
            mod_dir = os.path.join(d, "nomod")
            os.makedirs(mod_dir)
            self._make_routes_file(mod_dir, "x = 42\n")
            # Should not raise, just log warning
            load_module_routes(app, "test.nobp", mod_dir, "routes.py")


class TestLoadModuleCollector:
    """Test dynamic Collector class loading."""

    def _make_collector_file(self, mod_dir, content):
        with open(os.path.join(mod_dir, "collector.py"), "w") as f:
            f.write(content)

    def test_load_collector_class(self):
        """Load a Collector subclass from module file."""
        with tempfile.TemporaryDirectory() as d:
            mod_dir = os.path.join(d, "testmod")
            os.makedirs(mod_dir)
            self._make_collector_file(mod_dir, """
from app.collectors.base import Collector, CollectorResult

class TestCollector(Collector):
    name = "test_collector"
    def collect(self):
        return CollectorResult.ok("test", {})
""")
            cls = load_module_collector("test.mod", mod_dir, "collector.py:TestCollector")
            assert cls is not None
            assert cls.name == "test_collector"

    def test_invalid_spec_format(self):
        """Spec without ':ClassName' returns None."""
        cls = load_module_collector("test.bad", "/tmp", "collector.py")
        assert cls is None

    def test_missing_file(self):
        """Missing collector file returns None."""
        cls = load_module_collector("test.miss", "/nonexistent", "collector.py:Foo")
        assert cls is None


class TestStaticAndTemplates:
    """Test static file serving and template path registration."""

    def test_static_route_registered(self):
        """Module static dir is served at /modules/<id>/static/."""
        app = Flask(__name__)
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as d:
            mod_dir = os.path.join(d, "testmod")
            static_dir = os.path.join(mod_dir, "static")
            os.makedirs(static_dir)
            with open(os.path.join(static_dir, "test.js"), "w") as f:
                f.write("console.log('hello');")

            setup_module_static(app, "test.mod", mod_dir, "static/")

            with app.test_client() as c:
                resp = c.get("/modules/test.mod/static/test.js")
                assert resp.status_code == 200
                assert b"console.log" in resp.data
                resp.close()

    def test_template_paths_collected(self):
        """Module template paths are resolved to absolute paths."""
        with tempfile.TemporaryDirectory() as d:
            mod_dir = os.path.join(d, "testmod")
            tpl_dir = os.path.join(mod_dir, "templates")
            os.makedirs(tpl_dir)
            with open(os.path.join(tpl_dir, "tab.html"), "w") as f:
                f.write("<div>Tab</div>")

            paths = setup_module_templates("test.mod", mod_dir, {"tab": "templates/tab.html"})
            assert "tab" in paths
            assert paths["tab"].endswith("tab.html")
            assert os.path.isfile(paths["tab"])

    def test_missing_template_excluded(self):
        """Template paths that don't exist are not included."""
        with tempfile.TemporaryDirectory() as d:
            mod_dir = os.path.join(d, "testmod")
            os.makedirs(mod_dir)
            paths = setup_module_templates("test.mod", mod_dir, {"tab": "templates/tab.html"})
            assert "tab" not in paths


class TestModuleLoader:
    """Test the orchestrator that ties discovery + loading together."""

    def _make_full_module(self, base_dir, mod_id, name="Test Module"):
        """Create a module with manifest, routes, i18n."""
        folder = mod_id.split(".")[-1]
        mod_dir = os.path.join(base_dir, folder)
        os.makedirs(os.path.join(mod_dir, "i18n"), exist_ok=True)

        manifest = {
            "id": mod_id,
            "name": name,
            "description": "Test",
            "version": "1.0.0",
            "author": "Test",
            "minAppVersion": "2026.2",
            "type": "integration",
            "contributes": {
                "routes": "routes.py",
                "i18n": "i18n/",
            },
            "config": {f"{folder}_enabled": False},
            "menu": {"label_key": f"{mod_id}.name", "icon": "test", "order": 99},
        }
        with open(os.path.join(mod_dir, "manifest.json"), "w") as f:
            json.dump(manifest, f)

        with open(os.path.join(mod_dir, "routes.py"), "w") as f:
            safe = mod_id.replace(".", "_")
            f.write(f'''
from flask import Blueprint, jsonify
bp = Blueprint("{safe}_bp", __name__)

@bp.route("/api/modules/{mod_id}/status")
def status():
    return jsonify({{"module": "{mod_id}", "ok": True}})
''')

        with open(os.path.join(mod_dir, "i18n", "en.json"), "w") as f:
            json.dump({"name": name}, f)

        return mod_dir

    def test_load_modules_end_to_end(self):
        """Full load: discover -> validate -> register config + i18n + routes."""
        app = Flask(__name__)
        with tempfile.TemporaryDirectory() as d:
            self._make_full_module(d, "test.alpha", "Alpha")
            self._make_full_module(d, "test.beta", "Beta")

            loader = ModuleLoader(app, search_paths=[d])
            loaded = loader.load_all()

            assert len(loaded) == 2
            ids = {m.id for m in loaded}
            assert ids == {"test.alpha", "test.beta"}

            # Routes work
            with app.test_client() as c:
                r = c.get("/api/modules/test.alpha/status")
                assert r.status_code == 200
                assert r.get_json()["module"] == "test.alpha"

            # i18n merged
            from app.i18n import get_translations
            en = get_translations("en")
            assert en.get("test.alpha.name") == "Alpha"

    def test_disabled_modules_not_loaded(self):
        """Disabled modules are discovered but not loaded."""
        app = Flask(__name__)
        with tempfile.TemporaryDirectory() as d:
            self._make_full_module(d, "test.disabled")

            loader = ModuleLoader(app, search_paths=[d], disabled_ids={"test.disabled"})
            loaded = loader.load_all()

            assert len(loaded) == 1
            assert loaded[0].enabled is False

            # Routes should NOT be registered
            with app.test_client() as c:
                r = c.get("/api/modules/test.disabled/status")
                assert r.status_code == 404

    def test_get_modules_returns_all(self):
        """get_modules() returns all discovered modules including disabled."""
        app = Flask(__name__)
        with tempfile.TemporaryDirectory() as d:
            self._make_full_module(d, "test.one")
            self._make_full_module(d, "test.two")

            loader = ModuleLoader(app, search_paths=[d], disabled_ids={"test.two"})
            loader.load_all()

            all_mods = loader.get_modules()
            assert len(all_mods) == 2
            enabled = [m for m in all_mods if m.enabled]
            assert len(enabled) == 1
