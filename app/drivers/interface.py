"""Abstract driver interface for modem drivers.

All modem drivers must implement this interface to ensure compatibility
with the DOCSight analyzer, storage, and web UI.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional


class Driver(ABC):
    """Abstract base class for modem drivers.
    
    Each driver is responsible for:
    1. Authenticating with the modem's web interface
    2. Fetching DOCSIS channel data in the standard format
    3. Fetching device information (model, firmware, etc.)
    
    The session object returned by login() can be any type (requests.Session,
    string token, custom object) - it will be passed back to other methods.
    """

    @abstractmethod
    def login(self, url: str, username: str, password: str, timeout: int = 10) -> Optional[Any]:
        """Authenticate with the modem.
        
        Args:
            url: Base URL of the modem (e.g., "http://192.168.178.1")
            username: Username for authentication
            password: Password for authentication
            timeout: Request timeout in seconds
            
        Returns:
            Session object (can be requests.Session, token string, or custom object)
            Returns None on authentication failure
            
        Raises:
            Exception: On connection or authentication errors
        """
        pass

    @abstractmethod
    def get_docsis_data(self, session: Any, url: str) -> Dict:
        """Fetch DOCSIS channel data from the modem.
        
        Args:
            session: Session object returned by login()
            url: Base URL of the modem
            
        Returns:
            Dict with standardized DOCSIS data format:
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
            
        Raises:
            Exception: On connection or parsing errors
        """
        pass

    @abstractmethod
    def get_device_info(self, session: Any, url: str) -> Dict:
        """Fetch device information from the modem.
        
        Args:
            session: Session object returned by login()
            url: Base URL of the modem
            
        Returns:
            Dict with device information:
            {
                "model": str,           # Device model name
                "sw_version": str,      # Firmware version
                "uptime_seconds": int,  # Optional: uptime in seconds
            }
            
        Raises:
            Exception: On connection or parsing errors
        """
        pass

    def get_connection_info(self, session: Any, url: str) -> Optional[Dict]:
        """Fetch connection information (optional method).
        
        Args:
            session: Session object returned by login()
            url: Base URL of the modem
            
        Returns:
            Dict with connection info (optional):
            {
                "max_downstream_kbps": int,
                "max_upstream_kbps": int,
                "connection_type": str,
            }
            Returns None if not supported by this driver
        """
        return None
