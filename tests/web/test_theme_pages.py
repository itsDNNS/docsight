"""Every page renders the active theme, so setup and login look like the app."""

from bs4 import BeautifulSoup

from app.config import ConfigManager
from app.module_registry import discover_builtin_theme_modules
from app.runtime import current_runtime
from app.theme_registry import BUILTIN_THEMES, DEFAULT_THEME_ID


class _ThemeOnlyLoader:
    def __init__(self):
        self._themes = discover_builtin_theme_modules()

    def get_enabled_modules(self):
        return []

    def get_theme_modules(self):
        return self._themes


def _theme_block(html):
    block = BeautifulSoup(html, "html.parser").find("style", id="theme-module-vars")
    return block.get_text() if block else ""


def test_setup_and_login_render_the_active_theme(app, tmp_path):
    graphite = next(theme for theme in BUILTIN_THEMES if theme["id"] == DEFAULT_THEME_ID)
    runtime = current_runtime()
    runtime.module_loader = _ThemeOnlyLoader()

    runtime.config_manager = ConfigManager(str(tmp_path / "fresh"))
    with app.test_client() as client:
        setup = client.get("/setup")

    login_config = ConfigManager(str(tmp_path / "protected"))
    login_config.save({"modem_type": "fritzbox", "modem_password": "x", "admin_password": "theme-check"})
    runtime.config_manager = login_config
    with app.test_client() as client:
        login = client.get("/login")

    for page in (setup, login):
        assert page.status_code == 200
        block = _theme_block(page.get_data(as_text=True))
        for mode in ("dark", "light"):
            assert f"--bg: {graphite['theme_data'][mode]['--bg']};" in block
