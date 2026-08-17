"""Module discovery orchestration and compatibility facade."""

import logging
import os  # Compatibility: callers patch the shared filesystem module here.

# Public imports below intentionally preserve the legacy module-loader facade.
from app import module_registry as _module_registry
from app.builtin_modules import BUILTIN_MODULE_DIRS, BUILTIN_PYTHON_CONTRIBUTIONS
from app.manifest_contract import ID_PATTERN, VALID_CONTRIBUTES
from app.module_config_registry import (
    evaluate_module_config_ownership,
    evaluate_module_secret_ownership,
    register_module_config,
)
from app.module_contributions import (
    _PROTECTED_API_PREFIXES, _PROTECTED_ROUTES,
    _read_json_contribution,
    attach_builtin_python_contributions, load_module_collector,
    load_module_publisher, load_module_routes, merge_module_i18n,
    module_static_endpoint, module_static_url,
    resolve_module_contribution,
    setup_module_static, setup_module_templates, validate_theme,
    validate_thresholds,
)
from app.module_registry import (
    ManifestError,
    ModuleInfo,
    ModuleRegistryError,
    discover_modules,
    validate_manifest,
)
from app.registration import (
    RegistrationError,
    RegistrationPlan, existing_rules,
    register_plan, validate_plan,
)
from app.theme_registry import BUILTIN_THEMES
from app.threshold_profiles import BUILTIN_THRESHOLD_PROFILES


log = logging.getLogger("docsis.modules")


def discover_builtin_modules(
    builtin_base_path: str, disabled_ids: set[str] | None = None
) -> list[ModuleInfo]:
    try:
        return _module_registry.discover_builtin_modules(
            builtin_base_path,
            disabled_ids=disabled_ids,
            module_dirs=BUILTIN_MODULE_DIRS,
        )
    except ModuleRegistryError as exc:
        raise RegistrationError(str(exc)) from exc


def discover_builtin_theme_modules(
    disabled_ids: set[str] | None = None,
) -> list[ModuleInfo]:
    try:
        return _module_registry.discover_builtin_theme_modules(
            disabled_ids=disabled_ids,
            themes=BUILTIN_THEMES,
        )
    except ModuleRegistryError as exc:
        raise RegistrationError(str(exc)) from exc


def discover_builtin_threshold_modules(
    disabled_ids: set[str] | None = None,
) -> list[ModuleInfo]:
    try:
        return _module_registry.discover_builtin_threshold_modules(
            disabled_ids=disabled_ids,
            profiles=BUILTIN_THRESHOLD_PROFILES,
        )
    except ModuleRegistryError as exc:
        raise RegistrationError(str(exc)) from exc


