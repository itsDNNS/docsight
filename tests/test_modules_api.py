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
