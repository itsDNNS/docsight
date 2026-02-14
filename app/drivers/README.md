# Modem Drivers

This directory contains modem drivers for DOCSight. Each driver implements the `Driver` interface to provide authentication and data fetching for a specific modem type.

## Available Drivers

- **fritzbox** - AVM FRITZ!Box Cable routers (full support)
- **vodafone** - Vodafone Station (ARRIS TG3442DE)
  - ⚠️ **Note:** Error counters not available (set to 0). Power and SNR monitoring fully supported.

## Adding a New Driver

### 1. Create Driver Module

Create a new file `app/drivers/your_modem.py`:

```python
"""Your Modem driver implementing the Driver interface."""

import logging
from typing import Any, Dict, Optional

from .interface import Driver

log = logging.getLogger("docsis.drivers.your_modem")


class YourModemDriver(Driver):
    """Driver for Your Modem."""

    def login(self, url: str, username: str, password: str, timeout: int = 10) -> Optional[Any]:
        """Authenticate with the modem.
        
        Returns:
            Session object (can be requests.Session, token string, or custom object)
            Returns None on authentication failure
        """
        # Implement authentication logic
        # Return session/token or None
        pass

    def get_docsis_data(self, session: Any, url: str) -> Dict:
        """Fetch DOCSIS channel data.
        
        Must return dict with this structure:
        {
            "channelDs": {
                "docsis30": [
                    {
                        "channelID": int,
                        "frequency": str,     # e.g., "602 MHz"
                        "powerLevel": float,  # dBmV
                        "mse": float,         # MSE (negative SNR) for DOCSIS 3.0
                        "modulation": str,    # e.g., "256QAM"
                        "corrErrors": int,
                        "nonCorrErrors": int,
                    },
                    ...
                ],
                "docsis31": [
                    {
                        "channelID": int,
                        "frequency": str,     # e.g., "612~680 MHz"
                        "powerLevel": float,  # dBmV
                        "mer": float,         # MER (SNR) for DOCSIS 3.1
                        "modulation": str,    # e.g., "OFDM"
                        "corrErrors": int,
                        "nonCorrErrors": int,
                    },
                    ...
                ]
            },
            "channelUs": {
                "docsis30": [
                    {
                        "channelID": int,
                        "frequency": str,
                        "powerLevel": float,  # dBmV
                        "modulation": str,    # e.g., "64QAM"
                        "multiplex": str,     # e.g., "ATDMA"
                    },
                    ...
                ],
                "docsis31": [
                    {
                        "channelID": int,
                        "frequency": str,
                        "powerLevel": float,  # dBmV
                        "modulation": str,    # e.g., "OFDMA"
                        "multiplex": str,
                    },
                    ...
                ]
            }
        }
        """
        # Implement data fetching logic
        pass

    def get_device_info(self, session: Any, url: str) -> Dict:
        """Fetch device information.
        
        Returns:
            {
                "model": str,
                "sw_version": str,
                "uptime_seconds": int,  # optional
            }
        """
        # Implement device info fetching
        pass

    def get_connection_info(self, session: Any, url: str) -> Optional[Dict]:
        """Fetch connection info (optional).
        
        Returns:
            {
                "max_downstream_kbps": int,
                "max_upstream_kbps": int,
                "connection_type": str,
            }
            or None if not supported
        """
        # Optional: implement connection info fetching
        return None
```

### 2. Register Driver

Add your driver to `app/drivers/loader.py`:

```python
AVAILABLE_DRIVERS = {
    "fritzbox": "app.drivers.fritzbox.FritzBoxDriver",
    "your_modem": "app.drivers.your_modem.YourModemDriver",  # Add this line
}
```

### 3. Update Package

Add your driver to `app/drivers/__init__.py`:

```python
__all__ = ["interface", "loader", "fritzbox", "your_modem"]
```

### 4. Test Your Driver

Create `tests/test_your_modem.py`:

```python
import pytest
from app.drivers.your_modem import YourModemDriver

def test_login():
    driver = YourModemDriver()
    # Add mock tests
    pass

def test_get_docsis_data():
    driver = YourModemDriver()
    # Add mock tests
    pass
```

### 5. Configure DOCSight

Users can now select your driver by setting `modem_type` in config:

```json
{
  "modem_type": "your_modem",
  "modem_url": "http://192.168.1.1",
  "modem_user": "admin",
  "modem_password": "password"
}
```

Or via environment variable:

```bash
export MODEM_TYPE=your_modem
```

## Driver Interface Reference

See `interface.py` for the complete `Driver` abstract class definition.

### Key Points

1. **Session Object**: The `login()` method can return any type (requests.Session, string token, custom object). This object is passed to other methods.

2. **Standard Format**: `get_docsis_data()` must return data in the standardized format so the analyzer works correctly.

3. **Error Handling**: Methods should raise exceptions on errors. The main loop will catch and log them.

4. **Logging**: Use `logging.getLogger("docsis.drivers.your_modem")` for consistent logging.

## Reference Implementations

- **app/drivers/fritzbox.py** - Production driver for FRITZ!Box (session-based with SID token)
- **app/drivers/vodafone.py** - Production driver for Vodafone Station / ARRIS TG3442DE (AES-CCM encrypted auth)
- **arris-tg3442de-exporter** - External project that inspired the Vodafone driver

## Wanted Drivers

- ~~Vodafone Station / CommScope~~ ✅ **Implemented!**
- Arris / Technicolor / Sagemcom (other models)
- SNMP generic driver (for modems exposing DOCSIS MIBs)
