"""Tests for theme context injection in web.py."""

from types import SimpleNamespace

import pytest
from app.module_registry import ModuleInfo
from app.runtime import current_runtime


class TestThemeContext:
    """Test active theme module is available in template context."""

    @staticmethod
    def _context(monkeypatch, make_config, themes, active="", enabled=None):
        """Template context for these installed themes, the enabled ones (default: all) and the saved choice."""
        from app import web

        loader = SimpleNamespace(
            get_enabled_modules=lambda: themes if enabled is None else enabled,
            get_theme_modules=lambda: themes,
        )
        monkeypatch.setattr(current_runtime(), "module_loader", loader)
        monkeypatch.setattr(current_runtime(), "config_manager", make_config({"active_theme": active}))
        with app.test_request_context("/"):
            return web.inject_auth()

    @staticmethod
    def _theme(theme_id, dark, light=None, name=None):
        return ModuleInfo(
            id=theme_id, name=name or theme_id, description="d",
            version="1.0.0", author="a", min_app_version="2026.2",
            type="theme", contributes={"theme": "theme.json"}, path="/tmp",
            theme_data={"dark": dark, "light": light or {"--bg": "#fff"}},
        )

    def test_active_theme_in_context(self, monkeypatch, make_config):
        """Context processor includes active_theme_data when theme module is active."""
        theme_mod = self._theme("test.theme", {"--bg": "#111", "--text": "#fff"}, {"--bg": "#fff", "--text": "#111"})

        ctx = self._context(monkeypatch, make_config, [theme_mod], active="test.theme")

        assert ctx["active_theme_data"]["dark"]["--bg"] == "#111"

    def test_no_theme_returns_none(self, monkeypatch, make_config):
        """Context processor returns None when no theme modules exist."""
        ctx = self._context(monkeypatch, make_config, [])

        assert "active_theme_data" in ctx
        assert ctx["active_theme_data"] is None

    def test_fallback_prefers_graphite_over_alphabetical(self, monkeypatch, make_config):
        """Without a configured theme, Graphite is the default over alphabetical order."""
        modules = [
            self._theme("docsight.theme_amber_terminal", {"--bg": "#1a1200"}),
            self._theme("docsight.theme_classic", {"--bg": "#111"}),
            self._theme("docsight.theme_graphite", {"--bg": "#101316"}),
        ]

        ctx = self._context(monkeypatch, make_config, modules)

        assert ctx["active_theme_id"] == "docsight.theme_graphite"
        assert ctx["active_theme_data"]["dark"]["--bg"] == "#101316"

    def test_explicit_classic_selection_is_kept(self, monkeypatch, make_config):
        """Users who chose Classic keep it after Graphite became the default."""
        modules = [
            self._theme("docsight.theme_classic", {"--bg": "#111"}),
            self._theme("docsight.theme_graphite", {"--bg": "#101316"}),
        ]

        ctx = self._context(monkeypatch, make_config, modules, active="docsight.theme_classic")

        assert ctx["active_theme_id"] == "docsight.theme_classic"

    def test_gallery_lists_active_theme_first_then_names(self, monkeypatch, make_config):
        """The gallery needs only the active selection and alphabetical ordering."""
        classic = self._theme("docsight.theme_classic", {"--bg": "#111"}, name="Classic")
        modules = [
            self._theme("docsight.theme_matrix", {"--bg": "#111"}, name="Matrix"),
            self._theme("docsight.theme_tokyo_night", {"--bg": "#111"}, name="Tokyo Night"),
            classic,
        ]

        ctx = self._context(monkeypatch, make_config, modules, active="docsight.theme_classic", enabled=[classic])

        assert [m.id for m in ctx["all_theme_modules"]] == [
            "docsight.theme_classic",
            "docsight.theme_matrix",
            "docsight.theme_tokyo_night",
        ]

    def test_gallery_marks_themes_with_low_text_contrast(self, monkeypatch, make_config):
        """Community themes below AA get a visible hint; readable themes do not."""
        from app.i18n import get_translations

        def theme(theme_id, muted):
            tokens = {"--surface": "#1f2937", "--void": "#111827", "--text": "#f9fafb",
                      "--text-secondary": "#d1d5db", "--muted": muted}
            return self._theme(theme_id, tokens, dict(tokens))

        readable = theme("community.readable", "#a7acb6")
        modules = [readable, theme("community.faint", "#4b5563")]

        ctx = self._context(monkeypatch, make_config, modules, active="community.readable", enabled=[readable])

        assert ctx["theme_contrast_warnings"] == {"community.faint": ["dark", "light"]}
        with app.test_request_context("/settings"):
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
