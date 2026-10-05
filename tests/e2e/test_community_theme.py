"""A community theme in the documented format styles the running app.

The theme below is the example from the Themes wiki page. It only sets the
documented core tokens, so it shows whether pages follow those tokens rather
than the built-in themes' complete token sets: the roles the built-in themes
set on top (page background, cards, accent shades) derive from the core.
"""

import json
import os
from pathlib import Path

import pytest
from playwright.sync_api import expect

from tests.e2e.support.lifecycle import (
    ProcessSpec, artifact_log_path, reserve_local_port, running_processes,
)

THEME_ID = "community.wiki_example"
THEME = {
    "meta": {"family": "dark-first"},
    "dark": {
        "--bg": "#101316", "--surface": "#1c1e22", "--elevated": "#26292d",
        "--text": "#ebecee", "--text-secondary": "#cdcfd2", "--muted": "#aaadb0",
        "--accent": "#8cb4e8", "--text-on-accent": "#0f1215",
        "--good": "#8ec495", "--warn": "#e2a579", "--crit": "#f8958d",
    },
    "light": {
        "--bg": "#f1f4f7", "--surface": "#fbfcfd", "--elevated": "#e7eaee",
        "--text": "#1f2225", "--text-secondary": "#3d4044", "--muted": "#595c61",
        "--accent": "#34629b", "--text-on-accent": "#fbfcfc",
        "--good": "#32703e", "--warn": "#8e4e12", "--crit": "#a13735",
    },
}


def _rgb(hex_color):
    value = hex_color.lstrip("#")
    return "rgb({}, {}, {})".format(*(int(value[i:i + 2], 16) for i in (0, 2, 4)))


def serve_community_theme(data_path, *, listener_socket):
    from waitress.server import create_server

    from app.app_factory import create_app, default_module_loader_factory
    from app.config import ConfigManager

    os.environ.clear()
    os.environ["TZ"] = "UTC"
    root = Path(data_path)
    module = root / "modules" / "wiki-example-theme"
    module.mkdir(parents=True)
    (module / "manifest.json").write_text(json.dumps({
        "id": THEME_ID, "name": "Wiki Example", "description": "Documented example theme",
        "version": "1.0.0", "author": "docsight-tests", "minAppVersion": "2026.3",
        "type": "theme", "contributes": {"theme": "theme.json"},
    }))
    (module / "theme.json").write_text(json.dumps(THEME))
    config = ConfigManager(str(root / "data"))
    config.save({"modem_type": "generic", "active_theme": THEME_ID, "update_check_enabled": False})
    application = create_app(
        config_manager=config, testing=True, environ={},
        module_loader_factory=default_module_loader_factory(config, search_paths=[str(root / "modules")]),
    )
    create_server(application, sockets=[listener_socket], threads=2).run()


@pytest.fixture(scope="module")
def community_theme_server(tmp_path_factory):
    data_path = tmp_path_factory.mktemp("community_theme")
    reservation = reserve_local_port()
    identity = f"community-theme-{reservation.port}"
    spec = ProcessSpec(
        identity=identity, reservation=reservation,
        process_target=serve_community_theme, args=(str(data_path),),
        readiness_path="", log_path=artifact_log_path(identity), data_path=str(data_path),
    )
    # The reservation is handed to the server process; read the port before that.
    base_url = f"http://127.0.0.1:{reservation.port}"
    with running_processes([spec]):
        yield base_url


def _styles(page):
    return page.evaluate("""() => {
        const root = getComputedStyle(document.documentElement);
        const body = getComputedStyle(document.body);
        return {
            tokens: Object.fromEntries(['--bg', '--surface', '--text', '--accent', '--good', '--crit']
                .map(name => [name, root.getPropertyValue(name).trim()])),
            roles: Object.fromEntries(['--void', '--card', '--amethyst', '--good-muted']
                .map(name => [name, root.getPropertyValue(name).trim()])),
            bodyColor: body.color,
            bodyBackground: body.backgroundColor,
            hasThemeBlock: !!document.getElementById('theme-module-vars'),
        };
    }""")


@pytest.mark.parametrize("path", ["/", "/settings"])
@pytest.mark.parametrize("mode", ["dark", "light"])
def test_documented_core_tokens_reach_the_page(page, community_theme_server, path, mode):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(community_theme_server + path, wait_until="networkidle")
    page.evaluate("mode => { document.documentElement.dataset.theme = mode; }", mode)
    styles = _styles(page)

    assert styles["hasThemeBlock"]
    for name, value in styles["tokens"].items():
        assert value == THEME[mode][name], (path, mode, name)
    assert styles["bodyColor"] == _rgb(THEME[mode]["--text"])
    # Roles the documented format does not set follow its core tokens.
    assert styles["roles"] == {
        "--void": THEME[mode]["--bg"], "--card": THEME[mode]["--surface"], "--amethyst": THEME[mode]["--accent"],
        "--good-muted": f"color-mix(in srgb, {THEME[mode]['--good']} {15 if mode == 'dark' else 12}%, transparent)",
    }
    assert styles["bodyBackground"] == _rgb(THEME[mode]["--bg"])
    expect(page.locator("body")).to_be_visible()
    assert errors == []
