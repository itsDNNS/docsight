"""Vodafone Station driver for DOCSight.

Supports two hardware variants with auto-detection:
- CGA (CGA6444VF, CGA4322DE): Clean JSON API + double PBKDF2 auth
- TG (TG3442DE): HTML parsing + AES-CCM auth

Variant is auto-detected on first login attempt.

References:
- CGA6444VF: ZahrtheMad (tested & confirmed), aiovodafone patterns
- TG3442DE: PR #13 (Arris AES-CCM flow), vodafone-station-cli
"""

import json
import logging
import re

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .base import ModemDriver

log = logging.getLogger("docsis.driver.vodafone_station")


class VodafoneStationDriver(ModemDriver):
    """Driver for Vodafone Station (Arris TG3442DE, CGA6444VF, Technicolor CGA4322DE)."""

    VARIANT_CGA = "cga"  # CGA6444VF / CGA4322DE (JSON API + double PBKDF2)
    VARIANT_TG = "tg"    # TG3442DE (HTML + AES-CCM)

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._variant = None  # Auto-detected on first login

        # CGA-specific state
        self._cga_token = None

        # TG-specific state
        self._tg_nonce = None
        self._tg_key = None
        self._tg_iv = None

    # ── Public API ────────────────────────────────────────────

    def login(self) -> None:
        """Authenticate with the modem. Auto-detects hardware variant on first call."""
        if self._variant is None:
            self._auto_detect_and_login()
        elif self._variant == self.VARIANT_CGA:
            self._login_cga()
        else:
            self._login_tg()

    def get_docsis_data(self) -> dict:
        """Retrieve DOCSIS channel data."""
        if self._variant == self.VARIANT_CGA:
            return self._get_docsis_cga()
        elif self._variant == self.VARIANT_TG:
            return self._get_docsis_tg()
        raise RuntimeError("Not authenticated. Call login() first.")

    def get_device_info(self) -> dict:
        """Retrieve device model and firmware info."""
        if self._variant == self.VARIANT_CGA:
            return self._get_device_info_cga()
        return {
            "manufacturer": "Arris",
            "model": "Vodafone Station (TG3442DE)",
            "sw_version": "",
        }

    def get_connection_info(self) -> dict:
        """Retrieve internet connection info."""
        return {}

    # ── Auto-Detection ────────────────────────────────────────

    def _auto_detect_and_login(self) -> None:
        """Try CGA first, then TG. Store detected variant."""
        # Try CGA (simpler flow, has active tester)
        try:
            self._login_cga()
            self._variant = self.VARIANT_CGA
            log.info("Detected Vodafone Station variant: CGA (CGA6444VF/CGA4322DE)")
            return
        except Exception as e:
            log.debug("CGA login attempt failed: %s — trying TG variant", e)
            self._session.cookies.clear()
            self._cga_token = None

        # Try TG
        try:
            self._login_tg()
            self._variant = self.VARIANT_TG
            log.info("Detected Vodafone Station variant: TG (TG3442DE)")
            return
        except Exception as e:
            log.error("TG login attempt also failed: %s", e)
            self._session.cookies.clear()
            self._tg_nonce = None
            self._tg_key = None
            raise RuntimeError(
                "Vodafone Station authentication failed. "
                "Could not detect hardware variant (tried CGA and TG flows). "
                "Check URL, username, and password."
            )

    # ── CGA Variant (CGA6444VF / CGA4322DE) ──────────────────

    def _login_cga(self) -> None:
        """CGA auth: double PBKDF2-SHA256.

        1. POST /api/v1/session/login with password=seeksalthash → salt + saltwebui
        2. hash1 = PBKDF2(password, salt, 1000, 16).hex()
        3. hash2 = PBKDF2(hash1, saltwebui, 1000, 16).hex()
        4. POST /api/v1/session/login with password=hash2 + logout=true
        """
        if self._cga_token and self._session.cookies:
            log.debug("CGA session active, skipping login")
            return

        self._session.cookies.clear()
        self._cga_token = None

        # Step 1: Request salts
        r1 = self._session.post(
            f"{self._url}/api/v1/session/login",
            json={"username": self._user, "password": "seeksalthash"},
            timeout=10,
        )
        r1.raise_for_status()
        salt_data = r1.json()

        salt = salt_data.get("salt", "")
        salt_webui = salt_data.get("saltwebui", "")
        if not salt or not salt_webui:
            raise RuntimeError("CGA: No salt/saltwebui in response")

        # Step 2: First PBKDF2 — password + salt → hash1
        kdf1 = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=16,
            salt=salt.encode("utf-8"),
            iterations=1000,
        )
        hash1 = kdf1.derive(self._password.encode("utf-8")).hex()

        # Step 3: Second PBKDF2 — hash1 + saltwebui → hash2
        kdf2 = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=16,
            salt=salt_webui.encode("utf-8"),
            iterations=1000,
        )
        hash2 = kdf2.derive(hash1.encode("utf-8")).hex()

        # Step 4: Login with derived hash
        r2 = self._session.post(
            f"{self._url}/api/v1/session/login",
            json={
                "username": self._user,
                "password": hash2,
                "logout": True,  # Force logout stale sessions
            },
            timeout=10,
        )
        r2.raise_for_status()
        login_data = r2.json()

        error = login_data.get("error")
        if error:
            raise RuntimeError(f"CGA login error: {error}")

        self._cga_token = login_data.get("token", "")
        log.info("CGA auth OK (cookies: %s)", list(self._session.cookies.keys()))

    def _cga_request(self, method: str, path: str, **kwargs) -> requests.Response:
        """Make an authenticated request to the CGA API."""
        headers = kwargs.pop("headers", {})
        if self._cga_token:
            headers["X-CSRF-TOKEN"] = self._cga_token
        r = self._session.request(
            method,
            f"{self._url}{path}",
            headers=headers,
            timeout=10,
            **kwargs,
        )
        r.raise_for_status()
        return r

    def _get_docsis_cga(self) -> dict:
        """CGA: Fetch DOCSIS data from JSON API."""
        try:
            r = self._cga_request("GET", "/api/v1/sta_docsis_status")
            data = r.json()
        except requests.RequestException as e:
            self._invalidate_cga_session()
            raise RuntimeError(f"CGA DOCSIS data retrieval failed: {e}")

        downstream = []
        upstream = []

        for ch in data.get("downstream", []):
            try:
                channel_id = str(ch.get("channelID", ch.get("channelId", "")))
                freq = self._parse_number(ch.get("frequency", "0"))
                power = self._parse_number(ch.get("powerLevel", ch.get("power", "0")))
                snr = self._parse_number(
                    ch.get("snr", ch.get("mer", ch.get("mse", "0")))
                )
                if snr < 0:
                    snr = abs(snr)
                modulation = self._normalize_modulation(ch.get("modulation", ""))
                corr = int(self._parse_number(
                    ch.get("correctedErrors", ch.get("corrErrors", "0"))
                ))
                uncorr = int(self._parse_number(
                    ch.get("uncorrectedErrors", ch.get("nonCorrErrors", "0"))
                ))

                if freq > 1_000_000:
                    freq = freq / 1_000_000

                downstream.append({
                    "channelID": channel_id,
                    "type": modulation,
                    "frequency": f"{int(freq)} MHz" if freq else "",
                    "powerLevel": power,
                    "mse": -snr if snr else None,
                    "mer": snr if snr else None,
                    "latency": 0,
                    "corrError": corr,
                    "nonCorrError": uncorr,
                })
            except (ValueError, TypeError) as e:
                log.warning("Failed to parse CGA DS channel %s: %s", ch, e)

        for ch in data.get("upstream", []):
            try:
                channel_id = str(ch.get("channelID", ch.get("channelId", "")))
                freq = self._parse_number(ch.get("frequency", "0"))
                power = self._parse_number(ch.get("powerLevel", ch.get("power", "0")))
                modulation = self._normalize_modulation(ch.get("modulation", ""))

                if freq > 1_000_000:
                    freq = freq / 1_000_000

                upstream.append({
                    "channelID": channel_id,
                    "type": modulation,
                    "frequency": f"{int(freq)} MHz" if freq else "",
                    "powerLevel": power,
                    "multiplex": ch.get("multiplex", ""),
                })
            except (ValueError, TypeError) as e:
                log.warning("Failed to parse CGA US channel %s: %s", ch, e)

        return {
            "docsis": "3.1",
            "downstream": downstream,
            "upstream": upstream,
        }

    def _get_device_info_cga(self) -> dict:
        """CGA: Retrieve device info from API."""
        try:
            r = self._cga_request("GET", "/api/v1/sta_device_info")
            info = r.json()
            return {
                "manufacturer": info.get("manufacturer", "Arris"),
                "model": info.get("modelName", info.get("model", "Vodafone Station")),
                "sw_version": info.get("softwareVersion", info.get("swVersion", "")),
            }
        except Exception:
            return {
                "manufacturer": "Arris",
                "model": "Vodafone Station (CGA)",
                "sw_version": "",
            }

    def _invalidate_cga_session(self) -> None:
        """Clear CGA session state."""
        self._cga_token = None
        self._session.cookies.clear()

    # ── TG Variant (TG3442DE) ─────────────────────────────────

    def _login_tg(self) -> None:
        """TG auth: AES-CCM encrypted credentials (Arris TG3442DE).

        Based on arris-tg3442de-exporter and vodafone-station-cli:
        1. GET login page -> extract currentSessionId, myIv, mySalt from JS
        2. PBKDF2 key derivation (SHA256, 1000 iterations, 16 bytes)
        3. AES-CCM encrypt with AAD "loginPassword"
        4. POST /php/ajaxSet_Password.php as JSON
        5. Decrypt CSRF nonce from response
        """
        from Crypto.Cipher import AES

        if self._tg_nonce and self._session.cookies:
            log.debug("TG session active, skipping login")
            return

        self._session.cookies.clear()
        self._tg_nonce = None
        self._tg_key = None
        self._tg_iv = None

        # Step 1: Get login page and extract JS variables
        r = self._session.get(f"{self._url}/", timeout=10)
        r.raise_for_status()
        html = r.text

        session_id = self._extract_js_var(html, "currentSessionId")
        iv_hex = self._extract_js_var(html, "myIv")
        salt_hex = self._extract_js_var(html, "mySalt")

        if not all([session_id, iv_hex, salt_hex]):
            raise RuntimeError(
                "TG: Could not extract session variables from login page "
                f"(sessionId={bool(session_id)}, myIv={bool(iv_hex)}, "
                f"mySalt={bool(salt_hex)})"
            )

        # Validate hex format before parsing
        self._validate_hex(salt_hex, "mySalt")
        self._validate_hex(iv_hex, "myIv")
        log.debug("TG extracted: sessionId=%s..., myIv=%s, mySalt=%s",
                   session_id[:8], iv_hex, salt_hex)

        # Step 2: Derive AES key via PBKDF2
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=16,
            salt=bytes.fromhex(salt_hex),
            iterations=1000,
        )
        key = kdf.derive(self._password.encode("utf-8"))

        # Step 3: Encrypt credentials with AES-CCM
        # Full IV as nonce (8 bytes from 16 hex chars), 16-byte tag, AAD
        payload_str = json.dumps({"Password": self._password, "Nonce": session_id})
        iv_bytes = bytes.fromhex(iv_hex)
        auth_data = "loginPassword"

        cipher = AES.new(key, AES.MODE_CCM, nonce=iv_bytes, mac_len=16)
        cipher.update(auth_data.encode("utf-8"))
        ciphertext = cipher.encrypt(payload_str.encode("utf-8"))
        tag = cipher.digest()
        encrypted_hex = (ciphertext + tag).hex()

        # Step 4: POST login as JSON
        r2 = self._session.post(
            f"{self._url}/php/ajaxSet_Password.php",
            headers={"Content-Type": "application/json"},
            data=json.dumps({
                "EncryptData": encrypted_hex,
                "Name": self._user,
                "AuthData": auth_data,
            }),
            timeout=10,
        )
        r2.raise_for_status()

        # Step 5: Parse response and extract CSRF nonce
        try:
            resp = r2.json()
        except json.JSONDecodeError:
            raise RuntimeError("TG: Login response is not valid JSON")

        if resp.get("p_status") == "Lockout":
            raise RuntimeError(
                "TG: Account locked out (too many failed attempts). "
                "Wait a few minutes or reboot the modem."
            )
        if resp.get("p_status") == "Fail":
            raise RuntimeError("TG: Authentication failed (invalid password)")

        encrypted_nonce = resp.get("encryptData", "")
        if encrypted_nonce:
            enc_bytes = bytes.fromhex(encrypted_nonce)
            ct_part = enc_bytes[:-16]
            tag_part = enc_bytes[-16:]
            decipher = AES.new(key, AES.MODE_CCM, nonce=iv_bytes, mac_len=16)
            decipher.update(b"nonce")
            decrypted = decipher.decrypt_and_verify(ct_part, tag_part)
            self._tg_nonce = decrypted.decode("utf-8")[:32]
        else:
            self._tg_nonce = resp.get("nonce", session_id)

        self._tg_key = key
        self._tg_iv = iv_bytes
        log.info("TG auth OK")

    def _get_docsis_tg(self) -> dict:
        """TG: Fetch DOCSIS data via AJAX endpoint."""
        if not self._tg_nonce:
            raise RuntimeError("TG: Not authenticated. Call login() first.")

        try:
            r = self._session.post(
                f"{self._url}/php/ajaxGet_device_networkstatus_498.html",
                data={"csrfNonce": self._tg_nonce, "columns": "all"},
                timeout=10,
            )
            r.raise_for_status()
            data = r.json()
        except requests.RequestException as e:
            self._invalidate_tg_session()
            raise RuntimeError(f"TG DOCSIS data retrieval failed: {e}")
        except json.JSONDecodeError:
            self._invalidate_tg_session()
            raise RuntimeError("TG: DOCSIS response is not valid JSON")

        downstream = []
        upstream = []

        # Downstream SC-QAM channels (DOCSIS 3.0)
        for ch in data.get("ds_sc_qam", data.get("downstream", [])):
            try:
                channel_id = str(ch.get("channelID", ch.get("channelId", "")))
                freq = self._parse_number(ch.get("frequency", "0"))
                power = self._parse_number(ch.get("powerLevel", ch.get("power", "0")))
                snr = self._parse_number(ch.get("snr", ch.get("mse", "0")))
                if snr < 0:
                    snr = abs(snr)
                modulation = self._normalize_modulation(ch.get("modulation", ""))
                corr = int(self._parse_number(
                    ch.get("correctedErrors", ch.get("corrErrors", "0"))
                ))
                uncorr = int(self._parse_number(
                    ch.get("uncorrectedErrors", ch.get("nonCorrErrors", "0"))
                ))

                if freq > 1_000_000:
                    freq = freq / 1_000_000

                downstream.append({
                    "channelID": channel_id,
                    "type": modulation,
                    "frequency": f"{int(freq)} MHz" if freq else "",
                    "powerLevel": power,
                    "mse": -snr if snr else None,
                    "mer": snr if snr else None,
                    "latency": 0,
                    "corrError": corr,
                    "nonCorrError": uncorr,
                })
            except (ValueError, TypeError) as e:
                log.warning("Failed to parse TG DS channel %s: %s", ch, e)

        # Downstream OFDM channels (DOCSIS 3.1)
        for ch in data.get("ds_ofdm", []):
            try:
                channel_id = str(ch.get("channelID", ch.get("channelId", "")))
                freq = self._parse_number(ch.get("frequency", "0"))
                power = self._parse_number(ch.get("powerLevel", ch.get("power", "0")))
                mer = self._parse_number(ch.get("mer", ch.get("snr", "0")))
                modulation = self._normalize_modulation(ch.get("modulation", "ofdm"))
                corr = int(self._parse_number(ch.get("correctedErrors", "0")))
                uncorr = int(self._parse_number(ch.get("uncorrectedErrors", "0")))

                if freq > 1_000_000:
                    freq = freq / 1_000_000

                downstream.append({
                    "channelID": channel_id,
                    "type": modulation or "ofdm",
                    "frequency": f"{int(freq)} MHz" if freq else "",
                    "powerLevel": power,
                    "mse": None,
                    "mer": mer if mer else None,
                    "latency": 0,
                    "corrError": corr,
                    "nonCorrError": uncorr,
                })
            except (ValueError, TypeError) as e:
                log.warning("Failed to parse TG DS OFDM channel %s: %s", ch, e)

        # Upstream SC-QAM channels
        for ch in data.get("us_sc_qam", data.get("upstream", [])):
            try:
                channel_id = str(ch.get("channelID", ch.get("channelId", "")))
                freq = self._parse_number(ch.get("frequency", "0"))
                power = self._parse_number(ch.get("powerLevel", ch.get("power", "0")))
                modulation = self._normalize_modulation(ch.get("modulation", ""))

                if freq > 1_000_000:
                    freq = freq / 1_000_000

                upstream.append({
                    "channelID": channel_id,
                    "type": modulation,
                    "frequency": f"{int(freq)} MHz" if freq else "",
                    "powerLevel": power,
                    "multiplex": ch.get("multiplex", ""),
                })
            except (ValueError, TypeError) as e:
                log.warning("Failed to parse TG US channel %s: %s", ch, e)

        # Upstream OFDMA channels (DOCSIS 3.1)
        for ch in data.get("us_ofdma", []):
            try:
                channel_id = str(ch.get("channelID", ch.get("channelId", "")))
                freq = self._parse_number(ch.get("frequency", "0"))
                power = self._parse_number(ch.get("powerLevel", ch.get("power", "0")))
                modulation = self._normalize_modulation(ch.get("modulation", "ofdma"))

                if freq > 1_000_000:
                    freq = freq / 1_000_000

                upstream.append({
                    "channelID": channel_id,
                    "type": modulation or "ofdma",
                    "frequency": f"{int(freq)} MHz" if freq else "",
                    "powerLevel": power,
                    "multiplex": ch.get("multiplex", ""),
                })
            except (ValueError, TypeError) as e:
                log.warning("Failed to parse TG US OFDMA channel %s: %s", ch, e)

        return {
            "docsis": "3.1",
            "downstream": downstream,
            "upstream": upstream,
        }

    def _invalidate_tg_session(self) -> None:
        """Clear TG session state."""
        self._tg_nonce = None
        self._tg_key = None
        self._tg_iv = None
        self._session.cookies.clear()

    # ── Helpers ───────────────────────────────────────────────

    @staticmethod
    def _extract_js_var(html: str, var_name: str) -> str | None:
        """Extract JavaScript variable value from HTML source."""
        pattern = rf"""var\s+{re.escape(var_name)}\s*=\s*['"]([^'"]+)['"]"""
        match = re.search(pattern, html)
        return match.group(1) if match else None

    @staticmethod
    def _validate_hex(value: str, name: str) -> None:
        """Validate that a string contains only hex characters."""
        if not all(c in "0123456789abcdefABCDEF" for c in value):
            raise RuntimeError(
                f"TG: {name} is not a valid hex string: {value!r}"
            )

    @staticmethod
    def _parse_number(value) -> float:
        """Parse numeric value from string, handling units and whitespace."""
        if isinstance(value, (int, float)):
            return float(value)
        if not value or not isinstance(value, str):
            return 0.0
        parts = value.strip().split()
        try:
            return float(parts[0])
        except (IndexError, ValueError):
            return 0.0

    @staticmethod
    def _normalize_modulation(modulation: str) -> str:
        """Normalize modulation string to analyzer format.

        Input: "256QAM", "64QAM", "OFDM", "4096QAM"
        Output: "qam_256", "qam_64", "ofdm", "qam_4096"
        """
        if not modulation:
            return ""
        mod = modulation.upper().replace("-", "")
        if "OFDMA" in mod:
            return "ofdma"
        if "OFDM" in mod:
            return "ofdm"
        if "QAM" in mod:
            num = mod.replace("QAM", "")
            return f"qam_{num}" if num else "qam"
        return modulation.lower()
