"""Inline JavaScript in community modules decides whether the CSP allows inline scripts."""

import json
from types import SimpleNamespace

import pytest
from flask import Flask

from app.module_inline_code import module_has_inline_code, modules_with_inline_code, template_has_inline_code
from app.web import add_security_headers


@pytest.mark.parametrize("markup", [
    "<script>start()</script>",
    '<script type="module">start()</script>',
    '<button onclick="start()">Go</button>',
    '<img src="x.png" onerror="this.remove()">',
    '<a href="javascript:start()">Go</a>',
])
def test_inline_javascript_is_found(markup):
    assert template_has_inline_code(f"<div>{{{{ t.title }}}}{markup}</div>")


@pytest.mark.parametrize("markup", [
    '<script src="{{ module_static_url(mod.id, \'main.js\') }}"></script>',
    '<script type="application/json" id="data">{"a": 1}</script>',
    '<button id="go" data-action="start" class="one">Go</button>',
    '<a href="https://example.test/javascript:">Docs</a>',
])
def test_external_scripts_and_data_are_fine(markup):
    assert not template_has_inline_code(f"<div>{markup}</div>")


def _module(tmp_path, name, template, **info):
    path = tmp_path / name / "templates"
    path.mkdir(parents=True)
    (path / "tab.html").write_text(template, encoding="utf-8")
    return SimpleNamespace(id=f"community.{name}", path=str(tmp_path / name),
                           builtin=False, enabled=True, error=None, **info)


def test_only_enabled_community_modules_with_inline_code_count(tmp_path):
    inline = _module(tmp_path, "old", "<button onclick='x()'>x</button>")
    clean = _module(tmp_path, "new", "<button id='x'>x</button>")
    disabled = _module(tmp_path, "off", "<script>x()</script>")
    disabled.enabled = False
    broken = _module(tmp_path, "broken", "<script>x()</script>")
    broken.error = "failed to load"
    builtin = _module(tmp_path, "core", "<script>x()</script>")
    builtin.builtin = True

    assert module_has_inline_code(inline.path)
    assert modules_with_inline_code([inline, clean, disabled, broken, builtin]) == ("community.old",)


def _headers(inline_modules):
    app = Flask(__name__)
    app.extensions["docsight_inline_script_modules"] = inline_modules
    with app.test_request_context("/"):
        return add_security_headers(app.response_class("ok")).headers


def test_scripts_are_strict_unless_a_module_needs_inline_code():
    strict = _headers(())
    assert "script-src 'self';" in strict["Content-Security-Policy"]
    assert "'unsafe-inline'" not in strict["Content-Security-Policy"].split("style-src")[0]
    bridged = _headers(("community.old",))
    assert "script-src 'self' 'unsafe-inline';" in bridged["Content-Security-Policy"]


def test_trusted_types_are_reported_for_the_one_policy():
    report_only = _headers(())["Content-Security-Policy-Report-Only"]
    assert report_only == "require-trusted-types-for 'script'; trusted-types docsight"


def test_doctor_names_enabled_modules_with_inline_code(tmp_path, monkeypatch):
    from app.doctor import build_report

    modules = tmp_path / "modules"
    for name, template in (("old", "<script>x()</script>"), ("new", "<p>x</p>"), ("off", "<script>x()</script>")):
        _module(modules, name, template)
        (modules / name / "manifest.json").write_text(json.dumps({"id": f"community.{name}"}), encoding="utf-8")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "config.json").write_text(json.dumps({"disabled_modules": "community.off"}), encoding="utf-8")
    monkeypatch.setenv("MODULES_DIR", str(modules))

    check = next(c for c in build_report(data_dir=str(data_dir))["checks"] if c["id"] == "modules.inline_scripts")
    assert check["status"] == "warn"
    assert check["details"]["modules"] == ["community.old"]

    (modules / "old" / "templates" / "tab.html").write_text("<p>x</p>", encoding="utf-8")
    check = next(c for c in build_report(data_dir=str(data_dir))["checks"] if c["id"] == "modules.inline_scripts")
    assert check["status"] == "pass"


@pytest.mark.parametrize(("tab", "strict"), [
    ('<div id="old-tab"><button onclick="refresh()">Refresh</button></div>', False),
    ('<div id="new-tab"><button id="refresh">Refresh</button></div>', True),
])
def test_the_app_keeps_inline_scripts_only_for_a_module_that_needs_them(tmp_path, tab, strict):
    from app.app_factory import create_app, default_module_loader_factory
    from app.config import ConfigManager

    module_dir = tmp_path / "modules" / "legacy"
    (module_dir / "templates").mkdir(parents=True)
    (module_dir / "templates" / "tab.html").write_text(tab, encoding="utf-8")
    (module_dir / "manifest.json").write_text(json.dumps({
        "id": "community.legacy", "name": "Legacy", "description": "Legacy tab",
        "version": "1.0.0", "author": "Test", "minAppVersion": "2026.2", "type": "integration",
        "contributes": {"tab": "templates/tab.html"},
        "menu": {"label_key": "community.legacy.title", "icon": "puzzle", "order": 90},
    }), encoding="utf-8")
    manager = ConfigManager(str(tmp_path / "data"))
    app = create_app(
        config_manager=manager, storage=None, environ={}, testing=True,
        module_loader_factory=default_module_loader_factory(manager, search_paths=[str(tmp_path / "modules")]),
    )

    assert app.extensions["docsight_inline_script_modules"] == (() if strict else ("community.legacy",))
    csp = app.test_client().get("/health").headers["Content-Security-Policy"]
    assert ("script-src 'self';" in csp) is strict
