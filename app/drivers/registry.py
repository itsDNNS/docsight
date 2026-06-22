"""Built-in modem driver registry."""

from __future__ import annotations

import importlib

from .base import ModemDriver
from ..types import DriverHints


class DriverRegistry:
    """Central registry for DOCSight's built-in modem drivers."""

    def __init__(self):
        self._builtin: dict[str, str] = {}
        self._display_names: dict[str, str] = {}
        self._hints: dict[str, DriverHints] = {}

    def register_builtin(self, type_key: str, class_path: str, display_name: str, hints: DriverHints | None = None) -> None:
        self._builtin[type_key] = class_path
        self._display_names[type_key] = display_name
        if hints:
            self._hints[type_key] = hints

    def load_driver(self, modem_type: str, url: str, user: str, password: str) -> ModemDriver:
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
        return set(self._builtin)

    def get_driver_hints(self) -> dict[str, DriverHints]:
        """Return UI hints for all registered drivers, keyed by type_key."""
        return dict(self._hints)

    def has_driver(self, modem_type: str) -> bool:
        return modem_type in self._builtin
