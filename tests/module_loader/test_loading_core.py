"""Tests for core module loading helpers and asset wiring."""

# tests/test_module_loader.py
import importlib
import json
import os
import tempfile
import textwrap
from types import SimpleNamespace

import pytest
from flask import Flask
from app.module_loader import ModuleInfo, validate_manifest, ManifestError, discover_modules, register_module_config, merge_module_i18n, load_module_routes, load_module_collector, load_module_publisher, load_module_driver, setup_module_static, setup_module_templates, ModuleLoader

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

    def test_module_config_defaults_do_not_become_secret_keys(self, tmp_path):
        """Module config defaults stay plain config unless they use existing core secret keys."""
        from app import config as cfg
        from app.config import ConfigManager, PASSWORD_MASK

        original_defaults = dict(cfg.DEFAULTS)
        original_secrets = set(cfg.SECRET_KEYS)
        try:
            registered = register_module_config(
                {"community_api_token": "", "community_enabled": False},
                module_id="community.weather",
            )
            assert registered == {"community_api_token", "community_enabled"}
            assert "community_api_token" in cfg.DEFAULTS
            assert "community_api_token" not in cfg.SECRET_KEYS

            mgr = ConfigManager(str(tmp_path / "data"))
            mgr.save({"community_api_token": "token-value"})
            raw = json.loads((tmp_path / "data" / "config.json").read_text())

            assert raw["community_api_token"] == "token-value"
            assert mgr.get_all(mask_secrets=True)["community_api_token"] != PASSWORD_MASK
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)
            cfg.SECRET_KEYS.clear()
            cfg.SECRET_KEYS.update(original_secrets)

    def test_community_collector_proxy_hides_core_secrets(self, tmp_path):
        """Community collectors may read plain module config but not core secrets."""
        from app import config as cfg
        from app.collectors import discover_collectors
        from app.config import ConfigManager

        original_defaults = dict(cfg.DEFAULTS)
        try:
            register_module_config(
                {"community_api_token": "", "modem_password": ""},
                module_id="community.test",
            )
            mgr = ConfigManager(str(tmp_path / "data"))
            mgr.save({
                "modem_password": "core-secret",
                "community_api_token": "plain-module-value",
            })
            captured = {}

            class CommunityCollector:
                name = "community"

                def __init__(self, config_mgr, storage, web):
                    captured["config_mgr"] = config_mgr

            mod = ModuleInfo(
                id="community.test",
                name="Community Test",
                description="Test module",
                version="1.0.0",
                author="Test",
                min_app_version="2026.2",
                type="integration",
                contributes={"collector": "collector.py:CommunityCollector"},
                path="/modules/community-test",
                builtin=False,
                config={"community_api_token": "", "modem_password": ""},
                collector_class=CommunityCollector,
            )
            web = SimpleNamespace(
                get_module_loader=lambda: SimpleNamespace(get_enabled_modules=lambda: [mod])
            )

            discover_collectors(mgr, None, None, None, web, None)

            proxy = captured["config_mgr"]
            assert proxy.get("community_api_token") == "plain-module-value"
            assert proxy.get("modem_password", "blocked") == "blocked"
            assert "modem_password" not in proxy.get_all()
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)

    def test_builtin_can_register_reserved_core_secret_default(self):
        """Built-in modules may still provide defaults for static core secrets."""
        from app import config as cfg

        original_defaults = dict(cfg.DEFAULTS)
        original_secrets = set(cfg.SECRET_KEYS)
        try:
            cfg.DEFAULTS.pop("mqtt_password", None)

            registered = register_module_config(
                {"mqtt_password": ""},
                module_id="docsight.mqtt",
                builtin=True,
            )

            assert registered == {"mqtt_password"}
            assert "mqtt_password" in cfg.DEFAULTS
            assert "mqtt_password" in cfg.SECRET_KEYS
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)
            cfg.SECRET_KEYS.clear()
            cfg.SECRET_KEYS.update(original_secrets)

    @pytest.mark.parametrize("reserved_key", ["admin_password", "mqtt_password", "speedtest_tracker_token"])
    def test_community_module_cannot_register_reserved_secret_defaults(self, reserved_key, caplog):
        """Community modules cannot turn core secret or hash-backed keys into module config."""
        from app import config as cfg

        original_defaults = dict(cfg.DEFAULTS)
        original_secrets = set(cfg.SECRET_KEYS)
        try:
            cfg.DEFAULTS.pop(reserved_key, None)

            with caplog.at_level("WARNING", logger="docsis.modules"):
                registered = register_module_config(
                    {reserved_key: ""},
                    module_id="community.claimant",
                )

            assert registered == set()
            assert reserved_key not in cfg.DEFAULTS
            assert reserved_key not in caplog.text
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)
            cfg.SECRET_KEYS.clear()
            cfg.SECRET_KEYS.update(original_secrets)


