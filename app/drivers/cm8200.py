"""Arris Touchstone CM8200A driver for DOCSight.

The CM8200A is an ISP-branded Arris DOCSIS 3.1 cable modem (Comcast
reference design) with a traditional HTML web UI served by micro_httpd.
Authentication uses base64-encoded credentials in the query string.
The auth endpoint returns a session token. Due to a firmware bug, the
modem's Set-Cookie response header is malformed and browsers cannot parse
it automatically. Instead, the browser JS (main_arris.js) manually writes
both the credential token and the raw malformed cookie string to
document.cookie. Requests must replicate this by sending a hand-crafted
Cookie header on every subsequent request:

  Cookie: HttpOnly: true, Secure: true; credential=<token>

If the modem returns 4170 bytes (the login page), it is either rejecting
the session or in a 5-minute brute-force lockout with no feedback.

Channel data is on /cmconnectionstatus.html in two HTML tables:
- "Downstream Bonded Channels" (8 columns)
- "Upstream Bonded Channels" (7 columns)

DOCSIS version is inferred from modulation/channel type:
- DS: "Other" modulation = OFDM (3.1), anything else = SC-QAM (3.0)
- US: "OFDM Upstream" type = OFDMA (3.1), "SC-QAM Upstream" = 3.0
"""

from __future__ import annotations

import base64
import logging

import requests
from bs4 import BeautifulSoup

from .arris_html import parse_arris_channel_tables
from .base import ModemDriver
from ..types import DocsisData, DeviceInfo, ConnectionInfo
from .utils import make_legacy_tls_adapter

log = logging.getLogger("docsis.driver.cm8200")


