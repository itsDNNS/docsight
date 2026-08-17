"""Immutable planning and atomic application of DOCSight registrations."""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from flask import Blueprint, Flask
from jinja2 import ChoiceLoader, FileSystemLoader

from .i18n import _TRANSLATIONS


log = logging.getLogger("docsis.modules")


class RegistrationError(RuntimeError):
    """A registration plan is invalid and must not be applied."""


@dataclass(frozen=True)
class PlannedRule:
    rule: str
    endpoint: str
    methods: tuple[str, ...]
    source: str
    view: Callable[..., Any] | None = field(default=None, compare=False, repr=False)

    def __post_init__(self) -> None:
        methods = {method.upper() for method in self.methods}
        if "GET" in methods:
            methods.add("HEAD")
        object.__setattr__(self, "methods", tuple(sorted(methods | {"OPTIONS"})))


@dataclass(frozen=True)
class PlannedBlueprint:
    name: str
    source: str
    blueprint: Blueprint = field(compare=False, repr=False)
    rules: tuple[PlannedRule, ...] = ()
    registered_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class ModuleContribution:
    """One module's complete, resolved contribution set."""

    module_id: str
    source: str
    version: str
    builtin: bool
    info: Any = field(compare=False, repr=False)
    config: tuple[tuple[str, Any], ...] = field(default=(), repr=False)
    secret_keys: tuple[str, ...] = field(default=(), repr=False)
    private_keys: tuple[str, ...] = field(default=(), repr=False)
    i18n_catalogs: tuple[tuple[str, tuple[tuple[str, Any], ...]], ...] = ()
    template_paths: tuple[tuple[str, str], ...] = ()
    template_dir: str | None = field(default=None, compare=False, repr=False)
    collector_class: type | None = field(default=None, compare=False, repr=False)
    publisher_class: type | None = field(default=None, compare=False, repr=False)
    thresholds_data: dict[str, object] | None = field(default=None, compare=False, repr=False)
    theme_data: dict[str, object] | None = field(default=None, compare=False, repr=False)
    has_css: bool = False
    has_js: bool = False


@dataclass(frozen=True)
class RegistrationPlan:
    """The ordered, immutable complete registration contract."""

    rules: tuple[PlannedRule, ...] = ()
    blueprints: tuple[PlannedBlueprint, ...] = ()
    modules: tuple[ModuleContribution, ...] = ()
    module_secret_keys: tuple[str, ...] = field(default=(), repr=False)
    module_secret_owners: tuple[tuple[str, str], ...] = field(default=(), repr=False)
    builtin_private_keys: tuple[str, ...] = field(default=(), repr=False)

    def combined(self, *others: "RegistrationPlan") -> "RegistrationPlan":
        plans = (self, *others)
        return RegistrationPlan(
            rules=tuple(item for plan in plans for item in plan.rules),
            blueprints=tuple(item for plan in plans for item in plan.blueprints),
            modules=tuple(item for plan in plans for item in plan.modules),
            module_secret_keys=tuple(sorted({item for plan in plans for item in plan.module_secret_keys})),
            module_secret_owners=tuple(sorted(dict(
                item for plan in plans for item in plan.module_secret_owners
            ).items())),
            builtin_private_keys=tuple(sorted({
                item for plan in plans for item in plan.builtin_private_keys
            })),
        )


def probe_blueprint(blueprint: Blueprint, *, source: str) -> PlannedBlueprint:
    """Preflight a blueprint on an isolated app."""
    tree, pending = [], [blueprint]
    while pending:
        item = pending.pop()
        tree.append(item)
        pending.extend(child for child, _options in getattr(item, "_blueprints", ()))
    previous = {
        item: (getattr(item, "_got_registered_once", False), item.cli.name)
        for item in tree
    }
    probe = Flask("registration.probe", static_folder=None)
    try:
        probe.register_blueprint(blueprint)
        rules = tuple(
            PlannedRule(
                rule.rule, rule.endpoint, tuple(rule.methods), source,
                probe.view_functions.get(rule.endpoint),
            )
            for rule in probe.url_map.iter_rules()
        )
        names = tuple(probe.blueprints)
    except Exception as exc:
        raise RegistrationError(
            f"Blueprint '{blueprint.name}' from {source} failed preflight: {type(exc).__name__}"
        ) from exc
    finally:
        for item, (was_registered, cli_name) in previous.items():
            item._got_registered_once = was_registered
            item.cli.name = cli_name
    return PlannedBlueprint(blueprint.name, source, blueprint, rules, names)