class TestMergeModuleI18n:
    """Test module i18n merging into global translations."""

    def test_merge_translations(self):
        with tempfile.TemporaryDirectory() as d:
            i18n_dir = os.path.join(d, "i18n")
            os.makedirs(i18n_dir)
            with open(os.path.join(i18n_dir, "en.json"), "w") as f:
                json.dump({"greeting": "Hello from module", "fallback_only": "Fallback"}, f)
            with open(os.path.join(i18n_dir, "de.json"), "w") as f:
                json.dump({"greeting": "Hallo vom Modul"}, f)

            merge_module_i18n("test.mymod", i18n_dir)

            from app.i18n import get_translations
            en = get_translations("en")
            de = get_translations("de")
            assert en.get("test.mymod.greeting") == "Hello from module"
            assert de.get("test.mymod.greeting") == "Hallo vom Modul"
            assert de.get("test.mymod.fallback_only") == "Fallback"

    def test_merge_english_only_translations_into_existing_languages(self):
        with tempfile.TemporaryDirectory() as d:
            i18n_dir = os.path.join(d, "i18n")
            os.makedirs(i18n_dir)
            with open(os.path.join(i18n_dir, "en.json"), "w") as f:
                json.dump({"title": "English module title"}, f)

            merge_module_i18n("test.english_only", i18n_dir)

            from app.i18n import get_translations
            assert get_translations("en").get("test.english_only.title") == "English module title"
            assert get_translations("de").get("test.english_only.title") == "English module title"

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


class TestLoadModulePublisher:
    """Test dynamic Publisher class loading."""

    def _make_publisher_file(self, mod_dir, content):
        with open(os.path.join(mod_dir, "publisher.py"), "w") as f:
            f.write(content)

    def test_load_publisher_class(self):
        """Load a Publisher class from module file."""
        with tempfile.TemporaryDirectory() as d:
            mod_dir = os.path.join(d, "testmod")
            os.makedirs(mod_dir)
            self._make_publisher_file(mod_dir, """
class TestPublisher:
    name = "test_publisher"
    def publish(self, data):
        pass
""")
            cls = load_module_publisher("test.mod", mod_dir, "publisher.py:TestPublisher")
            assert cls is not None
            assert cls.name == "test_publisher"

    def test_invalid_spec_format(self):
        """Spec without ':ClassName' returns None."""
        cls = load_module_publisher("test.bad", "/tmp", "publisher.py")
        assert cls is None

    def test_missing_file(self):
        """Missing publisher file returns None."""
        cls = load_module_publisher("test.miss", "/nonexistent", "publisher.py:Foo")
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
            assert paths["tab"] == "tab.html"

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


class TestModuleAssetDetection:
    """Test convention-based CSS/JS detection."""

    def test_has_css_when_style_exists(self, tmp_path):
        """Module with static/style.css gets has_css=True."""
        mod_dir = tmp_path / "mymod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "docsight.css_test", "name": "CSS Test", "description": "d",
            "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
            "type": "integration", "contributes": {"static": "static/"},
        }))
        static = mod_dir / "static"
        static.mkdir()
        (static / "style.css").write_text("body { }")

        app = Flask(__name__)
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()
        mod = loader.get_enabled_modules()[0]
        assert mod.has_css is True
        assert mod.has_js is False

    def test_has_js_when_main_exists(self, tmp_path):
        """Module with static/main.js gets has_js=True."""
        mod_dir = tmp_path / "mymod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "docsight.js_test", "name": "JS Test", "description": "d",
            "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
            "type": "integration", "contributes": {"static": "static/"},
        }))
        static = mod_dir / "static"
        static.mkdir()
        (static / "main.js").write_text("console.log('hi')")

        app = Flask(__name__)
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()
        mod = loader.get_enabled_modules()[0]
        assert mod.has_css is False
        assert mod.has_js is True

    def test_no_assets_when_no_static(self, tmp_path):
        """Module without static dir has both False."""
        mod_dir = tmp_path / "mymod"
        mod_dir.mkdir()
        (mod_dir / "manifest.json").write_text(json.dumps({
            "id": "docsight.no_assets", "name": "No Assets", "description": "d",
            "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
            "type": "integration", "contributes": {},
        }))

        app = Flask(__name__)
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()
        mod = loader.get_enabled_modules()[0]
        assert mod.has_css is False
        assert mod.has_js is False


_VALID_THRESHOLDS = {
    "downstream_power": {"_default": "256QAM", "256QAM": {"good": [-4, 13], "warning": [-6, 18], "critical": [-8, 20]}},
    "upstream_power": {"_default": "sc_qam", "sc_qam": {"good": [41, 47], "warning": [37, 51], "critical": [35, 53]}},
    "snr": {"_default": "256QAM", "256QAM": {"good_min": 33, "warning_min": 31, "critical_min": 30}},
}

