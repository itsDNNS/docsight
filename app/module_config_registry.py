"""Preflight and application of module-owned configuration schema."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from . import config as _cfg
from .module_registry import ModuleInfo


def register_module_config(
    config_defaults: dict[str, Any],
    module_id: str | None = None,
    builtin: bool = False,
    config_secrets: list[str] | None = None,
    config_private: list[str] | None = None,
) -> set[str]:
    """Apply prevalidated defaults and classification to the process schema."""
    secret_keys = set(config_secrets or [])
    private_keys = set(config_private or []) if builtin else set()
    registered: set[str] = set()
    for key, value in config_defaults.items():
        if key in secret_keys and not builtin and _cfg.MODULE_SECRET_OWNERS.get(key) != module_id:
            continue
        if key in _cfg.DEFAULTS:
            if key in private_keys:
                _cfg.PRIVATE_KEYS.add(key)
            continue
        if not builtin and key in (_cfg.SECRET_KEYS | _cfg.PRIVATE_KEYS | _cfg.HASH_KEYS):
            continue
        _cfg.DEFAULTS[key] = value
        registered.add(key)
        if key in secret_keys and builtin:
            _cfg.SECRET_KEYS.add(key)
        if key in private_keys:
            _cfg.PRIVATE_KEYS.add(key)
        if _cfg.is_secret_key(key):
            continue
        if isinstance(value, bool):
            _cfg.BOOL_KEYS.add(key)
        elif isinstance(value, int):
            _cfg.INT_KEYS.add(key)
    return registered


def evaluate_module_secret_ownership(
    modules: list[ModuleInfo],
) -> tuple[set[str], dict[str, str], dict[str, str]]:
    """Return reserved keys, valid owners, and redacted ownership errors."""
    protected = set(_cfg.CORE_CONFIG_KEYS) | _cfg.SECRET_KEYS | _cfg.HASH_KEYS | _cfg.PRIVATE_KEYS
    for module in modules:
        if module.builtin:
            protected.update(module.config)
    secret_claims: dict[str, list[ModuleInfo]] = defaultdict(list)
    config_claims: dict[str, list[ModuleInfo]] = defaultdict(list)
    for module in modules:
        if module.builtin:
            continue
        for key in module.config:
            config_claims[key].append(module)
        for key in module.config_secrets:
            secret_claims[key].append(module)
    reserved = {key for key in secret_claims if key not in protected}
    owners: dict[str, str] = {}
    errors: dict[str, str] = {}
    for key, claimants in secret_claims.items():
        if key in protected:
            for module in claimants:
                errors[module.id] = "Module secret declaration conflicts with protected configuration"
            continue
        users = config_claims.get(key, [])
        if len(claimants) != 1 or len(users) != 1 or users[0].id != claimants[0].id:
            for module in [*claimants, *users]:
                errors[module.id] = "Module secret ownership conflict"
            continue
        owners[key] = claimants[0].id
    return reserved, owners, errors


def reserve_module_secrets(modules: list[ModuleInfo]) -> None:
    """Compatibility adapter for applying preflighted secret ownership."""
    reserved, owners, errors = evaluate_module_secret_ownership(modules)
    for module in modules:
        if module.id in errors:
            module.error = errors[module.id]
    _cfg.set_module_secret_registry(reserved, owners)


def evaluate_module_config_ownership(modules: list[ModuleInfo]) -> dict[str, str]:
    """Return redacted errors for ambiguous community config ownership."""
    protected = set(_cfg.CORE_CONFIG_KEYS)
    protected.update(key for module in modules if module.builtin for key in module.config)
    claims: dict[str, list[ModuleInfo]] = defaultdict(list)
    errors: dict[str, str] = {}
    for module in modules:
        if module.builtin or not module.enabled:
            continue
        for key in module.config:
            claims[key].append(module)
            if key in protected:
                errors[module.id] = "Module config ownership conflicts with protected configuration"
    for claimants in claims.values():
        if len(claimants) > 1:
            for module in claimants:
                errors[module.id] = "Module config ownership conflict"
    return errors
