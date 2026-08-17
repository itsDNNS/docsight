"""Regression contract for deterministic, atomic application registration."""

from __future__ import annotations

import ast
from dataclasses import FrozenInstanceError
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Blueprint, Flask

from app.registration import (
    ModuleContribution,
    PlannedBlueprint,
    PlannedRule,
    RegistrationError,
    RegistrationPlan,
    apply_plan,
    probe_blueprint,
    register_plan,
    validate_plan,
)


ROOT = Path(__file__).resolve().parents[2]


def _view():
    return "ok"


def _rule(rule: str, endpoint: str, source: str = "module:test") -> PlannedRule:
    return PlannedRule(rule, endpoint, ("GET",), source, _view)


@pytest.mark.parametrize(
    ("rules", "match"),
    [
        ((_rule("/one", "same", "module:a"), _rule("/two", "same", "module:b")), "endpoint"),
        ((_rule("/same", "one", "module:a"), _rule("/same", "two", "module:b")), "route/method"),
        (
            (
                _rule("/modules/a/static/<path:filename>", "module_static_a", "module-static:a"),
                _rule("/modules/a/static/<path:filename>", "module_static_b", "module-static:b"),
            ),
            "route/method",
        ),
        (
            (
                _rule("/modules/a/static/<path:filename>", "module_static_same", "module-static:a"),
                _rule("/modules/b/static/<path:filename>", "module_static_same", "module-static:b"),
            ),
            "endpoint",
        ),
    ],
)
def test_rule_collisions_are_rejected_before_apply(rules, match):
    app = Flask(__name__)
    before = tuple(app.url_map.iter_rules())

    with pytest.raises(RegistrationError, match=match):
        validate_plan(RegistrationPlan(rules=rules))

    assert tuple(app.url_map.iter_rules()) == before


def test_duplicate_blueprint_names_are_rejected_before_apply():
    left = Blueprint("duplicate", __name__)
    right = Blueprint("duplicate", __name__)
    plan = RegistrationPlan(
        blueprints=(
            PlannedBlueprint("duplicate", "module:a", left),
            PlannedBlueprint("duplicate", "module:b", right),
        )
    )

    with pytest.raises(RegistrationError, match="blueprint name"):
        validate_plan(plan)


def test_blueprint_probe_failure_does_not_mutate_target():
    target = Flask(__name__)
    before = (
        tuple(target.url_map.iter_rules()),
        dict(target.view_functions),
        dict(target.blueprints),
    )
    broken = Blueprint("broken", __name__)

    @broken.record
    def fail(_state):
        raise RuntimeError("registration exploded")

    with pytest.raises(RegistrationError, match="failed preflight"):
        probe_blueprint(broken, source="module:broken")

    assert tuple(target.url_map.iter_rules()) == before[0]
    assert target.view_functions == before[1]
    assert target.blueprints == before[2]


def test_probe_preserves_record_once_for_real_registration():
    calls = []
    blueprint = Blueprint("once", __name__)

    @blueprint.record_once
    def record_once(state):
        calls.append(state.app.name)

    planned = probe_blueprint(blueprint, source="module:once")
    target = Flask("registration-target")
    apply_plan(target, RegistrationPlan(blueprints=(planned,)))

    assert calls == ["registration.probe", "registration-target"]


def test_probe_restores_nested_blueprint_registration_state():
    parent = Blueprint("parent", __name__)
    child = Blueprint("child", __name__)

    @parent.cli.command("parent-command")
    def parent_command():
        pass

    @child.cli.command("child-command")
    def child_command():
        pass

    child.add_url_rule("/nested", "nested", _view)
    parent.register_blueprint(child)
    cli_names = parent.cli.name, child.cli.name

    planned = probe_blueprint(parent, source="module:nested")

    assert parent._got_registered_once is False
    assert child._got_registered_once is False
    assert (parent.cli.name, child.cli.name) == cli_names
    assert planned.registered_names == ("parent", "parent.child")


