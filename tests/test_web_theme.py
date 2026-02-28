"""Tests for theme context injection in web.py."""

import pytest
from app.module_loader import ModuleInfo


class TestThemeContext:
    """Test active theme module is available in template context."""

    def test_active_theme_in_context(self):
        """Context processor includes active_theme_data when theme module is active."""
        from app import web

        theme_mod = ModuleInfo(
            id="test.theme", name="Test Theme", description="d",
            version="1.0.0", author="a", min_app_version="2026.2",
            type="theme", contributes={"theme": "theme.json"}, path="/tmp",
            theme_data={
                "dark": {"--bg": "#111", "--text": "#fff"},
                "light": {"--bg": "#fff", "--text": "#111"},
            },
        )

        class FakeLoader:
            def get_enabled_modules(self):
                return [theme_mod]
            def get_theme_modules(self):
                return [theme_mod]

        class FakeConfig:
            def get(self, key, default=""):
                if key == "active_theme":
                    return "test.theme"
                return default

        old_loader = web._module_loader
        old_config = web._config_manager
        try:
            web._module_loader = FakeLoader()
            web._config_manager = FakeConfig()

            with web.app.test_request_context("/"):
                ctx = web.inject_auth()
                assert "active_theme_data" in ctx
                assert ctx["active_theme_data"]["dark"]["--bg"] == "#111"
        finally:
            web._module_loader = old_loader
            web._config_manager = old_config

    def test_no_theme_returns_none(self):
        """Context processor returns None when no theme modules exist."""
        from app import web

        class FakeLoader:
            def get_enabled_modules(self):
                return []
            def get_theme_modules(self):
                return []

        class FakeConfig:
            def get(self, key, default=""):
                return default

        old_loader = web._module_loader
        old_config = web._config_manager
        try:
            web._module_loader = FakeLoader()
            web._config_manager = FakeConfig()

            with web.app.test_request_context("/"):
                ctx = web.inject_auth()
                assert "active_theme_data" in ctx
                assert ctx["active_theme_data"] is None
        finally:
            web._module_loader = old_loader
            web._config_manager = old_config
