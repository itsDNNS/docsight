"""Modem driver abstractions."""

from .registry import DriverRegistry

driver_registry = DriverRegistry()

# Register built-in drivers
driver_registry.register_builtin("fritzbox", "app.drivers.fritzbox.FritzBoxDriver", "AVM FRITZ!Box",
                                 hints={"default_url": "http://192.168.178.1", "default_user": "admin"})
driver_registry.register_builtin("tc4400", "app.drivers.tc4400.TC4400Driver", "Technicolor TC4400",
                                 hints={"default_url": "http://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("ultrahub7", "app.drivers.ultrahub7.UltraHub7Driver", "Vodafone Ultra Hub 7",
                                 hints={"username_required": False})
driver_registry.register_builtin("vodafone_station", "app.drivers.vodafone_station.VodafoneStationDriver", "Vodafone Station",
                                 hints={"default_url": "http://192.168.0.1", "default_user": "admin"})
driver_registry.register_builtin("ch7465", "app.drivers.ch7465.CH7465Driver", "Compal CH7465 (Connect Box)",
                                 hints={"default_url": "http://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("ch7465_play", "app.drivers.ch7465_play.CH7465PlayDriver",
                                 "Compal CH7465 (Play/UPC)",
                                 hints={"default_url": "http://192.168.0.1", "username_required": False})
driver_registry.register_builtin("cm3000", "app.drivers.cm3000.CM3000Driver", "Netgear CM3000",
                                 hints={"default_url": "http://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("cm3500", "app.drivers.cm3500.CM3500Driver", "Arris CM3500B",
                                 hints={"default_url": "https://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("surfboard", "app.drivers.surfboard.SurfboardDriver",
                                 "Arris SURFboard (S33/S34/SB8200)",
                                 hints={"default_url": "https://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("cm8200", "app.drivers.cm8200.CM8200Driver",
                                 "Arris Touchstone CM8200A",
                                 hints={"default_url": "https://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("hitron", "app.drivers.hitron.HitronDriver",
                                 "Hitron CODA-56",
                                 hints={"default_url": "http://192.168.100.1", "credentials_required": False})
driver_registry.register_builtin("sagemcom", "app.drivers.sagemcom.SagemcomDriver",
                                 "Sagemcom F@st 3896",
                                 hints={"default_url": "http://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("generic", "app.drivers.generic.GenericDriver", "Generic Router (No DOCSIS)",
                                 hints={"credentials_required": False})


def load_driver(modem_type, url, user, password):
    """Backward-compatible wrapper around driver_registry.load_driver()."""
    return driver_registry.load_driver(modem_type, url, user, password)