class CM8200Driver(ModemDriver):
    """Driver for Arris Touchstone CM8200A DOCSIS 3.1 cable modem.

    Authentication uses base64(user:pass) in the query string.
    The auth response is a session token that must be sent back via a
    hand-crafted Cookie header (malformed Set-Cookie workaround).
    """

    def __init__(self, url: str, user: str, password: str):
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
            log.info("CM8200 requires HTTPS, upgraded URL to %s", url)
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._session.verify = False
        self._session.mount("https://", make_legacy_tls_adapter(sec_level=0))
        self._status_html = None
        self._cookie_header = None

    def login(self) -> None:
        """Authenticate with the CM8200A, reusing IP-based sessions.

        The CM8200A uses IP-based session management.  After a successful
        credential GET, subsequent bare GETs from the same IP return the
        status page without needing credentials again.  The modem has a
        brute-force lockout (~5 minutes) that triggers after a few
        credential GETs in quick succession, so we minimise credential
        requests by trying to reuse the existing session first.

        Flow:
          1. Probe: bare GET /cmconnectionstatus.html (no credentials).
             If the modem still recognises our IP, it returns the status
             page (~12 kB) and we skip credential auth entirely.
          2. If the probe returns the login page (~4 kB), check the
             lockout endpoint before sending credentials.
          3. Full auth: GET /cmconnectionstatus.html?{base64creds} to
             obtain a session token, then GET the status page.
        """
        self._status_html = None

        # Phase 1: try reusing existing IP-based session
        if self._try_session_reuse():
            return

        # Phase 2: check lockout before sending credentials
        self._check_lockout()

        # Phase 3: full credential-based auth
        self._credential_auth()

    def _try_session_reuse(self) -> bool:
        """Attempt to fetch the status page without sending credentials.

        Returns True if the session is still valid and _status_html is set.
        """
        try:
            headers = {"Cookie": self._cookie_header} if self._cookie_header else {}
            r = self._session.get(
                f"{self._url}/cmconnectionstatus.html",
                headers=headers,
                timeout=30,
            )
            r.raise_for_status()
            if len(r.text) > 5000 and "downstream bonded" in r.text.lower():
                self._status_html = r.text
                log.info("CM8200 session reused")
                return True
            log.debug("CM8200 session expired, re-authenticating")
        except requests.RequestException:
            log.debug("CM8200 session probe failed, re-authenticating")
        return False

    def _check_lockout(self) -> None:
        """Check the modem's brute-force lockout status before sending credentials."""
        try:
            r = self._session.get(
                f"{self._url}/Admin_Login_Lock.txt",
                timeout=10,
            )
            if r.text.strip() == "Locked":
                raise RuntimeError(
                    "CM8200 modem is in brute-force lockout. "
                    "Wait 5 minutes or reboot the modem."
                )
        except requests.RequestException:
            pass  # If the check fails, proceed with auth attempt

    def _credential_auth(self) -> None:
        """Full credential-based authentication flow."""
        creds = base64.b64encode(f"{self._user}:{self._password}".encode()).decode()
        for attempt in range(2):
            try:
                r1 = self._session.get(
                    f"{self._url}/cmconnectionstatus.html?{creds}",
                    timeout=30,
                )
                r1.raise_for_status()
                token = r1.text.strip()

                # The auth endpoint returns a short alphanumeric token.
                # If we got HTML instead, the modem rejected credentials
                # or is in brute-force lockout.
                if len(token) > 64 or not token.isalnum():
                    raise RuntimeError(
                        "CM8200 auth failed: expected session token but received "
                        f"{len(token)} bytes (wrong credentials or brute-force "
                        "lockout, wait 5 minutes)"
                    )

                # Replicate the browser JS cookie workaround
                self._cookie_header = f"HttpOnly: true, Secure: true; credential={token}"

                r = self._session.get(
                    f"{self._url}/cmconnectionstatus.html",
                    headers={"Cookie": self._cookie_header},
                    timeout=30,
                )
                r.raise_for_status()

                if len(r.text) < 5000 or "downstream bonded" not in r.text.lower():
                    raise RuntimeError(
                        "CM8200 auth succeeded but status page not returned "
                        f"({len(r.text)} bytes). Modem may be in brute-force "
                        "lockout (wait 5 minutes)."
                    )

                self._status_html = r.text
                log.info("CM8200 auth OK")
                return
            except requests.ConnectionError:
                if attempt == 0:
                    log.warning("CM8200 connection lost, retrying with fresh session")
                    self._session.close()
                    self._session = requests.Session()
                    self._session.verify = False
                    self._session.mount("https://", make_legacy_tls_adapter(sec_level=0))
                    continue
                raise RuntimeError("CM8200 authentication failed: connection refused after retry")
            except requests.RequestException as e:
                raise RuntimeError(f"CM8200 authentication failed: {e}")

    def get_docsis_data(self) -> DocsisData:
        """Retrieve DOCSIS channel data from HTML tables on status page."""
        soup = self._fetch_status_page()
        return parse_arris_channel_tables(str(soup))

    def get_device_info(self) -> DeviceInfo:
        """Retrieve device info from status page."""
        try:
            soup = self._fetch_status_page()
            model_span = soup.find("span", id="thisModelNumberIs")
            model = model_span.get_text(strip=True) if model_span else "CM8200A"
            return {
                "manufacturer": "Arris",
                "model": model,
                "sw_version": "",
            }
        except Exception:
            return {"manufacturer": "Arris", "model": "CM8200A", "sw_version": ""}

    def get_connection_info(self) -> ConnectionInfo:
        """CM8200A is a standalone modem with no connection info."""
        return {}

    def _fetch_status_page(self) -> BeautifulSoup:
        """Fetch and parse the status page HTML.

        Reuses cached HTML from login for the entire poll cycle.  The
        cache is refreshed on the next ``login()`` call, so both
        ``get_device_info()`` and ``get_docsis_data()`` share the same
        snapshot without triggering a second auth round-trip.

        If no cache is available (e.g. session expired mid-poll), tries
        session reuse first, then falls back to full credential auth.
        """
        if self._status_html:
            log.debug("CM8200 using cached status HTML (%d bytes)", len(self._status_html))
            return BeautifulSoup(self._status_html, "html.parser")

        # Try session reuse before sending credentials
        if self._try_session_reuse():
            return BeautifulSoup(self._status_html, "html.parser")

        self._check_lockout()
        self._credential_auth()
        return BeautifulSoup(self._status_html, "html.parser")

