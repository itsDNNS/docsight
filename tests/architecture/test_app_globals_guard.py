"""Keep Flask applications and their mutable state instance-owned."""

import ast
from pathlib import Path

from app import web, web_auth
from app.runtime import current_runtime


ROOT = Path(__file__).resolve().parents[2]
GUARDED_FILES = (
    *(ROOT / "app").glob("web*.py"),
    ROOT / "app" / "app_factory.py",
    ROOT / "app" / "registration.py",
    ROOT / "app" / "runtime.py",
    *(ROOT / "app" / "blueprints").glob("*.py"),
    *(ROOT / "app" / "modules").glob("*/routes.py"),
    *(ROOT / "app" / "collectors").glob("*.py"),
)
ALLOWED_LOWERCASE_BINDINGS = {
    "analysis_bp", "audit_log", "bp", "blueprint", "events_bp", "config_bp", "data_bp",
    "log", "logger", "metrics_bp", "modules_bp", "notices_bp",
    "polling_bp", "segment_bp", "smart_capture_bp", "ModuleLoaderFactory",
}
PROCESS_REGISTRY_ALLOWLIST = {
    "app/config.py": "module configuration keys form a process-wide schema catalog",
    "app/analyzer.py": "the analyzer threshold profile is a process-wide calculation catalog",
    "app/i18n/__init__.py": "translations are a process-wide immutable-at-request-time catalog",
    "app/theme_registry.py": "theme metadata is a process-wide catalog",
    "app/drivers/registry.py": "driver classes form a process-wide plugin catalog",
}
FORBIDDEN_WEB_EXPORTS = {
    "app", "init_config", "init_storage", "init_collector", "init_collectors",
    "init_modules", "setup_module_templates",
    "_build_metric_ranges", "_build_home_snr_display_context", "_build_home_modulation_context",
    "_build_capacity_context", "_snr_channel_family", "_power_metric_health", "_snr_metric_health",
    "_get_lang", "_get_setup_lang", "_get_tz_name", "_localize_timestamps", "_valid_date",
    "_build_theme_collections", "_check_for_update", "_version_newer", "_UPDATE_CACHE_TTL",
}


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _assigned_names(node):
    targets = node.targets if isinstance(node, ast.Assign) else (node.target,)
    return [target.id for target in targets if isinstance(target, ast.Name)]


def test_guard_scope_excludes_documented_process_registries():
    guarded = {str(path.relative_to(ROOT)) for path in GUARDED_FILES}
    assert guarded.isdisjoint(PROCESS_REGISTRY_ALLOWLIST)


def test_guarded_modules_have_no_global_or_nonlocal_statements():
    violations = []
    for path in GUARDED_FILES:
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_factory_is_the_only_flask_constructor():
    calls = []
    for path in (ROOT / "app").rglob("*.py"):
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                module = getattr(node, "module", "") or ""
                imports = {a.name for a in node.names} if isinstance(node, ast.Import) else {module}
                if isinstance(node, ast.ImportFrom) and module in {"", "app"}:
                    imports.update("app." + a.name for a in node.names)
                if path.relative_to(ROOT).as_posix() not in {"app/app_factory.py", "app/registration.py"}:
                    assert "app.web" not in imports and "web" not in imports, path
                if path.name in {"tz.py", "theme_registry.py", "version.py"}:
                    assert imports.isdisjoint({"flask", "app.runtime", "runtime", "app.app_factory"}), path
            if path.name == "tz.py" and isinstance(node, ast.Name):
                assert node.id not in {"current_app", "request", "current_runtime", "get_runtime"}
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Flask":
                calls.append(path.relative_to(ROOT).as_posix())
    assert sorted(calls) == [
        "app/app_factory.py",
        "app/app_factory.py",
        "app/registration.py",
    ]


def test_guarded_modules_have_no_lowercase_state_bindings():
    violations = []
    for path in GUARDED_FILES:
        for node in _tree(path).body:
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            for name in _assigned_names(node):
                if (
                    name.startswith("__")
                    or name.isupper()
                    or name in ALLOWED_LOWERCASE_BINDINGS
                ):
                    continue
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{name}")
    assert violations == []


def test_web_has_no_legacy_application_or_initializer_exports(app, monkeypatch):
    assert FORBIDDEN_WEB_EXPORTS.isdisjoint(vars(web).keys() | vars(web_auth).keys())
    assert web.require_auth is web_auth.require_auth
    with app.app_context():
        runtime = current_runtime()
        for name in ("storage", "config_manager", "modem_collector", "collectors", "module_loader", "on_config_changed"):
            marker = object()
            monkeypatch.setattr(runtime, name, marker)
            assert getattr(web, "get_" + name)() is marker
        web.set_last_manual_poll(12.5)
        assert web.get_last_manual_poll() == runtime.get_last_manual_poll() == 12.5
        web.update_state(analysis={"health": "good"}, speedtest_latest={"value": 1})
        snapshot = web.get_state()
        assert snapshot == runtime.get_state() and snapshot is not runtime.get_state()
        snapshot["error"] = "external"
        assert runtime.get_state()["error"] is None
        web.reset_modem_state()
        assert runtime.get_state()["analysis"] is None
        assert runtime.get_state()["speedtest_latest"] == {"value": 1}
        web.clear_speedtest_latest()
        assert runtime.get_state()["speedtest_latest"] is None