def existing_rules(app: Flask) -> tuple[PlannedRule, ...]:
    return tuple(
        PlannedRule(
            rule.rule, rule.endpoint, tuple(rule.methods), "existing",
            app.view_functions.get(rule.endpoint),
        )
        for rule in app.url_map.iter_rules()
    )


def validate_plan(
    plan: RegistrationPlan,
    *,
    existing: Sequence[PlannedRule] = (),
    existing_blueprints: Sequence[str] = (),
) -> None:
    """Reject all identity, ownership, endpoint, blueprint and route collisions."""
    errors: list[str] = []
    ids: set[str] = set()
    for module in plan.modules:
        if module.module_id in ids:
            errors.append(f"duplicate module id '{module.module_id}'")
        ids.add(module.module_id)
    claims = (
        ("config key", ((key, module.module_id) for module in plan.modules for key, _ in module.config)),
        ("secret ownership", (
            *((key, module.module_id) for module in plan.modules for key in module.secret_keys),
            *plan.module_secret_owners,
        )),
    )
    for kind, values in claims:
        owners: dict[str, str] = {}
        for key, owner in values:
            if key in owners and owners[key] != owner:
                errors.append(f"{kind} collision between {owners[key]} and {owner}")
            owners.setdefault(key, owner)
    names = {name: "existing" for name in existing_blueprints}
    for blueprint in plan.blueprints:
        for name in blueprint.registered_names or (blueprint.name,):
            if name in names:
                errors.append(
                    f"blueprint name collision '{name}' between {names[name]} and {blueprint.source}"
                )
            names.setdefault(name, blueprint.source)
    rules = (*existing, *plan.rules, *(
        rule for blueprint in plan.blueprints for rule in blueprint.rules
    ))
    endpoints: dict[str, PlannedRule] = {}
    routes: dict[tuple[str, str], PlannedRule] = {}
    for rule in rules:
        owner = endpoints.get(rule.endpoint)
        if owner and not (owner.source == rule.source and owner.view is rule.view):
            errors.append(
                f"endpoint collision '{rule.endpoint}' between {owner.source} and {rule.source}"
            )
        endpoints.setdefault(rule.endpoint, rule)
        for method in (method for method in rule.methods if method != "OPTIONS"):
            key, owner = (rule.rule, method), routes.get((rule.rule, method))
            same = owner and owner.source == rule.source and owner.endpoint == rule.endpoint and owner.view is rule.view
            if owner and not same:
                errors.append(
                    f"route/method collision '{rule.rule}' {method} between {owner.source} and {rule.source}"
                )
            routes.setdefault(key, rule)
    if errors:
        raise RegistrationError("; ".join(sorted(set(errors))))


def apply_module_i18n(module_id: str, catalogs: dict[str, dict[str, Any]]) -> None:
    """Merge validated, namespaced catalogs with English fallback."""
    if not catalogs:
        return
    fallback = catalogs.get("en", {})
    target_langs = set(_TRANSLATIONS) | set(catalogs)
    if fallback:
        target_langs.add("en")
    for lang in sorted(target_langs):
        data = dict(fallback)
        if lang != "en":
            data.update(catalogs.get(lang, {}))
        elif "en" in catalogs:
            data = catalogs["en"]
        elif not data:
            continue
        _TRANSLATIONS.setdefault(lang, {})
        merged = 0
        for key, value in data.items():
            if key.startswith("_"):
                continue
            _TRANSLATIONS[lang][f"{module_id}.{key}"] = value
            merged += 1
            _TRANSLATIONS[lang].setdefault(key, value)
        log.debug(
            "Merged %d i18n keys for module '%s' lang '%s'",
            merged, module_id, lang,
        )


