"""FritzBox driver implementing the Driver interface.

Supports AVM FRITZ!Box Cable routers with DOCSIS support.
"""

import hashlib
import logging
import xml.etree.ElementTree as ET
from typing import Any, Dict, Optional

import requests

from .interface import Driver

log = logging.getLogger("docsis.drivers.fritzbox")


class FritzBoxDriver(Driver):
    """Driver for AVM FRITZ!Box Cable routers."""

    def login(self, url: str, username: str, password: str, timeout: int = 10) -> Optional[str]:
        """Authenticate to FritzBox and return session ID (SID).
        
        Returns:
            Session ID string on success, None on failure
        """
        try:
            r = requests.get(
                f"{url}/login_sid.lua?version=2&username={username}", timeout=timeout
            )
            r.raise_for_status()
            root = ET.fromstring(r.text)
            challenge = root.find("Challenge").text

            if challenge.startswith("2$"):
                # PBKDF2 (modern FritzOS)
                parts = challenge.split("$")
                iter1, salt1 = int(parts[1]), bytes.fromhex(parts[2])
                iter2, salt2 = int(parts[3]), bytes.fromhex(parts[4])
                hash1 = hashlib.pbkdf2_hmac("sha256", password.encode(), salt1, iter1)
                hash2 = hashlib.pbkdf2_hmac("sha256", hash1, salt2, iter2)
                response = f"{parts[4]}${hash2.hex()}"
            else:
                # MD5 (legacy fallback)
                md5_input = f"{challenge}-{password}".encode("utf-16-le")
                md5_hash = hashlib.md5(md5_input).hexdigest()
                response = f"{challenge}-{md5_hash}"

            r2 = requests.get(
                f"{url}/login_sid.lua?version=2&username={username}&response={response}",
                timeout=timeout,
            )
            r2.raise_for_status()
            root2 = ET.fromstring(r2.text)
            sid = root2.find("SID").text

            if sid == "0000000000000000":
                log.error("FritzBox authentication failed")
                return None

            log.info("FritzBox auth OK (SID: %s...)", sid[:8])
            return sid
        except Exception as e:
            log.error("FritzBox login failed: %s", e)
            return None

    def get_docsis_data(self, session: Any, url: str) -> Dict:
        """Query DOCSIS channel data from FritzBox.
        
        Args:
            session: SID string returned by login()
            url: Base URL of the FritzBox
            
        Returns:
            Dict with DOCSIS channel data
        """
        sid = session  # session is the SID string
        r = requests.post(
            f"{url}/data.lua",
            data={
                "xhr": 1,
                "sid": sid,
                "lang": "de",
                "page": "docInfo",
                "xhrId": "all",
                "no_sidrenew": "",
            },
            timeout=10,
        )
        r.raise_for_status()
        return r.json().get("data", {})

    def get_device_info(self, session: Any, url: str) -> Dict:
        """Get FritzBox model and firmware info.
        
        Args:
            session: SID string returned by login()
            url: Base URL of the FritzBox
            
        Returns:
            Dict with device information
        """
        sid = session
        try:
            r = requests.post(
                f"{url}/data.lua",
                data={
                    "xhr": 1,
                    "sid": sid,
                    "lang": "de",
                    "page": "overview",
                    "xhrId": "all",
                    "no_sidrenew": "",
                },
                timeout=10,
            )
            r.raise_for_status()
            data = r.json().get("data", {})
            fritzos = data.get("fritzos", {})
            result = {
                "model": fritzos.get("Productname", "FRITZ!Box"),
                "sw_version": fritzos.get("nspver", ""),
            }
            uptime = fritzos.get("Uptime")
            if uptime is not None:
                try:
                    result["uptime_seconds"] = int(uptime)
                except (ValueError, TypeError):
                    # Ignore parsing errors and skip uptime if it's not a valid integer
                    pass
            return result
        except Exception as e:
            log.warning("Failed to get device info: %s", e)
            return {"model": "FRITZ!Box", "sw_version": ""}

    def get_connection_info(self, session: Any, url: str) -> Optional[Dict]:
        """Get internet connection info (speeds, type) from netMoni page.
        
        Args:
            session: SID string returned by login()
            url: Base URL of the FritzBox
            
        Returns:
            Dict with connection info or None on error
        """
        sid = session
        try:
            r = requests.post(
                f"{url}/data.lua",
                data={
                    "xhr": 1,
                    "sid": sid,
                    "lang": "de",
                    "page": "netMoni",
                    "xhrId": "all",
                    "no_sidrenew": "",
                },
                timeout=10,
            )
            r.raise_for_status()
            data = r.json().get("data", {})
            conns = data.get("connections", [])
            if not conns:
                return None
            conn = conns[0]
            return {
                "max_downstream_kbps": conn.get("downstream", 0),
                "max_upstream_kbps": conn.get("upstream", 0),
                "connection_type": conn.get("medium", ""),
            }
        except Exception as e:
            log.warning("Failed to get connection info: %s", e)
            return None
