"""Keep Flask applications and their mutable state instance-owned."""

import ast
from pathlib import Path

import app.web as web


ROOT = Path(__file__).resolve().parents[2]
GUARDED_FILES = (
    ROOT / "app" / "web.py",
    ROOT / "app" / "app_factory.py",
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
        if not path.exists():
            continue
        for node in ast.walk(_tree(path)):
            if isinstance(node, (ast.Global, ast.Nonlocal)):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_factory_is_the_only_flask_constructor():
    calls = []
    for path in (ROOT / "app").rglob("*.py"):
        for node in ast.walk(_tree(path)):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "Flask":
                calls.append(path.relative_to(ROOT).as_posix())
    assert calls == ["app/app_factory.py"]


def test_guarded_modules_have_no_lowercase_state_bindings():
    violations = []
    for path in GUARDED_FILES:
        if not path.exists():
            continue
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


def test_web_has_no_legacy_application_or_initializer_exports():
    assert FORBIDDEN_WEB_EXPORTS.isdisjoint(vars(web))
