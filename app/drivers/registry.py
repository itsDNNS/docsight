"""Unified driver registry for built-in and module-contributed modem drivers."""

from __future__ import annotations

import importlib
import logging

from .base import ModemDriver
from ..types import DriverHints

log = logging.getLogger("docsis.drivers")


class DriverRegistry:
    """Central registry for all modem drivers (built-in and module-contributed).

    Built-in drivers are stored as qualified class paths (lazy-loaded).
    Module drivers are stored as already-loaded classes.
    """

    def __init__(self):
        self._builtin: dict[str, str] = {}
        self._module_drivers: dict[str, type[ModemDriver]] = {}
        self._display_names: dict[str, str] = {}
        self._hints: dict[str, DriverHints] = {}

    def register_builtin(self, type_key: str, class_path: str, display_name: str, hints: DriverHints | None = None) -> None:
        self._builtin[type_key] = class_path
        self._display_names[type_key] = display_name
        if hints:
            self._hints[type_key] = hints

    def register_module_driver(self, type_key: str, cls: type[ModemDriver], display_name: str, hints: DriverHints | None = None) -> None:
        self._module_drivers[type_key] = cls
        self._display_names[type_key] = display_name
        if hints:
            self._hints[type_key] = hints

    def load_driver(self, modem_type: str, url: str, user: str, password: str) -> ModemDriver:
        # Module drivers take priority (community can override/extend)
        if modem_type in self._module_drivers:
            cls = self._module_drivers[modem_type]
            return cls(url, user, password)

        qualified = self._builtin.get(modem_type)
        if not qualified:
            supported = ", ".join(sorted(self.get_all_type_keys()))
            raise ValueError(
                f"Unknown modem_type '{modem_type}'. Supported: {supported}"
            )
        module_path, class_name = qualified.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        return cls(url, user, password)

    def get_available_drivers(self) -> list[tuple[str, str]]:
        all_keys = self.get_all_type_keys()
        return sorted(
            [(k, self._display_names.get(k, k)) for k in all_keys],
            key=lambda x: x[1],
        )

    def get_all_type_keys(self) -> set[str]:
        return set(self._builtin) | set(self._module_drivers)

    def get_driver_hints(self) -> dict[str, DriverHints]:
        """Return UI hints for all registered drivers, keyed by type_key."""
        return dict(self._hints)

    def has_driver(self, modem_type: str) -> bool:
        return modem_type in self._builtin or modem_type in self._module_drivers

    def register_module_drivers(self, module_loader) -> None:
        for mod in module_loader.get_enabled_modules():
            if mod.driver_class and "driver" in mod.contributes:
                type_key = mod.id
                display_name = mod.name
                self.register_module_driver(type_key, mod.driver_class, display_name, hints=mod.hints)
                log.info("Registered module driver: %s (%s)", type_key, display_name)
