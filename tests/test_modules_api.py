"""Tests for module management API endpoints."""

import os

import pytest
from flask import Flask

from app.module_loader import ModuleLoader

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture
def app_with_modules():
    """Create a Flask app with modules loaded."""
    app = Flask(__name__)
    app.config["TESTING"] = True
    loader = ModuleLoader(app, search_paths=[FIXTURE_DIR])
    loader.load_all()

    from app import web
    web.init_modules(loader)

    from app.blueprints.modules_bp import modules_bp
    app.register_blueprint(modules_bp)

    yield app, loader

    # Clean up global state
    web.init_modules(None)


class TestGetModules:
    """GET /api/modules returns all discovered modules."""

    def test_returns_all_modules(self, app_with_modules):
        app, loader = app_with_modules
        with app.test_client() as c:
            resp = c.get("/api/modules")
            assert resp.status_code == 200
            data = resp.get_json()
            assert isinstance(data, list)
            assert len(data) == 2
            ids = {m["id"] for m in data}
            assert "test.integration" in ids
            assert "test.ui" in ids

    def test_module_fields(self, app_with_modules):
        app, _ = app_with_modules
        with app.test_client() as c:
            resp = c.get("/api/modules")
            data = resp.get_json()
            mod = next(m for m in data if m["id"] == "test.integration")
            for field in ("name", "version", "type", "author", "enabled", "builtin", "error", "description"):
                assert field in mod

    def test_disabled_module_shown(self):
        """Disabled modules appear in the list with enabled=False."""
        app = Flask(__name__)
        app.config["TESTING"] = True
        loader = ModuleLoader(
            app, search_paths=[FIXTURE_DIR],
            disabled_ids={"test.integration"},
        )
        loader.load_all()

        from app import web
        web.init_modules(loader)

        from app.blueprints.modules_bp import modules_bp
        app.register_blueprint(modules_bp)

        try:
            with app.test_client() as c:
                resp = c.get("/api/modules")
                data = resp.get_json()
                mod = next(m for m in data if m["id"] == "test.integration")
                assert mod["enabled"] is False
        finally:
            web.init_modules(None)


class TestEnableDisable:
    """POST /api/modules/<id>/enable and /disable."""

    @pytest.fixture(autouse=True)
    def setup_app(self, tmp_path):
        from app.config import ConfigManager

        self.app = Flask(__name__)
        self.app.config["TESTING"] = True

        self.config_mgr = ConfigManager(str(tmp_path))
        self.config_mgr.save({"disabled_modules": ""})

        self.loader = ModuleLoader(
            self.app, search_paths=[FIXTURE_DIR],
        )
        self.loader.load_all()

        from app import web
        self._orig_module_loader = web._module_loader
        self._orig_config_manager = web._config_manager
        web.init_modules(self.loader)
        web.init_config(self.config_mgr)

        from app.blueprints.modules_bp import modules_bp
        self.app.register_blueprint(modules_bp)

        yield

        # Restore global state
        web._module_loader = self._orig_module_loader
        web._config_manager = self._orig_config_manager

    def test_disable_module(self):
        with self.app.test_client() as c:
            resp = c.post("/api/modules/test.integration/disable")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True
            assert data["restart_required"] is True

        disabled = self.config_mgr.get("disabled_modules", "")
        assert "test.integration" in disabled

    def test_enable_module(self):
        self.config_mgr.save({"disabled_modules": "test.integration"})

        with self.app.test_client() as c:
            resp = c.post("/api/modules/test.integration/enable")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["success"] is True

        disabled = self.config_mgr.get("disabled_modules", "")
        assert "test.integration" not in disabled

    def test_disable_unknown_module(self):
        with self.app.test_client() as c:
            resp = c.post("/api/modules/nonexistent.module/disable")
            assert resp.status_code == 404

    def test_disable_already_disabled(self):
        self.config_mgr.save({"disabled_modules": "test.integration"})
        with self.app.test_client() as c:
            resp = c.post("/api/modules/test.integration/disable")
            assert resp.status_code == 200

    def test_enable_already_enabled(self):
        with self.app.test_client() as c:
            resp = c.post("/api/modules/test.integration/enable")
            assert resp.status_code == 200


class TestThemeMutualExclusion:
    """Enabling a theme auto-disables others; cannot disable last theme."""

    @pytest.fixture
    def app_with_themes(self, tmp_path):
        """Create app with two theme modules."""
        import json
        for name, tid in [("theme1", "test.theme1"), ("theme2", "test.theme2")]:
            d = tmp_path / name
            d.mkdir()
            (d / "manifest.json").write_text(json.dumps({
                "id": tid, "name": name, "description": "d",
                "version": "1.0.0", "author": "a", "minAppVersion": "2026.2",
                "type": "theme",
                "contributes": {"theme": "theme.json"},
            }))
            (d / "theme.json").write_text(json.dumps({
                "dark": {"--bg": "#111", "--text": "#fff"},
                "light": {"--bg": "#fff", "--text": "#111"},
            }))

        app = Flask(__name__)
        app.config["TESTING"] = True
        loader = ModuleLoader(app, search_paths=[str(tmp_path)])
        loader.load_all()

        from app import web
        web.init_modules(loader)

        from app.config import ConfigManager
        config = ConfigManager(str(tmp_path / "config"))
        config.save({"disabled_modules": ""})
        web.init_config(config)

        from app.blueprints.modules_bp import modules_bp
        app.register_blueprint(modules_bp)

        yield app, loader, config
        web.init_modules(None)
        web._config_manager = None

    def test_enable_theme_disables_other(self, app_with_themes):
        app, loader, config = app_with_themes
        with app.test_client() as c:
            resp = c.post("/api/modules/test.theme2/enable")
            assert resp.status_code == 200
            disabled = config.get("disabled_modules", "")
            assert "test.theme1" in disabled

    def test_disable_last_theme_blocked(self, app_with_themes):
        app, loader, config = app_with_themes
        config.save({"disabled_modules": "test.theme1"})
        with app.test_client() as c:
            resp = c.post("/api/modules/test.theme2/disable")
            assert resp.status_code == 409
            data = resp.get_json()
            assert data["success"] is False

    def test_serialize_includes_is_theme(self, app_with_themes):
        app, loader, config = app_with_themes
        with app.test_client() as c:
            resp = c.get("/api/modules")
            data = resp.get_json()
            theme = next(m for m in data if m["id"] == "test.theme1")
            assert theme["is_theme"] is True
