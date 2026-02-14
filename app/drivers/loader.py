"""Driver loader - dynamically loads modem drivers by name."""

import importlib
import logging
from typing import Optional

from .interface import Driver

log = logging.getLogger("docsis.drivers.loader")

# Registry of available drivers
AVAILABLE_DRIVERS = {
    "fritzbox": "app.drivers.fritzbox.FritzBoxDriver",
    "vodafone": "app.drivers.vodafone.VodafoneStationDriver",
    # Add more drivers here as they are implemented:
    # "arris": "app.drivers.arris.ArrisDriver",
}


def load_driver(modem_type: str) -> Optional[Driver]:
    """Load and instantiate a driver by modem type.
    
    Args:
        modem_type: Type of modem (e.g., "fritzbox", "vodafone")
        
    Returns:
        Instantiated Driver object or None if driver not found
        
    Example:
        driver = load_driver("fritzbox")
        session = driver.login("http://192.168.178.1", "admin", "password")
        data = driver.get_docsis_data(session, "http://192.168.178.1")
    """
    if not modem_type:
        log.error("No modem_type specified")
        return None
        
    driver_path = AVAILABLE_DRIVERS.get(modem_type.lower())
    if not driver_path:
        log.error("Unknown modem type: %s. Available: %s", 
                  modem_type, ", ".join(AVAILABLE_DRIVERS.keys()))
        return None
    
    try:
        # Split module path and class name
        module_path, class_name = driver_path.rsplit(".", 1)
        module = importlib.import_module(module_path)
        driver_class = getattr(module, class_name)
        
        # Instantiate and return
        driver = driver_class()
        log.info("Loaded driver: %s (%s)", modem_type, driver_path)
        return driver
        
    except Exception as e:
        log.error("Failed to load driver %s: %s", modem_type, e)
        return None


def get_available_drivers():
    """Get list of available driver names.
    
    Returns:
        List of driver names (e.g., ["fritzbox", "vodafone"])
    """
    return list(AVAILABLE_DRIVERS.keys())