def test_productive_flask_registration_has_one_owner():
    violations = []
    for path in (ROOT / "app").rglob("*.py"):
        if path.name == "registration.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            receiver = node.func.value.id if isinstance(node.func.value, ast.Name) else ""
            local_blueprint_rule = node.func.attr == "add_url_rule" and (
                receiver in {"bp", "blueprint"} or receiver.endswith("_bp")
            )
            if node.func.attr in {"register_blueprint", "add_url_rule"} and not local_blueprint_rule:
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:{node.func.attr}")
            if node.func.attr == "register" and isinstance(node.func.value, ast.Name):
                if node.func.value.id in {"bp", "blueprint", "Blueprint"} or node.func.value.id.endswith("_bp"):
                    violations.append(f"{path.relative_to(ROOT)}:{node.lineno}:Blueprint.register")
    assert violations == []


@pytest.mark.parametrize(
    ("relative_path", "forbidden"),
    [
        ("app/registration.py", "app.module_loader"),
        ("app/module_registry.py", "app.registration"),
    ],
)
def test_registration_dependencies_have_no_reverse_imports(relative_path, forbidden):
    """Keep lower-level registration and discovery independent of the facade."""
    tree = ast.parse((ROOT / relative_path).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            base = f"app.{module}".rstrip(".") if node.level else module
            imported.add(base)
            if base == "app":
                imported.update(f"app.{alias.name}" for alias in node.names)
    assert forbidden not in imported


def test_manual_builtin_test_registrar_is_removed():
    matches = []
    for path in ROOT.rglob("*.py"):
        if path == Path(__file__):
            continue
        legacy_name = "register_" + "builtin_test_routes"
        if legacy_name in path.read_text(encoding="utf-8"):
            matches.append(path.relative_to(ROOT).as_posix())
    assert matches == []


def test_factory_calls_one_top_level_registrar():
    tree = ast.parse((ROOT / "app" / "app_factory.py").read_text(encoding="utf-8"))
    create_app = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "create_app"
    )
    calls = [
        node.func.id
        for node in ast.walk(create_app)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        and node.func.id in {"register_plan", "apply_plan", "apply_contributions"}
    ]
    assert calls == ["register_plan"]


@pytest.mark.parametrize("collision", ["module_id", "config", "secret"])
def test_non_http_plan_collisions_are_rejected_without_mutation(collision):
    app = Flask(__name__)
    before = (
        tuple(app.url_map.iter_rules()),
        dict(app.view_functions),
        dict(app.blueprints),
        dict(app.extensions),
    )
    left = ModuleContribution(
        "community.left", "community:left", "1.0", False, SimpleNamespace(),
        config=(("private_config_name", "private-value"),),
        secret_keys=("private_secret_name",),
    )
    right = ModuleContribution(
        "community.left" if collision == "module_id" else "community.right",
        "community:right", "1.0", False, SimpleNamespace(),
        config=(("private_config_name" if collision == "config" else "other", "value"),),
        secret_keys=(("private_secret_name",) if collision == "secret" else ("other_secret",)),
    )
    plan = RegistrationPlan(modules=(left, right))

    with pytest.raises(RegistrationError) as caught:
        register_plan(app, plan)

    assert before == (
        tuple(app.url_map.iter_rules()),
        dict(app.view_functions),
        dict(app.blueprints),
        dict(app.extensions),
    )
    assert "private_config_name" not in str(caught.value)
    assert "private_secret_name" not in str(caught.value)


def test_complete_plan_is_immutable_redacted_and_applied_once():
    from app import config as cfg

    contribution = ModuleContribution(
        "community.once", "community:once", "1.0", False, SimpleNamespace(),
        config=(("sensitive_config_name", "sensitive-config-value"),),
        secret_keys=("sensitive_config_name",),
    )
    plan = RegistrationPlan(
        modules=(contribution,),
        module_secret_keys=("sensitive_config_name",),
        module_secret_owners=(("sensitive_config_name", "community.once"),),
    )
    encoded = repr(plan)

    assert "sensitive_config_name" not in encoded
    assert "sensitive-config-value" not in encoded
    with pytest.raises(FrozenInstanceError):
        plan.modules = ()

    app = Flask(__name__)
    apply_once = RegistrationPlan(rules=(_rule("/once", "once"),))
    secret_registry = set(cfg.MODULE_SECRET_KEYS), dict(cfg.MODULE_SECRET_OWNERS)
    try:
        register_plan(app, apply_once)
        after_first = dict(app.extensions)
        with pytest.raises(RegistrationError, match="already been applied"):
            register_plan(app, apply_once)
        assert app.extensions == after_first
    finally:
        cfg.set_module_secret_registry(*secret_registry)
