"""Tests for theme context injection in web.py."""

import pytest
from app.module_loader import ModuleInfo
from app.runtime import current_runtime


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

        old_loader = current_runtime().module_loader
        old_config = current_runtime().config_manager
        try:
            current_runtime().module_loader = FakeLoader()
            current_runtime().config_manager = FakeConfig()

            with app.test_request_context("/"):
                ctx = web.inject_auth()
                assert "active_theme_data" in ctx
                assert ctx["active_theme_data"]["dark"]["--bg"] == "#111"
        finally:
            current_runtime().module_loader = old_loader
            current_runtime().config_manager = old_config

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

        old_loader = current_runtime().module_loader
        old_config = current_runtime().config_manager
        try:
            current_runtime().module_loader = FakeLoader()
            current_runtime().config_manager = FakeConfig()

            with app.test_request_context("/"):
                ctx = web.inject_auth()
                assert "active_theme_data" in ctx
                assert ctx["active_theme_data"] is None
        finally:
            current_runtime().module_loader = old_loader
            current_runtime().config_manager = old_config

    def test_fallback_prefers_classic_over_alphabetical(self):
        """When no active_theme is configured, Classic is chosen over alphabetically first."""
        from app import web

        amber = ModuleInfo(
            id="docsight.theme_amber_terminal", name="Amber Terminal", description="d",
            version="1.0.0", author="a", min_app_version="2026.2",
            type="theme", contributes={"theme": "theme.json"}, path="/tmp",
            theme_data={"dark": {"--bg": "#1a1200"}, "light": {"--bg": "#fff8e0"}},
        )
        classic = ModuleInfo(
            id="docsight.theme_classic", name="Classic", description="d",
            version="1.0.0", author="a", min_app_version="2026.2",
            type="theme", contributes={"theme": "theme.json"}, path="/tmp",
            theme_data={"dark": {"--bg": "#111"}, "light": {"--bg": "#fff"}},
        )

        class FakeLoader:
            def get_enabled_modules(self):
                return [amber, classic]
            def get_theme_modules(self):
                return [amber, classic]  # amber first (alphabetical)

        class FakeConfig:
            def get(self, key, default=""):
                return default  # no active_theme set

        old_loader = current_runtime().module_loader
        old_config = current_runtime().config_manager
        try:
            current_runtime().module_loader = FakeLoader()
            current_runtime().config_manager = FakeConfig()

            with app.test_request_context("/"):
                ctx = web.inject_auth()
                assert ctx["active_theme_id"] == "docsight.theme_classic"
                assert ctx["active_theme_data"]["dark"]["--bg"] == "#111"
        finally:
            current_runtime().module_loader = old_loader
            current_runtime().config_manager = old_config

    def test_theme_collections_are_grouped_for_gallery(self):
        """Theme gallery collections group signature, community, and playful themes."""
        from app import web

        signature = ModuleInfo(
            id="docsight.theme_classic", name="Classic", description="d",
            version="1.0.0", author="a", min_app_version="2026.2",
            type="theme", contributes={"theme": "theme.json"}, path="/tmp",
            theme_data={"dark": {"--bg": "#111"}, "light": {"--bg": "#fff"}},
        )
        community = ModuleInfo(
            id="docsight.theme_tokyo_night", name="Tokyo Night", description="d",
            version="1.0.0", author="a", min_app_version="2026.2",
            type="theme", contributes={"theme": "theme.json"}, path="/tmp",
            theme_data={"dark": {"--bg": "#111"}, "light": {"--bg": "#fff"}},
        )
        playful = ModuleInfo(
            id="docsight.theme_matrix", name="Matrix", description="d",
            version="1.0.0", author="a", min_app_version="2026.2",
            type="theme", contributes={"theme": "theme.json"}, path="/tmp",
            theme_data={"dark": {"--bg": "#111"}, "light": {"--bg": "#fff"}},
        )

        class FakeLoader:
            def get_enabled_modules(self):
                return [signature]
            def get_theme_modules(self):
                return [playful, community, signature]

        class FakeConfig:
            def get(self, key, default=""):
                if key == "active_theme":
                    return "docsight.theme_classic"
                return default

        old_loader = current_runtime().module_loader
        old_config = current_runtime().config_manager
        try:
            current_runtime().module_loader = FakeLoader()
            current_runtime().config_manager = FakeConfig()

            with app.test_request_context("/settings"):
                ctx = web.inject_auth()
                assert [c["key"] for c in ctx["theme_collections"]] == [
                    "signature",
                    "community",
                    "playful",
                ]
                assert [m.id for m in ctx["theme_collections"][1]["modules"]] == [
                    "docsight.theme_tokyo_night",
                ]
        finally:
            current_runtime().module_loader = old_loader
            current_runtime().config_manager = old_config