def register_plan(app: Flask, plan: RegistrationPlan) -> None:
    """Validate and atomically apply a complete plan exactly once."""
    from . import analyzer, config as cfg
    from .module_config_registry import register_module_config

    applied = app.extensions.get("docsight_applied_registration_plans", ())
    if any(plan is previous_plan for previous_plan in applied):
        raise RegistrationError("Registration plan has already been applied")
    previous = app.extensions.get("docsight_registration_plan", RegistrationPlan())
    validate_plan(RegistrationPlan(
        modules=previous.modules + plan.modules,
        module_secret_owners=previous.module_secret_owners + plan.module_secret_owners,
    ))
    validate_plan(
        plan, existing=existing_rules(app), existing_blueprints=tuple(app.blueprints)
    )
    for rule in plan.rules:
        app.add_url_rule(
            rule.rule, endpoint=rule.endpoint, view_func=rule.view,
            methods=[method for method in rule.methods if method != "OPTIONS"],
        )
    for blueprint in plan.blueprints:
        app.register_blueprint(blueprint.blueprint)

    complete = previous.combined(plan)
    if any((complete.modules, complete.module_secret_keys,
            complete.module_secret_owners, complete.builtin_private_keys)):
        cfg.set_module_secret_registry(
            set(complete.module_secret_keys), dict(complete.module_secret_owners)
        )
        cfg.PRIVATE_KEYS.update(complete.builtin_private_keys)
    template_loaders, template_dirs = [app.jinja_loader], set()
    for contribution in plan.modules:
        if contribution.config:
            register_module_config(
                dict(contribution.config), contribution.module_id, contribution.builtin,
                list(contribution.secret_keys), list(contribution.private_keys),
            )
        apply_module_i18n(contribution.module_id, {
            lang: dict(strings) for lang, strings in contribution.i18n_catalogs
        })
        info = contribution.info
        info.template_paths = dict(contribution.template_paths)
        for name in (
            "collector_class", "publisher_class", "thresholds_data",
            "theme_data", "has_css", "has_js",
        ):
            setattr(info, name, getattr(contribution, name))
        if contribution.thresholds_data is not None:
            analyzer.set_thresholds(
                contribution.thresholds_data,
                profile_id=contribution.module_id,
                profile_version=contribution.version,
            )
        directory = contribution.template_dir
        if directory and directory not in template_dirs:
            template_loaders.append(FileSystemLoader(directory))
            template_dirs.add(directory)
    if len(template_loaders) > 1:
        app.jinja_loader = ChoiceLoader(template_loaders)
    app.extensions["docsight_registration_plan"] = complete
    app.extensions["docsight_applied_registration_plans"] = (*applied, plan)


def apply_plan(app: Flask, plan: RegistrationPlan) -> None:
    """Compatibility adapter for the sole registrar."""
    register_plan(app, plan)


def build_core_plan() -> RegistrationPlan:
    from .blueprints import core_blueprints
    from .web import CORE_ROUTES

    return RegistrationPlan(
        rules=tuple(
            PlannedRule(spec.rule, spec.endpoint, spec.methods, "core", spec.view)
            for spec in CORE_ROUTES
        ),
        blueprints=tuple(
            probe_blueprint(blueprint, source="core-blueprint")
            for blueprint in core_blueprints()
        ),
    )


def canonical_manifest(app: Flask, module_loader=None) -> dict[str, object]:
    """Return manifest v1 using stable public identifiers only."""
    plan = app.extensions.get("docsight_registration_plan")
    sources = {}
    if isinstance(plan, RegistrationPlan):
        sources.update({(rule.endpoint, rule.rule): rule.source for rule in plan.rules})
        for blueprint in plan.blueprints:
            sources.update({
                (rule.endpoint, rule.rule): rule.source for rule in blueprint.rules
            })
    routes = sorted(({
        "endpoint": rule.endpoint,
        "rule": rule.rule,
        "methods": sorted(rule.methods),
        "source": sources.get((rule.endpoint, rule.rule), "framework"),
    } for rule in app.url_map.iter_rules()), key=lambda item: (
        item["rule"], item["endpoint"], item["methods"]
    ))
    modules = [] if not hasattr(module_loader, "get_modules") else sorted(({
        "id": module.id,
        "version": module.version,
        "type": module.type,
        "builtin": bool(module.builtin),
        "enabled": bool(module.enabled),
        "accepted": bool(module.enabled and not module.error),
    } for module in module_loader.get_modules()), key=lambda item: item["id"])
    return {
        "version": 1, "blueprints": sorted(app.blueprints),
        "routes": routes, "modules": modules,
    }


def manifest_fingerprint(manifest: dict[str, object]) -> str:
    payload = json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()
