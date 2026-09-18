"""Modem driver registry with application-owned community contributions."""

from __future__ import annotations

import importlib
from copy import deepcopy

from .base import ModemDriver
from ..types import DriverHints


class UnavailableDriver(ModemDriver):
    """Keep polling fail-safe active while the configured driver is unavailable."""

    def login(self):
        raise RuntimeError("Configured modem driver is unavailable; check Extensions and restart")


class DriverRegistry:
    """Built-in drivers and the community drivers accepted by one application."""

    def __init__(self):
        self._builtin: dict[str, str] = {}
        self._community: dict[str, type[ModemDriver]] = {}
        self._display_names: dict[str, str] = {}
        self._hints: dict[str, DriverHints] = {}
        self._init_kwargs: dict[str, dict[str, object]] = {}

    def register_builtin(
        self,
        type_key: str,
        class_path: str,
        display_name: str,
        hints: DriverHints | None = None,
        init_kwargs: dict[str, object] | None = None,
    ) -> None:
        self._builtin[type_key] = class_path
        self._display_names[type_key] = display_name
        if hints:
            self._hints[type_key] = hints
        if init_kwargs:
            self._init_kwargs[type_key] = dict(init_kwargs)

    def copy_builtins(self) -> DriverRegistry:
        registry = DriverRegistry()
        registry._builtin = dict(self._builtin)
        registry._display_names = {k: self._display_names[k] for k in self._builtin}
        registry._hints = {k: deepcopy(v) for k, v in self._hints.items() if k in self._builtin}
        registry._init_kwargs = deepcopy(self._init_kwargs)
        return registry

    def register_module_driver(
        self, type_key: str, driver_class: type[ModemDriver],
        display_name: str, hints: DriverHints | None = None,
    ) -> None:
        if type_key in self._community:
            raise ValueError("Driver key is already registered")
        self._community[type_key] = driver_class
        self._display_names[type_key] = display_name
        if hints:
            self._hints[type_key] = deepcopy(hints)

    def load_driver(self, modem_type: str, url: str, user: str, password: str) -> ModemDriver:
        if modem_type in self._community:
            return self._community[modem_type](url, user, password)
        qualified = self._builtin.get(modem_type)
        if not qualified:
            supported = ", ".join(sorted(self.get_all_type_keys()))
            raise ValueError(
                f"Unknown modem_type '{modem_type}'. Supported: {supported}"
            )
        module_path, class_name = qualified.rsplit(".", 1)
        mod = importlib.import_module(module_path)
        cls = getattr(mod, class_name)
        kwargs = self._init_kwargs.get(modem_type, {})
        return cls(url, user, password, **kwargs)

    def load_for_polling(self, modem_type, url, user, password) -> ModemDriver:
        try:
            return self.load_driver(modem_type, url, user, password)
        except Exception:
            return UnavailableDriver(url, user, password)

    def get_available_drivers(self) -> list[tuple[str, str]]:
        all_keys = self.get_all_type_keys()
        return sorted(
            [(k, self._display_names.get(k, k)) for k in all_keys],
            key=lambda x: x[1],
        )

    def get_all_type_keys(self) -> set[str]:
        return set(self._builtin) | set(self._community)

    def get_driver_hints(self) -> dict[str, DriverHints]:
        """Return UI hints for all registered drivers, keyed by type_key."""
        return deepcopy(self._hints)

    def is_builtin(self, modem_type: str) -> bool:
        return (
            isinstance(modem_type, str)
            and modem_type in self._builtin
            and modem_type not in self._community
        )

    def has_driver(self, modem_type: str) -> bool:
        return modem_type in self._builtin or modem_type in self._community
