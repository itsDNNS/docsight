"""Integration test: full module load cycle with a test fixture module."""

import os
import sys

import pytest
from flask import Flask

from app.module_loader import ModuleLoader


FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


class TestModuleIntegration:
    """End-to-end test with a real module fixture."""

    def setup_method(self):
        """Snapshot global state so we can restore it after each test."""
        from app import config as cfg
        from app.i18n import _TRANSLATIONS

        self._orig_defaults = dict(cfg.DEFAULTS)
        self._orig_bool_keys = set(cfg.BOOL_KEYS)
        self._orig_int_keys = set(cfg.INT_KEYS)
        self._orig_translations = {k: dict(v) for k, v in _TRANSLATIONS.items()}

        # Clean up any leftover dynamic module imports
        self._orig_sys_modules = set(sys.modules.keys())

    def teardown_method(self):
        """Restore global state to avoid polluting other tests."""
        from app import config as cfg
        from app.i18n import _TRANSLATIONS

        cfg.DEFAULTS.clear()
        cfg.DEFAULTS.update(self._orig_defaults)
        cfg.BOOL_KEYS.clear()
        cfg.BOOL_KEYS.update(self._orig_bool_keys)
        cfg.INT_KEYS.clear()
        cfg.INT_KEYS.update(self._orig_int_keys)

        _TRANSLATIONS.clear()
        _TRANSLATIONS.update(self._orig_translations)

        # Remove dynamically imported module entries
        for key in list(sys.modules.keys()):
            if key not in self._orig_sys_modules:
                del sys.modules[key]

    def test_full_load_cycle(self):
        """Discover -> validate -> load config + i18n + routes -> serve requests."""
        app = Flask(__name__)
        loader = ModuleLoader(app, search_paths=[FIXTURE_DIR])
        modules = loader.load_all()

        # Discovery
        assert len(modules) == 1
        mod = modules[0]
        assert mod.id == "test.integration"
        assert mod.enabled is True
        assert mod.error is None

        # Config registered
        from app import config as cfg

        assert "test_integration_enabled" in cfg.DEFAULTS
        assert "test_integration_interval" in cfg.DEFAULTS
        assert "test_integration_enabled" in cfg.BOOL_KEYS
        assert "test_integration_interval" in cfg.INT_KEYS

        # i18n merged
        from app.i18n import get_translations

        en = get_translations("en")
        assert en["test.integration.name"] == "Integration Test"
        assert en["test.integration.description"] == "Module for testing"

        # Routes work
        with app.test_client() as c:
            resp = c.get("/api/modules/test.integration/ping")
            assert resp.status_code == 200
            data = resp.get_json()
            assert data["pong"] is True
            assert data["module"] == "test.integration"

    def test_disable_skips_loading(self):
        """Disabled modules are discovered but their contributions are not loaded."""
        app = Flask(__name__)
        loader = ModuleLoader(
            app,
            search_paths=[FIXTURE_DIR],
            disabled_ids={"test.integration"},
        )
        modules = loader.load_all()

        assert len(modules) == 1
        assert modules[0].enabled is False

        # Route should NOT be registered
        with app.test_client() as c:
            resp = c.get("/api/modules/test.integration/ping")
            assert resp.status_code == 404

        # Config should NOT be registered
        from app import config as cfg

        assert "test_integration_enabled" not in cfg.DEFAULTS

        # i18n should NOT be merged
        from app.i18n import get_translations

        en = get_translations("en")
        assert "test.integration.name" not in en
