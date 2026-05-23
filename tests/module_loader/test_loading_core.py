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
from app.module_loader import ModuleInfo, validate_manifest, ManifestError, discover_modules, register_module_config, reserve_module_config_secrets, merge_module_i18n, load_module_routes, load_module_collector, load_module_publisher, load_module_driver, setup_module_static, setup_module_templates, ModuleLoader

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

    def test_register_config_secrets_encrypts_masks_and_preserves_masks(self, tmp_path):
        """Module-owned config_secrets join the global secret storage path."""
        from app import config as cfg
        from app.config import ConfigManager, PASSWORD_MASK

        original_defaults = dict(cfg.DEFAULTS)
        original_secrets = set(cfg.SECRET_KEYS)
        original_module_secrets = set(cfg.MODULE_SECRET_KEYS)
        original_module_secret_owners = dict(cfg.MODULE_SECRET_OWNERS)
        try:
            register_module_config(
                {"community_api_token": "", "community_enabled": False},
                config_secrets={"community_api_token"},
                module_id="community.weather",
            )
            assert "community_api_token" in cfg.DEFAULTS
            assert "community_api_token" in cfg.SECRET_KEYS
            assert cfg.MODULE_SECRET_OWNERS["community_api_token"] == "community.weather"

            mgr = ConfigManager(str(tmp_path / "data"))
            mgr.save({"community_api_token": "token-secret"})
            raw = json.loads((tmp_path / "data" / "config.json").read_text())

            assert raw["community_api_token"] != "token-secret"
            assert mgr.get("community_api_token") == "token-secret"
            assert mgr.get_all(mask_secrets=True)["community_api_token"] == PASSWORD_MASK

            mgr.save({"community_api_token": PASSWORD_MASK})
            assert mgr.get("community_api_token") == "token-secret"
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)
            cfg.SECRET_KEYS.clear()
            cfg.SECRET_KEYS.update(original_secrets)
            cfg.MODULE_SECRET_KEYS.clear()
            cfg.MODULE_SECRET_KEYS.update(original_module_secrets)
            cfg.MODULE_SECRET_OWNERS.clear()
            cfg.MODULE_SECRET_OWNERS.update(original_module_secret_owners)

    def test_community_collector_proxy_only_allows_declared_module_secrets(self, tmp_path):
        """Community collectors may read their own secrets but not core secrets."""
        from app import config as cfg
        from app.collectors import discover_collectors
        from app.config import ConfigManager

        original_defaults = dict(cfg.DEFAULTS)
        original_secrets = set(cfg.SECRET_KEYS)
        original_module_secrets = set(cfg.MODULE_SECRET_KEYS)
        original_module_secret_owners = dict(cfg.MODULE_SECRET_OWNERS)
        try:
            register_module_config(
                {"community_api_token": "", "modem_password": ""},
                config_secrets={"community_api_token"},
                module_id="community.test",
            )
            mgr = ConfigManager(str(tmp_path / "data"))
            mgr.save({
                "modem_password": "core-secret",
                "community_api_token": "module-secret",
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
                config_secrets={"community_api_token"},
                collector_class=CommunityCollector,
            )
            web = SimpleNamespace(
                get_module_loader=lambda: SimpleNamespace(get_enabled_modules=lambda: [mod])
            )

            discover_collectors(mgr, None, None, None, web, None)

            proxy = captured["config_mgr"]
            assert proxy.get("community_api_token") == "module-secret"
            assert proxy.get("modem_password", "blocked") == "blocked"
            assert "modem_password" not in proxy.get_all()
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)
            cfg.SECRET_KEYS.clear()
            cfg.SECRET_KEYS.update(original_secrets)
            cfg.MODULE_SECRET_KEYS.clear()
            cfg.MODULE_SECRET_KEYS.update(original_module_secrets)
            cfg.MODULE_SECRET_OWNERS.clear()
            cfg.MODULE_SECRET_OWNERS.update(original_module_secret_owners)

    def test_same_module_secret_reload_preserves_ownership(self):
        """Reloading the same module may reuse its already-owned secret key."""
        from app import config as cfg

        original_defaults = dict(cfg.DEFAULTS)
        original_secrets = set(cfg.SECRET_KEYS)
        original_module_secrets = set(cfg.MODULE_SECRET_KEYS)
        original_module_secret_owners = dict(cfg.MODULE_SECRET_OWNERS)
        try:
            first = register_module_config(
                {"community_reload_token": ""},
                config_secrets={"community_reload_token"},
                module_id="community.reload",
            )
            second = register_module_config(
                {"community_reload_token": ""},
                config_secrets={"community_reload_token"},
                module_id="community.reload",
            )

            assert first == {"community_reload_token"}
            assert second == {"community_reload_token"}
            assert cfg.MODULE_SECRET_OWNERS["community_reload_token"] == "community.reload"
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)
            cfg.SECRET_KEYS.clear()
            cfg.SECRET_KEYS.update(original_secrets)
            cfg.MODULE_SECRET_KEYS.clear()
            cfg.MODULE_SECRET_KEYS.update(original_module_secrets)
            cfg.MODULE_SECRET_OWNERS.clear()
            cfg.MODULE_SECRET_OWNERS.update(original_module_secret_owners)

    def test_other_module_cannot_claim_existing_module_secret(self, tmp_path):
        """A community module cannot read another module's colliding secret key."""
        from app import config as cfg
        from app.collectors import discover_collectors
        from app.config import ConfigManager

        original_defaults = dict(cfg.DEFAULTS)
        original_secrets = set(cfg.SECRET_KEYS)
        original_module_secrets = set(cfg.MODULE_SECRET_KEYS)
        original_module_secret_owners = dict(cfg.MODULE_SECRET_OWNERS)
        try:
            first = register_module_config(
                {"community_shared_token": ""},
                config_secrets={"community_shared_token"},
                module_id="community.first",
            )
            second = register_module_config(
                {"community_shared_token": ""},
                config_secrets={"community_shared_token"},
                module_id="community.second",
            )
            assert first == {"community_shared_token"}
            assert second == set()
            assert cfg.MODULE_SECRET_OWNERS["community_shared_token"] == "community.first"

            mgr = ConfigManager(str(tmp_path / "data"))
            mgr.save({"community_shared_token": "first-module-secret"})
            captured = {}

            class SecondCommunityCollector:
                name = "community-second"

                def __init__(self, config_mgr, storage, web):
                    captured["config_mgr"] = config_mgr

            mod = ModuleInfo(
                id="community.second",
                name="Community Second",
                description="Test module",
                version="1.0.0",
                author="Test",
                min_app_version="2026.2",
                type="integration",
                contributes={"collector": "collector.py:SecondCommunityCollector"},
                path="/modules/community-second",
                builtin=False,
                config={"community_shared_token": ""},
                config_secrets=second,
                collector_class=SecondCommunityCollector,
            )
            web = SimpleNamespace(
                get_module_loader=lambda: SimpleNamespace(get_enabled_modules=lambda: [mod])
            )

            discover_collectors(mgr, None, None, None, web, None)

            proxy = captured["config_mgr"]
            assert proxy.get("community_shared_token", "blocked") == "blocked"
            assert "community_shared_token" not in proxy.get_all()
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)
            cfg.SECRET_KEYS.clear()
            cfg.SECRET_KEYS.update(original_secrets)
            cfg.MODULE_SECRET_KEYS.clear()
            cfg.MODULE_SECRET_KEYS.update(original_module_secrets)
            cfg.MODULE_SECRET_OWNERS.clear()
            cfg.MODULE_SECRET_OWNERS.update(original_module_secret_owners)

    def test_declared_secret_duplicate_is_reserved_fail_closed_before_load(self, tmp_path):
        """Duplicate config_secrets cannot be won by whichever module loads first."""
        from app import config as cfg
        from app.collectors import discover_collectors
        from app.config import ConfigManager

        original_defaults = dict(cfg.DEFAULTS)
        original_secrets = set(cfg.SECRET_KEYS)
        original_module_secrets = set(cfg.MODULE_SECRET_KEYS)
        original_module_secret_owners = dict(cfg.MODULE_SECRET_OWNERS)
        try:
            shared_key = "community_duplicate_token"
            victim = ModuleInfo(
                id="community.victim",
                name="Community Victim",
                description="Victim module",
                version="1.0.0",
                author="Test",
                min_app_version="2026.2",
                type="integration",
                contributes={},
                path="/modules/community-victim",
                builtin=False,
                enabled=False,
                config={shared_key: ""},
                config_secrets={shared_key},
            )
            claimant = ModuleInfo(
                id="community.claimant",
                name="Community Claimant",
                description="Claimant module",
                version="1.0.0",
                author="Test",
                min_app_version="2026.2",
                type="integration",
                contributes={"collector": "collector.py:ClaimantCollector"},
                path="/modules/community-claimant",
                builtin=False,
                config={shared_key: ""},
                config_secrets={shared_key},
            )
            reserve_module_config_secrets([victim, claimant])

            claimant.config_secrets = register_module_config(
                claimant.config,
                config_secrets=claimant.config_secrets,
                module_id=claimant.id,
            )
            victim_registered = register_module_config(
                victim.config,
                config_secrets=victim.config_secrets,
                module_id=victim.id,
            )

            assert claimant.config_secrets == set()
            assert victim_registered == set()
            assert shared_key in cfg.SECRET_KEYS
            assert shared_key in cfg.MODULE_SECRET_KEYS

            mgr = ConfigManager(str(tmp_path / "data"))
            mgr.save({shared_key: "victim-secret"})
            captured = {}

            class ClaimantCollector:
                name = "community-claimant"

                def __init__(self, config_mgr, storage, web):
                    captured["config_mgr"] = config_mgr

            claimant.collector_class = ClaimantCollector
            web = SimpleNamespace(
                get_module_loader=lambda: SimpleNamespace(get_enabled_modules=lambda: [claimant])
            )

            discover_collectors(mgr, None, None, None, web, None)

            proxy = captured["config_mgr"]
            assert proxy.get(shared_key, "blocked") == "blocked"
            assert shared_key not in proxy.get_all()
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)
            cfg.SECRET_KEYS.clear()
            cfg.SECRET_KEYS.update(original_secrets)
            cfg.MODULE_SECRET_KEYS.clear()
            cfg.MODULE_SECRET_KEYS.update(original_module_secrets)
            cfg.MODULE_SECRET_OWNERS.clear()
            cfg.MODULE_SECRET_OWNERS.update(original_module_secret_owners)

    def test_builtin_can_register_reserved_core_secret_default(self):
        """Built-in modules may still provide defaults for static core secrets."""
        from app import config as cfg

        original_defaults = dict(cfg.DEFAULTS)
        original_secrets = set(cfg.SECRET_KEYS)
        original_module_secrets = set(cfg.MODULE_SECRET_KEYS)
        original_module_secret_owners = dict(cfg.MODULE_SECRET_OWNERS)
        try:
            cfg.DEFAULTS.pop("mqtt_password", None)

            registered = register_module_config(
                {"mqtt_password": ""},
                module_id="docsight.mqtt",
                builtin=True,
            )

            assert registered == set()
            assert "mqtt_password" in cfg.DEFAULTS
            assert "mqtt_password" in cfg.SECRET_KEYS
            assert "mqtt_password" not in cfg.MODULE_SECRET_KEYS
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)
            cfg.SECRET_KEYS.clear()
            cfg.SECRET_KEYS.update(original_secrets)
            cfg.MODULE_SECRET_KEYS.clear()
            cfg.MODULE_SECRET_KEYS.update(original_module_secrets)
            cfg.MODULE_SECRET_OWNERS.clear()
            cfg.MODULE_SECRET_OWNERS.update(original_module_secret_owners)

    def test_core_hash_key_without_registered_default_is_not_module_owned(self):
        """Modules cannot claim reserved hash-backed credentials either."""
        from app import config as cfg

        original_defaults = dict(cfg.DEFAULTS)
        original_secrets = set(cfg.SECRET_KEYS)
        original_module_secrets = set(cfg.MODULE_SECRET_KEYS)
        original_module_secret_owners = dict(cfg.MODULE_SECRET_OWNERS)
        try:
            cfg.DEFAULTS.pop("admin_password", None)
            assert "admin_password" in cfg.HASH_KEYS
            assert "admin_password" not in cfg.MODULE_SECRET_KEYS

            registered = register_module_config(
                {"admin_password": ""},
                config_secrets={"admin_password"},
                module_id="community.claimant",
            )

            assert registered == set()
            assert "admin_password" in cfg.HASH_KEYS
            assert "admin_password" not in cfg.MODULE_SECRET_KEYS
            assert "admin_password" not in cfg.MODULE_SECRET_OWNERS
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)
            cfg.SECRET_KEYS.clear()
            cfg.SECRET_KEYS.update(original_secrets)
            cfg.MODULE_SECRET_KEYS.clear()
            cfg.MODULE_SECRET_KEYS.update(original_module_secrets)
            cfg.MODULE_SECRET_OWNERS.clear()
            cfg.MODULE_SECRET_OWNERS.update(original_module_secret_owners)

    @pytest.mark.parametrize("reserved_key", ["mqtt_password", "speedtest_tracker_token"])
    def test_core_secret_without_registered_default_is_not_module_owned(self, reserved_key):
        """Modules cannot claim reserved core secrets before their defaults are loaded."""
        from app import config as cfg

        original_defaults = dict(cfg.DEFAULTS)
        original_secrets = set(cfg.SECRET_KEYS)
        original_module_secrets = set(cfg.MODULE_SECRET_KEYS)
        original_module_secret_owners = dict(cfg.MODULE_SECRET_OWNERS)
        try:
            cfg.DEFAULTS.pop(reserved_key, None)
            assert reserved_key in cfg.SECRET_KEYS
            assert reserved_key not in cfg.MODULE_SECRET_KEYS

            registered = register_module_config(
                {reserved_key: ""},
                config_secrets={reserved_key},
                module_id="community.claimant",
            )

            assert registered == set()
            assert reserved_key in cfg.SECRET_KEYS
            assert reserved_key not in cfg.MODULE_SECRET_KEYS
            assert reserved_key not in cfg.MODULE_SECRET_OWNERS
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)
            cfg.SECRET_KEYS.clear()
            cfg.SECRET_KEYS.update(original_secrets)
            cfg.MODULE_SECRET_KEYS.clear()
            cfg.MODULE_SECRET_KEYS.update(original_module_secrets)
            cfg.MODULE_SECRET_OWNERS.clear()
            cfg.MODULE_SECRET_OWNERS.update(original_module_secret_owners)

    def test_core_secret_collision_is_not_registered_as_module_owned(self):
        """Modules cannot claim existing core secret keys as module-owned secrets."""
        from app import config as cfg

        original_defaults = dict(cfg.DEFAULTS)
        original_secrets = set(cfg.SECRET_KEYS)
        original_module_secrets = set(cfg.MODULE_SECRET_KEYS)
        original_module_secret_owners = dict(cfg.MODULE_SECRET_OWNERS)
        try:
            registered = register_module_config(
                {"modem_password": ""},
                config_secrets={"modem_password"},
                module_id="community.claimant",
            )

            assert registered == set()
            assert "modem_password" in cfg.SECRET_KEYS
            assert "modem_password" not in cfg.MODULE_SECRET_KEYS
        finally:
            cfg.DEFAULTS.clear()
            cfg.DEFAULTS.update(original_defaults)
            cfg.SECRET_KEYS.clear()
            cfg.SECRET_KEYS.update(original_secrets)
            cfg.MODULE_SECRET_KEYS.clear()
            cfg.MODULE_SECRET_KEYS.update(original_module_secrets)
            cfg.MODULE_SECRET_OWNERS.clear()
            cfg.MODULE_SECRET_OWNERS.update(original_module_secret_owners)


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

