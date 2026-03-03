"""Modem driver abstractions."""

from .registry import DriverRegistry

driver_registry = DriverRegistry()

# Register built-in drivers
driver_registry.register_builtin("fritzbox", "app.drivers.fritzbox.FritzBoxDriver", "AVM FRITZ!Box")
driver_registry.register_builtin("tc4400", "app.drivers.tc4400.TC4400Driver", "Technicolor TC4400")
driver_registry.register_builtin("ultrahub7", "app.drivers.ultrahub7.UltraHub7Driver", "Vodafone Ultra Hub 7")
driver_registry.register_builtin("vodafone_station", "app.drivers.vodafone_station.VodafoneStationDriver", "Vodafone Station")
driver_registry.register_builtin("ch7465", "app.drivers.ch7465.CH7465Driver", "Unitymedia Connect Box (CH7465)")
driver_registry.register_builtin("cm3500", "app.drivers.cm3500.CM3500Driver", "Arris CM3500B")


def load_driver(modem_type, url, user, password):
    """Backward-compatible wrapper around driver_registry.load_driver()."""
    return driver_registry.load_driver(modem_type, url, user, password)
