"""Modem driver abstractions."""

from .registry import DriverRegistry

driver_registry = DriverRegistry()

driver_registry.register_builtin("fritzbox", "app.drivers.fritzbox.FritzBoxDriver", "AVM FRITZ!Box",
                                 hints={"manufacturer": "AVM", "region": "DE · AT · CH", "default_url": "http://192.168.178.1", "default_user": "admin"})
driver_registry.register_builtin("tc4400", "app.drivers.tc4400.TC4400Driver", "Technicolor TC4400",
                                 hints={"manufacturer": "Technicolor", "default_url": "http://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("ultrahub7", "app.drivers.ultrahub7.UltraHub7Driver", "Vodafone Ultra Hub 7",
                                 hints={"manufacturer": "Vodafone", "region": "Vodafone DE", "username_required": False})
driver_registry.register_builtin("vodafone_station", "app.drivers.vodafone_station.VodafoneStationDriver", "Vodafone Station",
                                 hints={"manufacturer": "Vodafone", "region": "Vodafone DE", "default_url": "http://192.168.0.1", "default_user": "admin"})
driver_registry.register_builtin("ch7465", "app.drivers.ch7465.CH7465Driver", "Compal CH7465 (Connect Box)",
                                 hints={"manufacturer": "Compal", "region": "UPC · Unitymedia", "default_url": "http://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("ch7465_play", "app.drivers.ch7465.CH7465Driver",
                                 "Compal CH7465 (Play/UPC)",
                                 hints={"manufacturer": "Compal", "default_url": "http://192.168.0.1", "username_required": False},
                                 init_kwargs={"play_firmware": True})
driver_registry.register_builtin("cm3000", "app.drivers.cm3000.CM3000Driver", "Netgear CM3000",
                                 hints={"manufacturer": "Netgear", "region": "US", "default_url": "http://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("cm1000", "app.drivers.cm1000.CM1000Driver", "Netgear CM1000",
                                 hints={"manufacturer": "Netgear", "region": "US", "default_url": "http://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("cm3500", "app.drivers.cm3500.CM3500Driver", "Arris CM3500B",
                                 hints={"manufacturer": "Arris", "region": "Vodafone DE (ex Unitymedia)", "default_url": "https://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("surfboard", "app.drivers.surfboard.SurfboardDriver",
                                 "Arris SURFboard (S33/S34/SB8200)",
                                 hints={"manufacturer": "Arris", "region": "US · CA", "default_url": "https://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("sb6141", "app.drivers.sb6141.SB6141Driver",
                                 "Arris/Motorola SB6141",
                                 hints={"manufacturer": "Arris", "region": "US · CA", "default_url": "http://192.168.100.1", "credentials_required": False})
driver_registry.register_builtin("sb6183", "app.drivers.sb6183.SB6183Driver",
                                 "Arris SB6183",
                                 hints={"manufacturer": "Arris", "region": "US · CA", "default_url": "http://192.168.100.1", "credentials_required": False})
driver_registry.register_builtin("sb6190", "app.drivers.sb6190.SB6190Driver",
                                 "Arris SB6190",
                                 hints={"manufacturer": "Arris", "region": "US · CA", "default_url": "https://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("sb8200_cbn", "app.drivers.sb8200_cbn.SB8200CBNDriver",
                                 "Arris SURFboard SB8200 (CBN firmware)",
                                 hints={"manufacturer": "Arris", "default_url": "https://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("cm8200", "app.drivers.cm8200.CM8200Driver",
                                 "Arris Touchstone CM8200A",
                                 hints={"manufacturer": "Arris", "default_url": "https://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("hitron", "app.drivers.hitron.HitronDriver",
                                 "Hitron CODA-56",
                                 hints={"manufacturer": "Hitron", "region": "US", "default_url": "http://192.168.100.1", "credentials_required": False})
driver_registry.register_builtin("hitron_coda_4680", "app.drivers.hitron_coda_4680.HitronCoda4680Driver",
                                 "Hitron CODA-4680",
                                 hints={"manufacturer": "Hitron", "region": "Rogers · Shaw (CA)", "default_url": "http://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("sagemcom", "app.drivers.sagemcom.SagemcomDriver",
                                 "Sagemcom F@st 3896",
                                 hints={"manufacturer": "Sagemcom", "default_url": "http://192.168.100.1", "default_user": "admin"})
driver_registry.register_builtin("f3896lg", "app.drivers.f3896lg.F3896LGDriver",
                                 "Sagemcom F3896LG (Virgin Media Hub 5 / Liberty Global)",
                                 hints={"manufacturer": "Sagemcom", "default_url": "https://192.168.100.1",
                                        "credentials_required": False})
driver_registry.register_builtin("pyur_fast3896", "app.drivers.pyur_fast3896.PyurFast3896Driver",
                                 "PYUR FAST3896-15 (experimental)",
                                 hints={"manufacturer": "Sagemcom", "region": "PŸUR DE", "default_url": "http://192.168.100.1", "default_user": "admin",
                                        "credentials_required": True, "username_required": False})
driver_registry.register_builtin("sercom_dm1000", "app.drivers.sercom_dm1000.SercomDM1000Driver",
                                 "Sercom DM1000",
                                 hints={"manufacturer": "Sercom", "default_url": "http://192.168.100.1", "default_user": "technician"})
driver_registry.register_builtin("cgm4981", "app.drivers.cgm4981.CGM4981Driver",
                                 "Technicolor CGM4981COM (Cox Panoramic Gateway PM8 / XB8)",
                                 hints={"manufacturer": "Technicolor", "default_url": "http://192.168.0.1", "default_user": "admin"})
driver_registry.register_builtin("generic", "app.drivers.generic.GenericDriver", "Generic Router (No DOCSIS)",
                                 hints={"credentials_required": False})


def create_driver_registry():
    """Start an application with the unchanged built-in catalog."""
    return driver_registry.copy_builtins()


def get_driver_registry(runtime=None):
    """Resolve explicit collector ownership or the active HTTP application."""
    if runtime is None:
        from flask import has_app_context
        if has_app_context():
            from ..runtime import current_runtime
            runtime = current_runtime()
    registry = getattr(runtime, "driver_registry", None)
    return registry if isinstance(registry, DriverRegistry) else driver_registry


def load_driver(modem_type, url, user, password):
    """Backward-compatible wrapper around driver_registry.load_driver()."""
    return get_driver_registry().load_driver(modem_type, url, user, password)
