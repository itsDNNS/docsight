"""Tests for theme context injection in web.py."""

import pytest
from app.module_loader import ModuleInfo
from app.runtime import current_runtime


class TestThemeContext:
    """Test active theme module is available in template context."""

    def test_active_theme_in_context(self, monkeypatch):
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
            def has_stored_value(self, key):
                return False

            def get(self, key, default=""):
                if key == "active_theme":
                    return "test.theme"
                return default

        monkeypatch.setattr(current_runtime(), "module_loader", FakeLoader())
        monkeypatch.setattr(current_runtime(), "config_manager", FakeConfig())

        with app.test_request_context("/"):
            ctx = web.inject_auth()
            assert "active_theme_data" in ctx
            assert ctx["active_theme_data"]["dark"]["--bg"] == "#111"

    def test_no_theme_returns_none(self, monkeypatch):
        """Context processor returns None when no theme modules exist."""
        from app import web

        class FakeLoader:
            def get_enabled_modules(self):
                return []
            def get_theme_modules(self):
                return []

        class FakeConfig:
            def has_stored_value(self, key):
                return False

            def get(self, key, default=""):
                return default

        monkeypatch.setattr(current_runtime(), "module_loader", FakeLoader())
        monkeypatch.setattr(current_runtime(), "config_manager", FakeConfig())

        with app.test_request_context("/"):
            ctx = web.inject_auth()
            assert "active_theme_data" in ctx
            assert ctx["active_theme_data"] is None

    def _fallback_context(self, monkeypatch, modules, active=""):
        from app import web

        class FakeLoader:
            def get_enabled_modules(self):
                return modules
            def get_theme_modules(self):
                return modules

        class FakeConfig:
            def has_stored_value(self, key):
                return False

            def get(self, key, default=""):
                return active if key == "active_theme" else default

        monkeypatch.setattr(current_runtime(), "module_loader", FakeLoader())
        monkeypatch.setattr(current_runtime(), "config_manager", FakeConfig())
        with app.test_request_context("/"):
            return web.inject_auth()

    @staticmethod
    def _theme(theme_id, bg):
        return ModuleInfo(
            id=theme_id, name=theme_id, description="d",
            version="1.0.0", author="a", min_app_version="2026.2",
            type="theme", contributes={"theme": "theme.json"}, path="/tmp",
            theme_data={"dark": {"--bg": bg}, "light": {"--bg": "#fff"}},
        )

    def test_fallback_prefers_graphite_over_alphabetical(self, monkeypatch):
        """Without a configured theme, Graphite is the default over alphabetical order."""
        modules = [
            self._theme("docsight.theme_amber_terminal", "#1a1200"),
            self._theme("docsight.theme_classic", "#111"),
            self._theme("docsight.theme_graphite", "#101316"),
        ]

        ctx = self._fallback_context(monkeypatch, modules)

        assert ctx["active_theme_id"] == "docsight.theme_graphite"
        assert ctx["active_theme_data"]["dark"]["--bg"] == "#101316"

    def test_explicit_classic_selection_is_kept(self, monkeypatch):
        """Users who chose Classic keep it after Graphite became the default."""
        modules = [
            self._theme("docsight.theme_classic", "#111"),
            self._theme("docsight.theme_graphite", "#101316"),
        ]

        ctx = self._fallback_context(monkeypatch, modules, active="docsight.theme_classic")

        assert ctx["active_theme_id"] == "docsight.theme_classic"

    def test_gallery_lists_active_theme_first_then_names(self, monkeypatch):
        """The gallery needs only the active selection and alphabetical ordering."""
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
            def has_stored_value(self, key):
                return False

            def get(self, key, default=""):
                if key == "active_theme":
                    return "docsight.theme_classic"
                return default

        monkeypatch.setattr(current_runtime(), "module_loader", FakeLoader())
        monkeypatch.setattr(current_runtime(), "config_manager", FakeConfig())

        with app.test_request_context("/settings"):
            ctx = web.inject_auth()
            assert [m.id for m in ctx["all_theme_modules"]] == [
                "docsight.theme_classic",
                "docsight.theme_matrix",
                "docsight.theme_tokyo_night",
            ]

    def test_gallery_marks_themes_with_low_text_contrast(self, monkeypatch):
        """Community themes below AA get a visible hint; readable themes do not."""
        from app import web
        from app.i18n import get_translations

        def theme(theme_id, muted):
            tokens = {"--surface": "#1f2937", "--void": "#111827", "--text": "#f9fafb",
                      "--text-secondary": "#d1d5db", "--muted": muted}
            return ModuleInfo(
                id=theme_id, name=theme_id, description="d",
                version="1.0.0", author="a", min_app_version="2026.2",
                type="theme", contributes={"theme": "theme.json"}, path="/tmp",
                theme_data={"dark": tokens, "light": dict(tokens)},
            )

        faint = theme("community.faint", "#4b5563")
        readable = theme("community.readable", "#a7acb6")

        class FakeLoader:
            def get_enabled_modules(self):
                return [readable]
            def get_theme_modules(self):
                return [readable, faint]

        class FakeConfig:
            def has_stored_value(self, key):
                return False

            def get(self, key, default=""):
                return "community.readable" if key == "active_theme" else default

        monkeypatch.setattr(current_runtime(), "module_loader", FakeLoader())
        monkeypatch.setattr(current_runtime(), "config_manager", FakeConfig())

        with app.test_request_context("/settings"):
            ctx = web.inject_auth()
            assert ctx["theme_contrast_warnings"] == {"community.faint": ["dark", "light"]}
            html = app.jinja_env.get_template("settings/appearance.html").render(
                **ctx, t=get_translations("en"), theme="dark", config={},
            )
        faint_card = html.split('data-theme-id="community.faint"', 1)[1].split('class="theme-actions"', 1)[0]
        readable_card = html.split('data-theme-id="community.readable"', 1)[1].split('class="theme-actions"', 1)[0]
        assert "Low text contrast:" in faint_card
        assert "Dark Mode" in faint_card and "Light Mode" in faint_card
        assert "theme-contrast-warning" not in readable_card


class TestThemeCssDeclarations:
    def test_quoted_font_names_stay_valid_css(self):
        from app.web import theme_css_declarations

        css = str(theme_css_declarations({"--font-sans": "'DM Sans', system-ui, sans-serif", "--bg": "#101316"}))

        assert "--font-sans: 'DM Sans', system-ui, sans-serif;" in css
        assert "&#39;" not in css
        assert "--bg: #101316;" in css

    @pytest.mark.parametrize("value", [
        "red;} body { display: none",
        "#fff</style><script>alert(1)</script>",
        "#fff /* comment */",
        "url(x)\\",
        "#fff\nbody{}",
    ])
    def test_values_that_could_escape_the_declaration_are_dropped(self, value):
        from app.web import theme_css_declarations

        css = str(theme_css_declarations({"--accent": value, "--ok": "#fff"}))

        assert "--accent" not in css
        assert "--ok: #fff;" in css

    @pytest.mark.parametrize("name", ["accent", "--a b", "--a:b", "</style>"])
    def test_invalid_property_names_are_dropped(self, name):
        from app.web import theme_css_declarations

        assert str(theme_css_declarations({name: "#fff"})) == ""

    def test_non_dict_input_renders_nothing(self):
        from app.web import theme_css_declarations

        assert str(theme_css_declarations(None)) == ""
