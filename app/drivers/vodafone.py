"""Vodafone Station driver (ARRIS TG3442DE) implementing the Driver interface.

Supports Vodafone Station / ARRIS TG3442DE cable modems.
Based on the arris-tg3442de-exporter implementation.
"""

import binascii
import hashlib
import json
import logging
import re
from typing import Any, Dict, Optional

import requests
from Crypto.Cipher import AES

from .interface import Driver

log = logging.getLogger("docsis.drivers.vodafone")


class VodafoneStationDriver(Driver):
    """Driver for Vodafone Station (ARRIS TG3442DE) cable modems."""

    def login(self, url: str, username: str, password: str, timeout: int = 10) -> Optional[requests.Session]:
        """Authenticate to Vodafone Station using AES-CCM encrypted password.
        
        Returns:
            requests.Session with CSRF headers set on success, None on failure
        """
        try:
            log.info("Attempting Vodafone Station login to %s", url)
            session = requests.Session()
            
            # 1. Get login page to extract session ID, IV, and salt
            log.debug("Fetching login page...")
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
            log.debug("Login page status: %d, content length: %d", r.status_code, len(r.text))
            
            # Extract values from JavaScript in the page
            try:
                current_session_id = re.search(r".*var currentSessionId = '(.+)';.*", r.text)[1]
                log.debug("Extracted currentSessionId: %s", current_session_id[:20] + "...")
            except (TypeError, IndexError) as e:
                log.error("Failed to extract currentSessionId from login page")
                log.debug("Login page content preview: %s", r.text[:500])
                return None
            
            try:
                iv = re.search(r".*var myIv = '(.+)';.*", r.text)[1]
                log.debug("Extracted IV: %s", iv[:20] + "...")
            except (TypeError, IndexError) as e:
                log.error("Failed to extract IV from login page")
                return None
            
            try:
                salt = re.search(r".*var mySalt = '(.+)';.*", r.text)[1]
                log.debug("Extracted salt: %s", salt[:20] + "...")
            except (TypeError, IndexError) as e:
                log.error("Failed to extract salt from login page")
                return None
            
            # 2. Derive encryption key using PBKDF2-HMAC-SHA256
            log.debug("Deriving encryption key...")
            key = hashlib.pbkdf2_hmac(
                'sha256',
                password.encode("ascii"),
                binascii.unhexlify(salt),
                iterations=1000,
                dklen=16
            )
            log.debug("Key derived successfully")
            
            # 3. Prepare and encrypt the login payload
            secret = {"Password": password, "Nonce": current_session_id}
            plaintext = json.dumps(secret).encode("ascii")
            associated_data = "loginPassword"
            
            # Use pycryptodome's AES.MODE_CCM (same as arris-tg3442de-exporter)
            iv_bytes = binascii.unhexlify(iv)
            log.debug("IV length: %d", len(iv_bytes))
            
            # Create cipher for encryption
            cipher = AES.new(key, AES.MODE_CCM, iv_bytes)
            cipher.update(associated_data.encode("ascii"))
            encrypt_data = cipher.encrypt(plaintext)
            encrypt_data += cipher.digest()
            log.debug("Payload encrypted successfully, encrypted data length: %d", len(encrypt_data))
            
            login_data = {
                'EncryptData': binascii.hexlify(encrypt_data).decode("ascii"),
                'Name': username,
                'AuthData': associated_data
            }
            log.debug("Login data prepared - Name: %s, AuthData: %s, EncryptData length: %d", 
                     username, associated_data, len(login_data['EncryptData']))
            
            # 4. POST encrypted credentials
            log.debug("Posting encrypted credentials to /php/ajaxSet_Password.php...")
            r = session.post(
                f"{url}/php/ajaxSet_Password.php",
                headers={"Content-Type": "application/json"},
                data=json.dumps(login_data),
                timeout=timeout
            )
            r.raise_for_status()
            log.debug("Password post response status: %d", r.status_code)
            log.debug("Password post response: %s", r.text[:200])
            
            # Check for successful login
            if "AdminMatch" not in r.text:
                log.error("Vodafone Station authentication failed - AdminMatch not in response")
                log.debug("Full response: %s", r.text)
                return None
            
            try:
                result = r.json()
            except json.JSONDecodeError as e:
                log.error("Failed to parse JSON response: %s", e)
                log.debug("Response text: %s", r.text)
                return None
            
            # 5. Decrypt response to get CSRF nonce
            encryptData = result.get('encryptData')
            if not encryptData:
                log.error("No encryptData in login response")
                log.debug("Response keys: %s", list(result.keys()))
                return None
            
            log.debug("Decrypting CSRF nonce...")
            log.debug("encryptData hex length: %d (bytes: %d)", len(encryptData), len(encryptData) // 2)
            
            # Decrypt using pycryptodome (same as original arris exporter)
            cipher_decrypt = AES.new(key, AES.MODE_CCM, iv_bytes)
            plain_data = cipher_decrypt.decrypt(binascii.unhexlify(encryptData))
            csrf_nonce = plain_data[:32]
            log.debug("CSRF nonce extracted: %d bytes", len(csrf_nonce))
            log.debug("Decrypted data length: %d", len(plain_data))
            
            # 6. Set required headers for subsequent requests
            # CSRF nonce is binary data, keep as bytes or decode with latin-1
            if isinstance(csrf_nonce, bytes):
                csrf_nonce_str = csrf_nonce.decode("latin-1")  # Use latin-1 to preserve all bytes
            else:
                csrf_nonce_str = str(csrf_nonce)
            log.debug("Setting session headers with CSRF nonce")
            session.headers.update({
                "X-Requested-With": "XMLHttpRequest",
                "csrfNonce": csrf_nonce_str,
                "Origin": url.rstrip("/"),
            })
            
            # 7. Finalize session
            log.debug("Finalizing session...")
            r = session.post(f"{url}/php/ajaxSet_Session.php", timeout=timeout)
            log.debug("Session finalize response: %d", r.status_code)
            
            log.info("Vodafone Station auth OK")
            return session
            
        except Exception as e:
            log.error("Vodafone Station login failed: %s", e, exc_info=True)
            return None

    def get_docsis_data(self, session: Any, url: str) -> Dict:
        """Fetch DOCSIS channel data from Vodafone Station.
        
        Args:
            session: requests.Session returned by login()
            url: Base URL of the Vodafone Station
            
        Returns:
            Dict with DOCSIS channel data in DOCSight format
        """
        try:
            # Fetch DOCSIS status page
            log.debug("Fetching DOCSIS data from /php/status_docsis_data.php...")
            r = session.get(f"{url}/php/status_docsis_data.php", timeout=10)
            r.raise_for_status()
            log.debug("DOCSIS page status: %d, content length: %d", r.status_code, len(r.text))
            
            # Extract JSON data from JavaScript variables
            # Use non-greedy match and stop at semicolon to avoid capturing extra data
            json_ds_match = re.search(r"json_dsData = (.+?);", r.text, re.DOTALL)
            json_us_match = re.search(r"json_usData = (.+?);", r.text, re.DOTALL)
            
            if not json_ds_match or not json_us_match:
                log.error("Could not extract DOCSIS data from response")
                log.debug("Response preview: %s", r.text[:500])
                return {"channelDs": {"docsis30": [], "docsis31": []}, "channelUs": {"docsis30": [], "docsis31": []}}
            
            log.debug("Parsing downstream data...")
            downstream_data = json.loads(json_ds_match[1])
            log.debug("Found %d downstream channels", len(downstream_data) if isinstance(downstream_data, list) else 0)
            if downstream_data and len(downstream_data) > 0:
                log.debug("Sample DS channel data: %s", downstream_data[0])
            
            log.debug("Parsing upstream data...")
            upstream_data = json.loads(json_us_match[1])
            log.debug("Found %d upstream channels", len(upstream_data) if isinstance(upstream_data, list) else 0)
            if upstream_data and len(upstream_data) > 0:
                log.debug("Sample US channel data: %s", upstream_data[0])
            
            # Transform to DOCSight format
            log.debug("Transforming to DOCSight format...")
            return self._transform_to_docsight_format(downstream_data, upstream_data)
            
        except Exception as e:
            log.error("Failed to fetch DOCSIS data: %s", e, exc_info=True)
            return {"channelDs": {"docsis30": [], "docsis31": []}, "channelUs": {"docsis30": [], "docsis31": []}}

    def _transform_to_docsight_format(self, downstream_data: list, upstream_data: list) -> Dict:
        """Transform Vodafone Station data format to DOCSight analyzer format.
        
        Vodafone format:
        {
            "ChannelID": "1",
            "ChannelType": "SC-QAM" | "OFDM",
            "Frequency": "602000000" or "602~698",
            "PowerLevel": "3.2 dBmV / 320 dBuV",
            "SNRLevel": "37.5",
            "Modulation": "256QAM",
            "LockStatus": "Locked" | "ACTIVE" | "SUCCESS",
            ...
        }
        
        DOCSight format (FritzBox-like):
        {
            "channelDs": {
                "docsis30": [{channelID, frequency, powerLevel, mse, modulation, corrErrors, nonCorrErrors}, ...],
                "docsis31": [{channelID, frequency, powerLevel, mer, modulation, corrErrors, nonCorrErrors}, ...]
            },
            "channelUs": {
                "docsis30": [{channelID, frequency, powerLevel, modulation, multiplex}, ...],
                "docsis31": [{channelID, frequency, powerLevel, modulation, multiplex}, ...]
            }
        }
        """
        ds_30 = []
        ds_31 = []
        us_30 = []
        us_31 = []
        
        # Process downstream channels
        for ch in downstream_data:
            log.debug("Processing DS channel: %s", ch)
            channel_type = ch.get("ChannelType", "SC-QAM")
            is_docsis31 = channel_type in ("OFDM", "OFDMA")
            
            # Parse frequency (can be "602000000" or "602~698" or integer)
            freq_raw = ch.get("Frequency", "0")
            log.debug("Frequency raw value: %s (type: %s)", freq_raw, type(freq_raw).__name__)
            freq_str = str(freq_raw)  # Convert to string in case it's an integer
            if "~" in freq_str:
                freq_str = freq_str.split("~")[0]
            try:
                # Handle both Hz (large numbers) and MHz (small numbers)
                freq_num = float(freq_str)
                if freq_num > 10000:  # Likely in Hz
                    frequency = f"{freq_num / 1000000:.0f} MHz"
                else:  # Already in MHz
                    frequency = f"{freq_num:.0f} MHz"
            except (ValueError, TypeError):
                frequency = freq_str
            log.debug("Parsed frequency: %s", frequency)
            
            # Parse power level "3.2 dBmV / 320 dBuV" or "3.2/320" or just number
            power_raw = ch.get("PowerLevel", "0")
            log.debug("PowerLevel raw value: %r (type: %s)", power_raw, type(power_raw).__name__)
            
            try:
                if isinstance(power_raw, (int, float)):
                    # Direct number
                    power_level = float(power_raw)
                else:
                    # String format - try different patterns
                    power_str = str(power_raw)
                    # Pattern 1: "3.2 dBmV / 320 dBuV" or "3.2 dBmV/320 dBuV"
                    if "dBmV" in power_str or "/" in power_str:
                        # Split by "/" and take first part, then extract number
                        first_part = power_str.split("/")[0].strip()
                        # Remove "dBmV" and any other text
                        number_str = first_part.replace("dBmV", "").replace("dBuV", "").strip()
                        power_level = float(number_str)
                    else:
                        # Direct number as string
                        power_level = float(power_str)
            except (ValueError, IndexError, AttributeError) as e:
                log.warning("Failed to parse power level from %r: %s", power_raw, e)
                power_level = 0.0
            log.debug("Parsed power level: %.2f dBmV", power_level)
            
            # SNR level
            snr_raw = ch.get("SNRLevel", "0")
            log.debug("SNRLevel raw value: %s (type: %s)", snr_raw, type(snr_raw).__name__)
            try:
                snr = float(snr_raw)
            except (ValueError, TypeError):
                snr = 0.0
            log.debug("Parsed SNR: %s", snr)
            
            channel_dict = {
                "channelID": int(ch.get("ChannelID", 0)),
                "frequency": frequency,
                "powerLevel": power_level,
                "modulation": ch.get("Modulation", ""),
                "type": channel_type,
                "corrErrors": 0,  # Vodafone Station doesn't expose these in status page
                "nonCorrErrors": 0,
            }
            
            if is_docsis31:
                channel_dict["mer"] = snr  # MER for DOCSIS 3.1
                ds_31.append(channel_dict)
            else:
                channel_dict["mse"] = -snr  # MSE (negative SNR) for DOCSIS 3.0
                ds_30.append(channel_dict)
        
        # Process upstream channels
        for ch in upstream_data:
            log.debug("Processing US channel: %s", ch)
            channel_type = ch.get("ChannelType", "SC-QAM")
            is_docsis31 = channel_type in ("OFDM", "OFDMA")
            
            # Parse frequency (can be string or integer)
            freq_raw = ch.get("Frequency", "0")
            log.debug("US Frequency raw value: %s (type: %s)", freq_raw, type(freq_raw).__name__)
            freq_str = str(freq_raw)  # Convert to string in case it's an integer
            if "~" in freq_str:
                freq_str = freq_str.split("~")[0]
            try:
                # Handle both Hz (large numbers) and MHz (small numbers)
                freq_num = float(freq_str)
                if freq_num > 10000:  # Likely in Hz
                    frequency = f"{freq_num / 1000000:.0f} MHz"
                else:  # Already in MHz
                    frequency = f"{freq_num:.0f} MHz"
            except (ValueError, TypeError):
                frequency = freq_str
            log.debug("US Parsed frequency: %s", frequency)
            
            # Parse power level
            power_raw = ch.get("PowerLevel", "0")
            log.debug("US PowerLevel raw value: %r (type: %s)", power_raw, type(power_raw).__name__)
            
            try:
                if isinstance(power_raw, (int, float)):
                    # Direct number
                    power_level = float(power_raw)
                else:
                    # String format - try different patterns
                    power_str = str(power_raw)
                    # Pattern 1: "3.2 dBmV / 320 dBuV" or "3.2 dBmV/320 dBuV"
                    if "dBmV" in power_str or "/" in power_str:
                        # Split by "/" and take first part, then extract number
                        first_part = power_str.split("/")[0].strip()
                        # Remove "dBmV" and any other text
                        number_str = first_part.replace("dBmV", "").replace("dBuV", "").strip()
                        power_level = float(number_str)
                    else:
                        # Direct number as string
                        power_level = float(power_str)
            except (ValueError, IndexError, AttributeError) as e:
                log.warning("Failed to parse US power level from %r: %s", power_raw, e)
                power_level = 0.0
            log.debug("US Parsed power level: %.2f dBmV", power_level)
            
            channel_dict = {
                "channelID": int(ch.get("ChannelID", 0)),
                "frequency": frequency,
                "powerLevel": power_level,
                "modulation": ch.get("Modulation", ""),
                "type": channel_type,
                "multiplex": "ATDMA" if not is_docsis31 else "OFDMA",
            }
            
            if is_docsis31:
                us_31.append(channel_dict)
            else:
                us_30.append(channel_dict)
        
        return {
            "channelDs": {
                "docsis30": ds_30,
                "docsis31": ds_31
            },
            "channelUs": {
                "docsis30": us_30,
                "docsis31": us_31
            }
        }

    def get_device_info(self, session: Any, url: str) -> Dict:
        """Fetch device information from Vodafone Station.
        
        Args:
            session: requests.Session returned by login()
            url: Base URL of the Vodafone Station
            
        Returns:
            Dict with device information
        """
        try:
            # Try to get device info from overview page
            r = session.get(f"{url}/php/status_overview_data.php", timeout=10)
            r.raise_for_status()
            
            # Extract device info from response
            # The Vodafone Station returns JSON with device details
            data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            
            return {
                "model": data.get("model", "Vodafone Station"),
                "sw_version": data.get("sw_version", ""),
                "uptime_seconds": data.get("uptime", 0),
            }
        except Exception as e:
            log.warning("Failed to get device info: %s", e)
            return {
                "model": "Vodafone Station",
                "sw_version": "",
            }

    def get_connection_info(self, session: Any, url: str) -> Optional[Dict]:
        """Get connection info from Vodafone Station (not supported).
        
        The Vodafone Station doesn't expose connection speed info in an easily
        accessible format, so this returns None.
        """
        return None
