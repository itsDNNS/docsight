"""Fault-seed tests for all-or-nothing module contribution registration."""

from __future__ import annotations

import json

import pytest
from flask import Flask

from app import analyzer, config as cfg
from app.i18n import _TRANSLATIONS
from app.module_loader import ModuleLoader


def _manifest(
    module_id: str, contributes: dict[str, str], *, config=None,
    module_type="analysis",
):
    return {
        "id": module_id,
        "name": module_id,
        "description": "atomic registration fixture",
        "version": "1.0.0",
        "author": "Test",
        "minAppVersion": "2026.2",
        "type": module_type,
        "contributes": contributes,
        "config": config or {},
    }


def _write_module(root, directory, manifest, routes=None):
    module = root / directory
    module.mkdir()
    (module / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    if routes is not None:
        (module / "routes.py").write_text(routes, encoding="utf-8")
    return module


def _snapshot(app):
    return {
        "rules": tuple((r.rule, r.endpoint, tuple(sorted(r.methods))) for r in app.url_map.iter_rules()),
        "views": dict(app.view_functions),
        "blueprints": dict(app.blueprints),
        "defaults": dict(cfg.DEFAULTS),
        "bool": set(cfg.BOOL_KEYS),
        "int": set(cfg.INT_KEYS),
        "private": set(cfg.PRIVATE_KEYS),
        "module_secrets": set(cfg.MODULE_SECRET_KEYS),
        "module_owners": dict(cfg.MODULE_SECRET_OWNERS),
        "translations": {lang: dict(values) for lang, values in _TRANSLATIONS.items()},
        "thresholds": analyzer._thresholds,
        "threshold_profile": dict(analyzer._threshold_profile),
    }


def test_mixed_protected_blueprint_is_rejected_without_any_mutation(tmp_path):
    _write_module(
        tmp_path,
        "mixed",
        _manifest("community.mixed", {"routes": "routes.py"}),
        """
from flask import Blueprint
bp = Blueprint("mixed_bp", __name__)
bp.add_url_rule("/community-ok", "ok", lambda: "ok")
bp.add_url_rule("/login", "login_shadow", lambda: "bad")
""",
    )
    app = Flask(__name__)
    before = _snapshot(app)

    loader = ModuleLoader(app, search_paths=[str(tmp_path)])
    module = loader.load_all()[0]

    assert module.error and "protected" in module.error.lower()
    assert _snapshot(app) == before


def test_blueprint_registration_failure_is_rejected_without_any_mutation(tmp_path):
    _write_module(
        tmp_path,
        "broken",
        _manifest("community.broken", {"routes": "routes.py"}),
        """
from flask import Blueprint
bp = Blueprint("broken_bp", __name__)
@bp.record
def fail(state):
    raise RuntimeError("registration exploded")
""",
    )
    app = Flask(__name__)
    before = _snapshot(app)

    module = ModuleLoader(app, search_paths=[str(tmp_path)]).load_all()[0]

    assert module.error and "preflight" in module.error.lower()
    assert _snapshot(app) == before


def test_late_invalid_threshold_rejects_routes_and_catalogs_atomically(tmp_path):
    manifest = _manifest(
        "community.late",
        {
            "routes": "routes.py",
            "static": "static/",
            "i18n": "i18n/",
            "thresholds": "thresholds.json",
        },
        config={"community_late_credential": ""},
    )
    manifest["config_secrets"] = ["community_late_credential"]
    module = _write_module(
        tmp_path,
        "late",
        manifest,
        """
from flask import Blueprint
bp = Blueprint("late_bp", __name__)
bp.add_url_rule("/community-late", "late", lambda: "late")
""",
    )
    (module / "static").mkdir()
    (module / "static" / "main.js").write_text("late", encoding="utf-8")
    (module / "i18n").mkdir()
    (module / "i18n" / "en.json").write_text(json.dumps({"name": "Late"}), encoding="utf-8")
    (module / "thresholds.json").write_text(json.dumps({"downstream_power": {}}), encoding="utf-8")
    app = Flask(__name__)
    before = _snapshot(app)

    info = ModuleLoader(app, search_paths=[str(tmp_path)]).load_all()[0]

    assert info.error and "threshold" in info.error.lower()
    assert info.collector_class is None and info.publisher_class is None
    assert info.template_paths == {} and info.has_css is False and info.has_js is False
    assert _snapshot(app) == before


def test_duplicate_plain_config_ownership_rejects_both_modules(tmp_path):
    key = "community_shared_setting"
    _write_module(tmp_path, "a", _manifest("community.a", {}, config={key: "a"}))
    _write_module(tmp_path, "b", _manifest("community.b", {}, config={key: "b"}))
    app = Flask(__name__)
    before = _snapshot(app)

    modules = ModuleLoader(app, search_paths=[str(tmp_path)]).load_all()

    assert {module.id for module in modules if module.error} == {"community.a", "community.b"}
    assert key not in cfg.DEFAULTS
    assert _snapshot(app) == before


def test_disabled_module_contributes_nothing(tmp_path):
    module = _write_module(
        tmp_path,
        "disabled",
        _manifest(
            "community.disabled",
            {"routes": "routes.py", "static": "static/", "i18n": "i18n/"},
            config={"community_disabled_enabled": True},
        ),
        """
from flask import Blueprint
bp = Blueprint("disabled_bp", __name__)
bp.add_url_rule("/community-disabled", "disabled", lambda: "disabled")
""",
    )
    (module / "static").mkdir()
    (module / "i18n").mkdir()
    (module / "i18n" / "en.json").write_text(json.dumps({"name": "Disabled"}), encoding="utf-8")
    app = Flask(__name__)
    before = _snapshot(app)

    info = ModuleLoader(
        app,
        search_paths=[str(tmp_path)],
        disabled_ids={"community.disabled"},
    ).load_all()[0]

    assert info.enabled is False and info.error is None
    assert _snapshot(app) == before


def test_disabled_theme_retains_only_validated_preview_metadata(tmp_path):
    theme_data = {
        "dark": {"--bg": "#101010", "--accent": "#7654ff"},
        "light": {"--bg": "#fafafa", "--accent": "#5432dd"},
    }
    module = _write_module(
        tmp_path,
        "preview",
        _manifest(
            "community.preview", {"theme": "theme.json"}, module_type="theme"
        ),
    )
    (module / "theme.json").write_text(json.dumps(theme_data), encoding="utf-8")
    app = Flask(__name__)
    before = _snapshot(app)
    loader = ModuleLoader(
        app,
        search_paths=[str(tmp_path)],
        disabled_ids={"community.preview"},
    )

    info = loader.load_all()[0]

    assert info.enabled is False and info.error is None
    assert info.theme_data == theme_data
    assert info.template_paths == {}
    assert info.collector_class is None and info.publisher_class is None
    assert info.thresholds_data is None
    assert info.has_css is False and info.has_js is False
    assert loader.registration_plan == type(loader.registration_plan)()
    assert _snapshot(app) == before


@pytest.mark.parametrize("action", ["enable", "enable/", "disable", "disable/"])
def test_community_own_namespace_cannot_shadow_core_actions(tmp_path, action):
    _write_module(
        tmp_path,
        "action-shadow",
        _manifest("community.owned", {"routes": "routes.py"}),
        f'''\nfrom flask import Blueprint\nbp = Blueprint("owned_action_bp", __name__)\nbp.add_url_rule("/api/modules/community.owned/{action}", "shadow", lambda: "bad")\n''',
    )

    loader = ModuleLoader(Flask(__name__), search_paths=[str(tmp_path)])
    info = loader.load_all()[0]

    assert info.error and "protected route conflicts" in info.error.lower()
    assert str(tmp_path) not in info.error
    assert loader.registration_plan.blueprints == ()


def test_community_own_namespace_allows_non_core_action(tmp_path):
    _write_module(
        tmp_path,
        "owned-status",
        _manifest("community.owned", {"routes": "routes.py"}),
        '''
from flask import Blueprint
bp = Blueprint("owned_status_bp", __name__)
bp.add_url_rule("/api/modules/community.owned/status", "status", lambda: "ok")
''',
    )
    app = Flask(__name__)
    loader = ModuleLoader(app, search_paths=[str(tmp_path)])

    info = loader.load_all()[0]

    assert info.error is None
    assert len(loader.registration_plan.blueprints) == 1
    assert app.test_client().get("/api/modules/community.owned/status").data == b"ok"


@pytest.mark.parametrize(
    ("kind", "spec"),
    [
        ("routes", "missing.py"),
        ("static", "missing-static/"),
        ("i18n", "missing-i18n/"),
        ("tab", "templates/missing.html"),
        ("collector", "missing.py:MissingCollector"),
        ("publisher", "missing.py:MissingPublisher"),
    ],
)
def test_explicit_missing_contribution_rejects_module_atomically(tmp_path, kind, spec):
    _write_module(
        tmp_path,
        "missing",
        _manifest("community.missing", {kind: spec}),
    )
    app = Flask(__name__)
    before = _snapshot(app)

    module = ModuleLoader(app, search_paths=[str(tmp_path)]).load_all()[0]

    assert module.error and kind in module.error.lower()
    assert _snapshot(app) == before


def test_implicit_static_directory_remains_optional(tmp_path):
    _write_module(tmp_path, "no-static", _manifest("community.no_static", {}))
    app = Flask(__name__)

    module = ModuleLoader(app, search_paths=[str(tmp_path)]).load_all()[0]

    assert module.error is None
    assert module.has_css is False and module.has_js is False


def test_contribution_failure_diagnostics_are_redacted(tmp_path, caplog):
    sensitive_value = "private-token-value-9371"
    module = _write_module(
        tmp_path,
        "sensitive-location",
        _manifest(
            "community.redacted",
            {"collector": "collector.py:SensitiveCollectorName"},
        ),
    )
    (module / "collector.py").write_text(
        f"raise RuntimeError({(str(module) + ':' + sensitive_value)!r})\n",
        encoding="utf-8",
    )

    info = ModuleLoader(Flask(__name__), search_paths=[str(tmp_path)]).load_all()[0]

    diagnostics = caplog.text + "\n" + (info.error or "")
    assert "community.redacted" in diagnostics
    assert "collector" in diagnostics
    assert str(tmp_path) not in diagnostics
    assert sensitive_value not in diagnostics
    assert "SensitiveCollectorName" not in diagnostics
