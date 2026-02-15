"""Modem driver abstractions."""

import importlib
import logging

log = logging.getLogger("docsis.drivers")

DRIVER_REGISTRY = {
    "fritzbox": "app.drivers.fritzbox.FritzBoxDriver",
    "ultrahub7": "app.drivers.ultrahub7.UltraHub7Driver",
}

DRIVER_DISPLAY_NAMES = {
    "fritzbox": "AVM FRITZ!Box",
    "ultrahub7": "Vodafone Ultra Hub 7",
}


def load_driver(modem_type, url, user, password):
    """Instantiate a modem driver by type name."""
    qualified = DRIVER_REGISTRY.get(modem_type)
    if not qualified:
        supported = ", ".join(sorted(DRIVER_REGISTRY))
        raise ValueError(
            f"Unknown modem_type '{modem_type}'. Supported: {supported}"
        )
    module_path, class_name = qualified.rsplit(".", 1)
    mod = importlib.import_module(module_path)
    cls = getattr(mod, class_name)
    return cls(url, user, password)
