"""Vodafone Ultra Hub 7 (Sercomm) driver for DOCSIS data retrieval.

This driver implements AES-CCM + PBKDF2-HMAC-SHA256 authentication
and fetches DOCSIS channel data via clean JSON APIs.

Based on HAR analysis from Tmo-Dev and aiovodafone patterns.
"""

from __future__ import annotations

import base64
import json
import logging
import os

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from .base import ModemDriver
from .formats.vodafone import (
    parse_ultrahub7_downstream,
    parse_ultrahub7_json,
    parse_ultrahub7_upstream,
)
from .utils import pbkdf2_sha256
from ..types import DocsisData, DeviceInfo, ConnectionInfo, RawChannel

log = logging.getLogger("docsis.driver.ultrahub7")


class UltraHub7Driver(ModemDriver):
    """Driver for Vodafone Ultra Hub 7 (Sercomm DOCSIS 3.1).

    Authentication uses AES-CCM encryption with PBKDF2-HMAC-SHA256 key derivation.
    DOCSIS data is fetched via clean JSON API endpoints.
    """

    FORMAT_FAMILIES = ("ultrahub7_json",)

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        self._session = requests.Session()  # Persistent session for cookie handling
        self._csrf_token = None
        self._router_id = "3"  # Default ID, will be updated from router

    def login(self) -> None:
        """Authenticate with AES-CCM encrypted credentials.

        Based on aiovodafone VodafoneStationUltraHubApi implementation.
        Called before each poll cycle — skips re-auth if session is still active.
        """
        if self._csrf_token and self._session.cookies:
            log.debug("Session active, skipping login")
            return

        # Up to 2 attempts: initial login + 1 retry if duplicate session detected.
        # The initial GET to fetch the CSRF token sets a DUKSID cookie that is NOT
        # an authenticated session cookie. If the router reports a duplicate session
        # (e.g. from the setup wizard), we must clear the stale cookie and retry.
        for attempt in range(2):
            self._session.cookies.clear()
            self._csrf_token = None

            # Headers required for AJAX requests (CSRF protection + Priority)
            headers = {
                "User-Agent": "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:78.0) Gecko/20100101 Firefox/78.0",
                "X-Requested-With": "XMLHttpRequest",
                "Accept-Language": "en-GB,en;q=0.5",
                "Priority": "u=1",
            }

            try:
                # Step 1: Initial request to get router ID and CSRF token
                init_url = f"{self._url}/api/config/details.jst"
                r_init = self._session.get(
                    init_url,
                    params={"X_INTERNAL_FIELDS": "X_RDK_ONT_Veip_1_OperationalState"},
                    headers=headers,
                    timeout=10
                )
                r_init.raise_for_status()
                init_response = r_init.json()

                # Extract router ID if present
                if "X_INTERNAL_ID" in init_response:
                    self._router_id = init_response["X_INTERNAL_ID"]

                # Extract CSRF token if present
                if "csrf_token" in init_response:
                    self._csrf_token = init_response["csrf_token"]

                if not self._csrf_token:
                    raise RuntimeError("CSRF token not found in initial response")

                log.info("Got router ID: %s, CSRF token: %s...", self._router_id, self._csrf_token[:8])

                # Step 2: Get WebUISecret from device
                details_url = f"{self._url}/api/users/details.jst"
                r = self._session.get(
                    details_url,
                    params={
                        "__id": self._router_id,
                        "X_INTERNAL_FIELDS": "X_VODAFONE_WebUISecret"
                    },
                    headers=headers,
                    timeout=10
                )
                r.raise_for_status()
                details = r.json()

                web_ui_secret = details.get("X_VODAFONE_WebUISecret", "")
                if not web_ui_secret:
                    raise RuntimeError("X_VODAFONE_WebUISecret not found in device response")

                # Parse WebUISecret: <salt_web_ui (10 chars)><salt (rest)>
                salt_web_ui = web_ui_secret[:10]
                salt = web_ui_secret[10:]

                # Step 3: Derive encryption key with PBKDF2-HMAC-SHA256
                key = pbkdf2_sha256(
                    bytes(salt_web_ui, "utf-8"),
                    bytes(salt, "utf-8"),
                )

                # Step 4: Encrypt password with AES-CCM
                iv = os.urandom(16)
                nonce = self._truncate_iv(iv, len(self._password) * 8, 8)

                aes_ccm = AESCCM(key, tag_length=8)
                encrypted_password = aes_ccm.encrypt(
                    nonce,
                    bytes(self._password, "utf-8"),
                    None  # No additional authenticated data
                )

                # Step 5: Build encrypted password payload (base64-encoded JSON)
                b64_ct = base64.b64encode(encrypted_password).decode("ascii").strip()
                b64_iv = base64.b64encode(iv).decode("ascii").strip()

                password_payload = {
                    "iv": b64_iv,
                    "v": 1,
                    "iter": 1000,
                    "ks": 128,
                    "ts": 64,
                    "mode": "ccm",
                    "adata": "",
                    "cipher": "aes",
                    "ct": b64_ct,
                }

                encrypted_password_json = json.dumps(password_payload)

                # Step 6: POST login request
                login_url = f"{self._url}/api/users/login.jst"
                login_payload = {
                    "__id": self._router_id,
                    "X_VODAFONE_Password": encrypted_password_json,
                    "Push": "true",  # Force logout stale sessions (DOCSight is primary client)
                    "csrf_token": self._csrf_token,
                }

                r2 = self._session.post(
                    login_url,
                    data=login_payload,  # Form data, not JSON
                    headers=headers,  # AJAX headers for CSRF protection
                    timeout=10
                )
                r2.raise_for_status()

                # Step 7: Validate login response
                login_response = r2.json()

                if login_response.get("X_INTERNAL_Password_Status") == "Invalid_PWD":
                    raise RuntimeError("Invalid password")

                if login_response.get("X_INTERNAL_Is_Duplicate") == "true":
                    if attempt > 0:
                        raise RuntimeError(
                            "Router still reports duplicate session after retry. "
                            "Another client may be logged in. Try again in a few minutes."
                        )
                    # Push=true should have killed the old session, but the DUKSID
                    # cookie from the initial GET is NOT an authenticated cookie.
                    # Clear everything and redo the full login flow.
                    log.info("Duplicate session detected, clearing cookies and retrying full login...")
                    continue

                # Update CSRF token from response if present
                if "csrf_token" in login_response:
                    self._csrf_token = login_response["csrf_token"]

                log.info("Auth OK (session cookies: %s)", list(self._session.cookies.keys()))
                return  # Success

            except requests.RequestException as e:
                log.error("Login failed: %s", e)
                raise RuntimeError(f"Ultra Hub 7 authentication failed: {e}")

    def _truncate_iv(self, iv: bytes, ol: int, tlen: int) -> bytes:
        """Calculate CCM nonce by truncating IV.
        
        Based on aiovodafone implementation.
        
        Args:
            iv: 16-byte initialization vector
            ol: Output length in bits (including tag)
            tlen: Tag length in bytes
            
        Returns:
            Truncated nonce for AES-CCM
        """
        ivl = len(iv)  # IV length in bytes
        ol = (ol - tlen) // 8  # Convert to bytes

        # Compute the length of the length field (L parameter)
        loop = 2
        max_length_field_bytes = 4  # Maximum L per CCM spec
        while (loop < max_length_field_bytes) and (ol >> (8 * loop)) > 0:
            loop += 1
        loop = max(loop, 15 - ivl)

        return iv[: (15 - loop)]

    def get_docsis_data(self) -> DocsisData:
        """Retrieve raw DOCSIS channel data."""
        if not self._csrf_token:
            raise RuntimeError("Not authenticated. Call login() first.")

        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Fedora; Linux x86_64; rv:78.0) Gecko/20100101 Firefox/78.0",
            "X-Requested-With": "XMLHttpRequest",
            "Accept-Language": "en-GB,en;q=0.5",
            "Priority": "u=1",
        }

        try:
            ds_url = f"{self._url}/api/docsis/downstream/list.jst"
            ds_response = self._session.get(
                ds_url,
                headers=headers,
                timeout=10
            )
            ds_response.raise_for_status()
            ds_data = ds_response.json()

            us_url = f"{self._url}/api/docsis/upstream/list.jst"
            us_response = self._session.get(
                us_url,
                headers=headers,
                timeout=10
            )
            us_response.raise_for_status()
            us_data = us_response.json()

            return parse_ultrahub7_json({
                "downstream": ds_data.get("channels", []),
                "upstream": us_data.get("channels", []),
            }).value

        except requests.RequestException as e:
            log.error("Failed to fetch DOCSIS data: %s", e)
            # Invalidate session so next poll triggers fresh login
            self._csrf_token = None
            self._session.cookies.clear()
            raise RuntimeError(f"DOCSIS data retrieval failed: {e}")

    def get_device_info(self) -> DeviceInfo:
        """Retrieve device model and firmware info."""
        # Ultra Hub 7 doesn't expose device info via a dedicated endpoint
        # Return static info based on driver
        return {
            "manufacturer": "Sercomm",
            "model": "Vodafone Ultra Hub 7",
            "sw_version": "",  # Not available via API
        }

    def get_connection_info(self) -> ConnectionInfo:
        """Retrieve internet connection info (speeds, type)."""
        # Ultra Hub 7 doesn't expose connection info via DOCSIS API
        # Return empty dict (will use Fritz!Box fallback in analyzer)
        return {}

    def _parse_downstream_channels(self, channels: list[dict[str, str]]) -> list[RawChannel]:
        return parse_ultrahub7_downstream(channels).value

    def _parse_upstream_channels(self, channels: list[dict[str, str]]) -> list[RawChannel]:
        return parse_ultrahub7_upstream(channels).value
