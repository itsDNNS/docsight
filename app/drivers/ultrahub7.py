"""Vodafone Ultra Hub 7 (Sercomm) driver for DOCSIS data retrieval.

This driver implements AES-CCM + PBKDF2-HMAC-SHA256 authentication
and fetches DOCSIS channel data via clean JSON APIs.

Based on HAR analysis from Tmo-Dev and aiovodafone patterns.
"""

import hashlib
import json
import logging
import os
import secrets

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from .base import ModemDriver

log = logging.getLogger("docsis.driver.ultrahub7")


class UltraHub7Driver(ModemDriver):
    """Driver for Vodafone Ultra Hub 7 (Sercomm DOCSIS 3.1).

    Authentication uses AES-CCM encryption with PBKDF2-HMAC-SHA256 key derivation.
    DOCSIS data is fetched via clean JSON API endpoints.
    """

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        self._session_cookie = None
        self._csrf_token = None

    def login(self) -> None:
        """Authenticate with AES-CCM encrypted credentials."""
        try:
            # Step 1: Get WebUISecret (salt) from device
            details_url = f"{self._url}/api/users/details.jst"
            r = requests.get(details_url, timeout=10)
            r.raise_for_status()
            details = r.json()

            web_ui_secret = details.get("WebUISecret", "")
            if not web_ui_secret:
                raise RuntimeError("WebUISecret not found in device response")

            # Step 2: Derive encryption key with PBKDF2-HMAC-SHA256
            # Use salt from WebUISecret (first 16 bytes as hex)
            salt = bytes.fromhex(web_ui_secret[:32])
            
            # PBKDF2: 1000 iterations, SHA256
            key = hashlib.pbkdf2_hmac(
                "sha256",
                self._password.encode("utf-8"),
                salt,
                1000,
                dklen=16  # AES-128
            )

            # Step 3: Encrypt password with AES-CCM
            # Generate random nonce (13 bytes for CCM)
            nonce = secrets.token_bytes(13)
            
            aes_ccm = AESCCM(key, tag_length=8)
            encrypted_password = aes_ccm.encrypt(
                nonce,
                self._password.encode("utf-8"),
                None  # No additional authenticated data
            )

            # Step 4: Build login payload
            # Format: nonce (hex) + encrypted_password (hex)
            encrypted_hex = nonce.hex() + encrypted_password.hex()

            login_payload = {
                "username": self._user,
                "password": encrypted_hex
            }

            # Step 5: POST login request
            login_url = f"{self._url}/api/users/login.jst"
            r2 = requests.post(
                login_url,
                json=login_payload,
                timeout=10
            )
            r2.raise_for_status()
            
            # Step 6: Extract session cookie and CSRF token
            login_response = r2.json()
            
            if not login_response.get("success", False):
                raise RuntimeError(
                    f"Login failed: {login_response.get('error', 'Unknown error')}"
                )

            # Extract DUKSID cookie
            cookies = r2.cookies
            if "DUKSID" not in cookies:
                raise RuntimeError("Session cookie (DUKSID) not found in response")
            
            self._session_cookie = cookies["DUKSID"]
            self._csrf_token = login_response.get("csrf_token", "")

            log.info("Auth OK (DUKSID: %s...)", self._session_cookie[:12])

        except requests.RequestException as e:
            log.error("Login failed: %s", e)
            raise RuntimeError(f"Ultra Hub 7 authentication failed: {e}")

    def get_docsis_data(self) -> dict:
        """Retrieve raw DOCSIS channel data."""
        if not self._session_cookie:
            raise RuntimeError("Not authenticated. Call login() first.")

        try:
            # Fetch downstream channels
            ds_url = f"{self._url}/api/docsis/downstream/list.jst"
            ds_response = requests.get(
                ds_url,
                cookies={"DUKSID": self._session_cookie},
                timeout=10
            )
            ds_response.raise_for_status()
            ds_data = ds_response.json()

            # Fetch upstream channels
            us_url = f"{self._url}/api/docsis/upstream/list.jst"
            us_response = requests.get(
                us_url,
                cookies={"DUKSID": self._session_cookie},
                timeout=10
            )
            us_response.raise_for_status()
            us_data = us_response.json()

            # Parse and convert to DOCSight schema
            downstream = self._parse_downstream_channels(ds_data.get("channels", []))
            upstream = self._parse_upstream_channels(us_data.get("channels", []))

            return {
                "docsis": "3.1",  # Ultra Hub 7 is DOCSIS 3.1
                "downstream": downstream,
                "upstream": upstream
            }

        except requests.RequestException as e:
            log.error("Failed to fetch DOCSIS data: %s", e)
            raise RuntimeError(f"DOCSIS data retrieval failed: {e}")

    def get_device_info(self) -> dict:
        """Retrieve device model and firmware info."""
        # Ultra Hub 7 doesn't expose device info via a dedicated endpoint
        # Return static info based on driver
        return {
            "model": "Vodafone Ultra Hub 7 (Sercomm)",
            "sw_version": "",  # Not available via API
        }

    def get_connection_info(self) -> dict:
        """Retrieve internet connection info (speeds, type)."""
        # Ultra Hub 7 doesn't expose connection info via DOCSIS API
        # Return empty dict (will use Fritz!Box fallback in analyzer)
        return {}

    def _parse_downstream_channels(self, channels: list) -> list:
        """Parse downstream channel data from Ultra Hub 7 API format."""
        result = []
        
        for ch in channels:
            try:
                # Parse fields with proper type conversion
                channel_id = int(ch.get("ChannelID", "0"))
                frequency = self._parse_frequency(ch.get("Frequency", "0"))
                modulation = self._normalize_modulation(ch.get("Modulation", ""))
                power = self._parse_power(ch.get("PowerLevel", "0"))
                snr = self._parse_snr(ch.get("SNRLevel", ""))
                lock_status = ch.get("LockStatus", "")

                # Map to FritzBox-compatible format for analyzer
                result.append({
                    "channelID": str(channel_id),
                    "type": modulation,
                    "frequency": f"{int(frequency)} MHz",
                    "powerLevel": power,
                    "mer": snr if snr > 0 else None,  # DOCSIS 3.1 uses MER
                    "mse": None,  # Not provided
                    "latency": 0,
                    "corrError": 0,  # Not provided by Ultra Hub 7 API
                    "nonCorrError": 0  # Not provided by Ultra Hub 7 API
                })

            except (ValueError, TypeError) as e:
                log.warning("Failed to parse downstream channel %s: %s", ch, e)
                continue

        return result

    def _parse_upstream_channels(self, channels: list) -> list:
        """Parse upstream channel data from Ultra Hub 7 API format."""
        result = []
        
        for ch in channels:
            try:
                # Parse fields with proper type conversion
                channel_id = int(ch.get("ChannelID", "0"))
                frequency = self._parse_frequency(ch.get("Frequency", "0"))
                modulation = self._normalize_modulation(ch.get("Modulation", ""))
                power = self._parse_power(ch.get("PowerLevel", "0"))
                lock_status = ch.get("LockStatus", "")

                # Map to FritzBox-compatible format for analyzer
                result.append({
                    "channelID": str(channel_id),
                    "type": modulation,
                    "frequency": f"{int(frequency)} MHz",
                    "powerLevel": power,
                    "multiplex": ""  # Not relevant for display
                })

            except (ValueError, TypeError) as e:
                log.warning("Failed to parse upstream channel %s: %s", ch, e)
                continue

        return result

    def _parse_frequency(self, freq_str: str) -> float:
        """Parse frequency string to MHz float.
        
        Handles both single and double spaces: "264 MHz" and "51  MHz"
        """
        if not freq_str:
            return 0.0
        
        try:
            # Strip whitespace and split on first space
            parts = freq_str.strip().split()
            return float(parts[0])
        except (IndexError, ValueError):
            log.warning("Failed to parse frequency: %s", freq_str)
            return 0.0

    def _parse_power(self, power_str: str) -> float:
        """Parse power string to dBmV float.
        
        Format: "15.1 dBmV" → 15.1
        """
        if not power_str:
            return 0.0
        
        try:
            # Split on space and take first part
            parts = power_str.strip().split()
            return float(parts[0])
        except (IndexError, ValueError):
            log.warning("Failed to parse power: %s", power_str)
            return 0.0

    def _parse_snr(self, snr_str: str) -> float:
        """Parse SNR string to dB float.
        
        Format: "41.9 dB" → 41.9
        Empty string → 0.0 (upstream channels don't have SNR)
        """
        if not snr_str or snr_str.strip() == "":
            return 0.0
        
        try:
            # Split on space and take first part
            parts = snr_str.strip().split()
            return float(parts[0])
        except (IndexError, ValueError):
            log.warning("Failed to parse SNR: %s", snr_str)
            return 0.0

    def _normalize_modulation(self, modulation: str) -> str:
        """Normalize modulation string to match analyzer expectations.
        
        Ultra Hub 7 uses: "256QAM", "64QAM", "4096QAM", "32QAM", etc.
        Analyzer expects: "qam_256", "qam_64", "ofdm", etc.
        """
        if not modulation:
            return ""
        
        # Remove hyphens and convert to uppercase
        mod_upper = modulation.upper().replace("-", "")
        
        # Map common values (check OFDMA before OFDM!)
        if "OFDMA" in mod_upper:
            return "ofdma"
        elif "OFDM" in mod_upper:
            return "ofdm"
        elif "QAM" in mod_upper:
            # Extract number: "256QAM" → "qam_256"
            num = mod_upper.replace("QAM", "")
            return f"qam_{num}"
        
        # Return as-is if unknown
        return modulation.lower()
