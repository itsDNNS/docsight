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

    return app, loader


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

        with app.test_client() as c:
            resp = c.get("/api/modules")
            data = resp.get_json()
            mod = next(m for m in data if m["id"] == "test.integration")
            assert mod["enabled"] is False


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
        web.init_modules(self.loader)
        web.init_config(self.config_mgr)

        from app.blueprints.modules_bp import modules_bp
        self.app.register_blueprint(modules_bp)

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