class ModuleLoader:
    """Discover modules and assemble their complete validated registration plan."""

    def __init__(self, app, search_paths=None, disabled_ids=None, builtin_base_path=None):
        self._app = app
        self._search_paths = search_paths or []
        self._disabled_ids = disabled_ids or set()
        self._builtin_base_path = builtin_base_path
        self._modules: list[ModuleInfo] = []
        self._registration_plan = RegistrationPlan()

    def load_all(self) -> list[ModuleInfo]:
        """Discover, resolve, and deterministically accept complete module plans."""
        modules: list[ModuleInfo] = []
        if self._builtin_base_path:
            modules.extend(discover_builtin_modules(
                self._builtin_base_path, disabled_ids=self._disabled_ids,
            ))
            modules.extend(discover_builtin_threshold_modules(self._disabled_ids))
            modules.extend(discover_builtin_theme_modules(self._disabled_ids))
        modules.extend(discover_modules(
            search_paths=self._search_paths, disabled_ids=self._disabled_ids,
            known_ids={mod.id for mod in modules},
        ))
        self._modules = modules
        builtin_ids = [mod.id for mod in modules if mod.builtin]
        if len(builtin_ids) != len(set(builtin_ids)):
            raise RegistrationError("Duplicate built-in module id")
        _reserved, _owners, ownership_errors = evaluate_module_secret_ownership(modules)
        config_errors = evaluate_module_config_ownership(modules)
        for mod in modules:
            mod.error = ownership_errors.get(mod.id) or config_errors.get(mod.id)
        resolved = []
        for mod in modules:
            if mod.error:
                if mod.builtin:
                    raise RegistrationError(
                        f"Built-in module {mod.id} failed ownership validation"
                    )
                continue
            if not mod.enabled:
                if not mod.builtin and mod.type == "theme" and "theme" in mod.contributes:
                    try:
                        mod.theme_data = _read_json_contribution(
                            mod.path, mod.contributes["theme"], "theme", validate_theme
                        )
                    except Exception as exc:
                        mod.error = (
                            str(exc) if isinstance(exc, ManifestError)
                            else "theme contribution is invalid"
                        )
                        log.warning("Module '%s': disabled theme preview rejected", mod.id)
                log.info("Module '%s' is disabled, skipping load", mod.id)
                continue
            try:
                resolved.append(resolve_module_contribution(mod))
            except Exception as exc:
                if mod.builtin:
                    raise RegistrationError(
                        f"Built-in module {mod.id} failed contribution preflight: "
                        f"{type(exc).__name__}"
                    ) from exc
                mod.error = str(exc)
                log.error("Module '%s' failed contribution preflight", mod.id)
        accepted = self._validate_resolved(resolved)
        accepted_ids = {item.module_id for item, _http in accepted}
        registry_modules = [
            mod for mod in modules
            if mod.id in accepted_ids or not mod.enabled or mod.id in ownership_errors
        ]
        secret_keys, secret_owners, _errors = evaluate_module_secret_ownership(
            registry_modules
        )
        http = RegistrationPlan().combined(*(plan for _item, plan in accepted))
        self._registration_plan = RegistrationPlan(
            rules=http.rules, blueprints=http.blueprints,
            modules=tuple(item for item, _http in accepted),
            module_secret_keys=tuple(sorted(secret_keys)),
            module_secret_owners=tuple(sorted(secret_owners.items())),
            builtin_private_keys=tuple(sorted(
                key for mod in modules if mod.builtin for key in mod.config_private
            )),
        )
        plan = self._registration_plan
        if (
            any((plan.rules, plan.blueprints, plan.modules, plan.module_secret_keys,
                 plan.builtin_private_keys))
            and not self._app.extensions.get("docsight_registration_deferred", False)
        ):
            register_plan(self._app, plan)
        enabled = [mod for mod in self._modules if mod.enabled and not mod.error]
        log.info(
            "Module loading complete: %d discovered, %d enabled, %d failed",
            len(self._modules), len(enabled),
            len([mod for mod in self._modules if mod.error]),
        )
        return self._modules

    def _validate_resolved(self, resolved):
        base = self._app.extensions.get(
            "docsight_registration_base_plan", RegistrationPlan()
        )
        accepted = []
        for item, http in resolved:
            candidate = base.combined(
                *(current_http for _current, current_http in accepted), http,
                RegistrationPlan(modules=tuple(
                    current for current, _current_http in accepted
                ) + (item,)),
            )
            try:
                validate_plan(
                    candidate,
                    existing=existing_rules(self._app),
                    existing_blueprints=tuple(self._app.blueprints),
                )
            except RegistrationError as exc:
                if item.builtin:
                    raise RegistrationError(
                        f"Built-in module {item.module_id} has a registration collision"
                    ) from exc
                item.info.error = str(exc)
                continue
            accepted.append((item, http))
        return accepted

    @property
    def registration_plan(self) -> RegistrationPlan:
        return self._registration_plan

    def get_modules(self) -> list[ModuleInfo]:
        return list(self._modules)

    def get_enabled_modules(self) -> list[ModuleInfo]:
        return [mod for mod in self._modules if mod.enabled and not mod.error]

    def get_threshold_modules(self) -> list[ModuleInfo]:
        return [mod for mod in self._modules if "thresholds" in mod.contributes]

    def get_theme_modules(self) -> list[ModuleInfo]:
        return [mod for mod in self._modules if "theme" in mod.contributes]
