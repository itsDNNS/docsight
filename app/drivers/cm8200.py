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

import base64
import logging
import ssl

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.ssl_ import create_urllib3_context

from .base import ModemDriver

log = logging.getLogger("docsis.driver.cm8200")


class _LegacyTLSAdapter(HTTPAdapter):
    """Allow 1024-bit RSA keys for ancient modem certs.

    The CM8200A ships with a Broadcom factory certificate using a 1024-bit
    RSA key.  Modern OpenSSL defaults reject keys smaller than 2048 bits,
    causing a TLS handshake failure.  This adapter lowers the security
    level for connections to the modem only.
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = create_urllib3_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.set_ciphers("DEFAULT:@SECLEVEL=0")
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


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
        self._session.mount("https://", _LegacyTLSAdapter())
        self._status_html = None
        self._cookie_header = None

    def login(self) -> None:
        """Authenticate via base64 credentials in query string.

        The CM8200A auth flow:
          1. GET /cmconnectionstatus.html?{base64creds} returns a bare
             session token string (~31 alphanumeric chars, not HTML).
          2. The modem's Set-Cookie response header is malformed (firmware
             bug). The browser JS works around this by writing the literal
             Set-Cookie value + token into document.cookie, producing:
               Cookie: HttpOnly: true, Secure: true; credential=<token>
          3. Subsequent requests must include this Cookie header.

        Note: the modem has a 5-minute brute-force lockout with no visible
        error. It returns the login page (HTTP 200, ~4170 bytes) instead
        of the status page when locked out.
        """
        self._status_html = None
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
                    self._session.mount("https://", _LegacyTLSAdapter())
                    continue
                raise RuntimeError("CM8200 authentication failed: connection refused after retry")
            except requests.RequestException as e:
                raise RuntimeError(f"CM8200 authentication failed: {e}")

    def get_docsis_data(self) -> dict:
        """Retrieve DOCSIS channel data from HTML tables on status page.

        Returns pre-split format so the analyzer correctly labels
        SC-QAM channels as DOCSIS 3.0 and OFDM/OFDMA channels as 3.1.
        """
        soup = self._fetch_status_page()
        ds_table, us_table = self._find_channel_tables(soup)
        if not ds_table and not us_table:
            tables = soup.find_all("table")
            log.debug("CM8200 found %d tables but no channel tables", len(tables))
            for i, t in enumerate(tables[:5]):
                header = t.find("tr")
                log.debug("CM8200 table[%d] header: %s", i, header.get_text(strip=True)[:120] if header else "(none)")

        ds30, ds31 = self._parse_downstream(ds_table)
        us30, us31 = self._parse_upstream(us_table)

        return {
            "channelDs": {"docsis30": ds30, "docsis31": ds31},
            "channelUs": {"docsis30": us30, "docsis31": us31},
        }

    def get_device_info(self) -> dict:
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

    def get_connection_info(self) -> dict:
        """CM8200A is a standalone modem with no connection info."""
        return {}

    # -- Internal helpers --

    def _fetch_status_page(self) -> BeautifulSoup:
        """Fetch and parse the status page HTML.

        Reuses cached HTML from login for the entire poll cycle.  The
        cache is refreshed on the next ``login()`` call, so both
        ``get_device_info()`` and ``get_docsis_data()`` share the same
        snapshot without triggering a second auth round-trip.

        If no cache is available (e.g. session expired mid-poll), falls
        back to a full re-auth with the same validation as ``login()``.
        """
        if self._status_html:
            log.debug("CM8200 using cached status HTML (%d bytes)", len(self._status_html))
            return BeautifulSoup(self._status_html, "html.parser")

        creds = base64.b64encode(f"{self._user}:{self._password}".encode()).decode()
        try:
            r1 = self._session.get(
                f"{self._url}/cmconnectionstatus.html?{creds}",
                timeout=30,
            )
            token = r1.text.strip()

            if len(token) > 64 or not token.isalnum():
                raise RuntimeError(
                    "CM8200 re-auth failed: expected session token but received "
                    f"{len(token)} bytes (wrong credentials or brute-force "
                    "lockout, wait 5 minutes)"
                )

            self._cookie_header = f"HttpOnly: true, Secure: true; credential={token}"

            r = self._session.get(
                f"{self._url}/cmconnectionstatus.html",
                headers={"Cookie": self._cookie_header},
                timeout=30,
            )
            r.raise_for_status()

            if len(r.text) < 5000 or "downstream bonded" not in r.text.lower():
                raise RuntimeError(
                    "CM8200 re-auth succeeded but status page not returned "
                    f"({len(r.text)} bytes). Modem may be in brute-force "
                    "lockout (wait 5 minutes)."
                )
        except requests.RequestException as e:
            raise RuntimeError(f"CM8200 status page retrieval failed: {e}")

        self._status_html = r.text
        log.debug("CM8200 status page fetched (%d bytes)", len(r.text))
        return BeautifulSoup(r.text, "html.parser")

    @staticmethod
    def _find_channel_tables(soup) -> tuple:
        """Find downstream and upstream channel tables.

        Tables are identified by the text in their first header row:
        - "Downstream Bonded Channels" -> downstream
        - "Upstream Bonded Channels" -> upstream
        """
        ds_table = None
        us_table = None

        for table in soup.find_all("table"):
            header = table.find("tr")
            if not header:
                continue
            text = header.get_text(strip=True).lower()
            if "downstream bonded" in text:
                ds_table = table
            elif "upstream bonded" in text:
                us_table = table

        return ds_table, us_table

    @staticmethod
    def _is_header_row(row) -> bool:
        """True if row is a table title or column-header row (not data)."""
        if row.find("th"):
            return True
        if row.find("strong"):
            return True
        return False

    def _parse_downstream(self, table) -> tuple:
        """Parse downstream table into (docsis30, docsis31) channel lists.

        8 columns: Channel ID, Lock Status, Modulation, Frequency,
                   Power, SNR/MER, Corrected, Uncorrectables
        """
        ds30 = []
        ds31 = []
        if not table:
            return ds30, ds31

        rows = table.find_all("tr")
        for row in rows:
            if self._is_header_row(row):
                continue
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 8:
                continue

            lock_status = cells[1]
            if lock_status != "Locked":
                continue

            try:
                channel_id = int(cells[0])
                modulation = cells[2]
                frequency = self._parse_freq_hz(cells[3])
                power = self._parse_value(cells[4])
                snr = self._parse_value(cells[5])
                corrected = int(cells[6])
                uncorrectables = int(cells[7])

                channel = {
                    "channelID": channel_id,
                    "frequency": frequency,
                    "powerLevel": power,
                    "modulation": modulation,
                    "corrErrors": corrected,
                    "nonCorrErrors": uncorrectables,
                }

                if modulation == "Other":
                    # OFDM channel (DOCSIS 3.1)
                    channel["type"] = "OFDM"
                    channel["mer"] = snr
                    channel["mse"] = None
                    ds31.append(channel)
                else:
                    # SC-QAM channel (DOCSIS 3.0)
                    channel["mer"] = snr
                    channel["mse"] = -snr if snr is not None else None
                    ds30.append(channel)
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse CM8200 DS row: %s", e)

        return ds30, ds31

    def _parse_upstream(self, table) -> tuple:
        """Parse upstream table into (docsis30, docsis31) channel lists.

        7 columns: Channel, Channel ID, Lock Status, US Channel Type,
                   Frequency, Width, Power
        """
        us30 = []
        us31 = []
        if not table:
            return us30, us31

        rows = table.find_all("tr")
        for row in rows:
            if self._is_header_row(row):
                continue
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if len(cells) < 7:
                continue

            lock_status = cells[2]
            if lock_status != "Locked":
                continue

            try:
                channel_id = int(cells[1])
                channel_type = cells[3]
                frequency = self._parse_freq_hz(cells[4])
                power = self._parse_value(cells[6])

                channel = {
                    "channelID": channel_id,
                    "frequency": frequency,
                    "powerLevel": power,
                    "modulation": channel_type,
                }

                if "OFDM" in channel_type and "SC-QAM" not in channel_type:
                    # OFDMA channel (DOCSIS 3.1)
                    channel["type"] = "OFDMA"
                    channel["multiplex"] = ""
                    us31.append(channel)
                else:
                    # SC-QAM channel (DOCSIS 3.0)
                    channel["multiplex"] = "SC-QAM"
                    us30.append(channel)
            except (ValueError, TypeError, IndexError) as e:
                log.warning("Failed to parse CM8200 US row: %s", e)

        return us30, us31

    # -- Value parsers --

    @staticmethod
    def _parse_freq_hz(freq_str: str) -> str:
        """Convert '795000000 Hz' to '795 MHz'."""
        if not freq_str:
            return ""
        parts = freq_str.strip().split()
        try:
            hz = float(parts[0])
            mhz = hz / 1_000_000
            if mhz == int(mhz):
                return f"{int(mhz)} MHz"
            return f"{mhz:.1f} MHz"
        except (ValueError, IndexError):
            return freq_str

    @staticmethod
    def _parse_value(val_str: str):
        """Parse '8.2 dBmV' or '43.0 dB' to float."""
        if not val_str:
            return None
        parts = val_str.strip().split()
        try:
            return float(parts[0])
        except (ValueError, IndexError):
            return None
