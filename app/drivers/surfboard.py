"""Arris SURFboard HNAP driver for DOCSight.

Supports Arris/CommScope DOCSIS 3.1 SURFboard modems (S33, S34, SB8200)
that expose an HNAP1 JSON API at /HNAP1/.

Authentication is a two-phase HMAC-SHA256 handshake:
1. POST Action "request" -- server returns Challenge, Cookie, PublicKey
2. Derive PrivateKey = HMAC-SHA256(PublicKey+password, Challenge)
3. Derive LoginPassword = HMAC-SHA256(PrivateKey, Challenge)
4. POST Action "login" with LoginPassword
5. All subsequent requests use HNAP_AUTH header with timestamp-based HMAC

Channel data arrives as pipe-delimited strings ("|+|" between channels,
"^" between fields within a channel).
"""

import hashlib
import hmac
import logging
import time

import requests

from .base import ModemDriver

log = logging.getLogger("docsis.driver.surfboard")

_HNAP_LOGIN_URI = '"http://purenetworks.com/HNAP1/Login"'
_HNAP_MULTI_URI = '"http://purenetworks.com/HNAP1/GetMultipleHNAPs"'

# Fields per downstream channel (split by "^"):
# num ^ lock ^ modulation ^ channelID ^ frequency ^ power ^ snr ^ corrErrors ^ uncorrErrors ^
_DS_FIELDS = 9

# Fields per upstream channel (split by "^"):
# num ^ lock ^ type ^ channelID ^ width ^ frequency ^ power ^
_US_FIELDS = 7


class SurfboardDriver(ModemDriver):
    """Driver for Arris SURFboard DOCSIS 3.1 modems (S33/S34/SB8200).

    Uses HNAP1 JSON API with HMAC-SHA256 authentication.

    Session management: The modem tracks active sessions by IP address and
    only allows one concurrent login. Re-logging in while a session is active
    causes the modem to return ``LoginResult: RELOAD`` instead of a challenge.
    To avoid this, the driver reuses the existing session across polls and only
    re-authenticates when a request fails or when no session exists yet.
    """

    def __init__(self, url: str, user: str, password: str):
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
            log.info("SURFboard requires HTTPS, upgraded URL to %s", url)
        # Strip trailing path (users sometimes enter .../Login.html)
        url = url.rstrip("/")
        from urllib.parse import urlparse, urlunparse
        parsed = urlparse(url)
        if parsed.path and parsed.path != "/":
            url = urlunparse(parsed._replace(path=""))
            log.info("SURFboard stripped path from URL: %s", url)
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._session.verify = False
        self._private_key = ""
        self._cookie = ""
        self._logged_in = False

    def _fresh_session(self) -> None:
        """Reset HTTP session to clear stale cookies/state."""
        self._session.close()
        self._session = requests.Session()
        self._session.verify = False
        self._private_key = ""
        self._cookie = ""
        self._logged_in = False

    def login(self) -> None:
        """Two-phase HNAP login with HMAC-SHA256.

        Reuses the existing session if already authenticated. Only performs
        a fresh login when no session exists or after a failed request
        invalidated the session.

        Retries once with a fresh session on ConnectionError or when the
        modem returns no challenge (stale session / concurrent login).
        """
        if self._logged_in:
            return

        for attempt in range(3):
            try:
                self._fresh_session()
                self._do_login()
                log.info("SURFboard HNAP login OK")
                self._logged_in = True
                return
            except requests.ConnectionError:
                if attempt < 2:
                    log.warning("SURFboard connection lost, retrying with fresh session")
                    time.sleep(1)
                    continue
                raise RuntimeError("SURFboard login failed: connection refused after retry")
            except RuntimeError as e:
                if "no challenge received" in str(e) and attempt < 2:
                    log.warning("SURFboard no challenge received, retrying with fresh session")
                    time.sleep(2)
                    continue
                raise
            except requests.RequestException as e:
                raise RuntimeError(f"SURFboard login failed: {e}")

    def _do_login(self) -> None:
        """Execute the two-phase HNAP login handshake."""
        # Phase 1: request challenge
        body = {
            "Login": {
                "Action": "request",
                "Username": self._user,
                "LoginPassword": "",
                "Captcha": "",
                "PrivateLogin": "LoginPassword",
            }
        }
        resp = self._hnap_post("Login", body, auth=False)
        login_resp = resp.get("LoginResponse", {})

        challenge = login_resp.get("Challenge", "")
        cookie = login_resp.get("Cookie", "")
        public_key = login_resp.get("PublicKey", "")

        if not challenge or not public_key:
            log.debug("HNAP login response: %s", login_resp)
            raise RuntimeError("SURFboard login failed: no challenge received")

        # Derive keys
        self._private_key = hmac.new(
            (public_key + self._password).encode(),
            challenge.encode(),
            hashlib.sha256,
        ).hexdigest().upper()

        login_password = hmac.new(
            self._private_key.encode(),
            challenge.encode(),
            hashlib.sha256,
        ).hexdigest().upper()

        self._cookie = cookie
        self._session.cookies.set("uid", cookie)

        # Phase 2: login with derived password
        body = {
            "Login": {
                "Action": "login",
                "Username": self._user,
                "LoginPassword": login_password,
                "Captcha": "",
                "PrivateLogin": "LoginPassword",
            }
        }
        resp = self._hnap_post("Login", body, auth=False)
        login_resp = resp.get("LoginResponse", {})
        result = login_resp.get("LoginResult", "")

        if result != "OK":
            raise RuntimeError(f"SURFboard login failed: {result}")

    def get_docsis_data(self) -> dict:
        """Retrieve DOCSIS channel data via HNAP GetMultipleHNAPs.

        Retries once with a fresh login if the request fails (expired session).
        """
        try:
            return self._fetch_docsis_data()
        except requests.HTTPError as e:
            log.warning("DOCSIS data fetch failed (HTTP %d), re-authenticating",
                        e.response.status_code if e.response is not None else 0)
            self._logged_in = False
            self.login()
            return self._fetch_docsis_data()

    def _fetch_docsis_data(self) -> dict:
        """Internal: fetch and parse DOCSIS channel data."""
        body = {
            "GetMultipleHNAPs": {
                "GetCustomerStatusDownstreamChannelInfo": "",
                "GetCustomerStatusUpstreamChannelInfo": "",
            }
        }
        resp = self._hnap_post("GetMultipleHNAPs", body)
        multi = resp.get("GetMultipleHNAPsResponse", {})

        ds_raw = (
            multi.get("GetCustomerStatusDownstreamChannelInfoResponse", {})
            .get("CustomerConnDownstreamChannel", "")
        )
        us_raw = (
            multi.get("GetCustomerStatusUpstreamChannelInfoResponse", {})
            .get("CustomerConnUpstreamChannel", "")
        )

        ds30, ds31 = self._parse_downstream(ds_raw)
        us30, us31 = self._parse_upstream(us_raw)

        return {
            "channelDs": {"docsis30": ds30, "docsis31": ds31},
            "channelUs": {"docsis30": us30, "docsis31": us31},
        }

    def get_device_info(self) -> dict:
        """Retrieve device model and firmware from HNAP."""
        try:
            body = {
                "GetMultipleHNAPs": {
                    "GetCustomerStatusConnectionInfo": "",
                }
            }
            resp = self._hnap_post("GetMultipleHNAPs", body)
            multi = resp.get("GetMultipleHNAPsResponse", {})

            cust = multi.get("GetCustomerStatusConnectionInfoResponse", {})

            return {
                "manufacturer": "Arris",
                "model": cust.get("StatusSoftwareModelName", ""),
                "sw_version": cust.get("StatusSoftwareSfVer", ""),
            }
        except Exception:
            # Mark session as potentially dead so get_docsis_data() re-auths
            self._logged_in = False
            return {"manufacturer": "Arris", "model": "", "sw_version": ""}

    def get_connection_info(self) -> dict:
        """Standalone modem -- no connection info available."""
        return {}

    # -- HNAP transport --

    def _hnap_post(self, action: str, body: dict, auth: bool = True) -> dict:
        """Send an HNAP1 JSON POST request.

        Args:
            action: HNAP action name (e.g. "Login", "GetMultipleHNAPs")
            body: JSON body to send
            auth: Whether to include HNAP_AUTH header (False for login phase)
        """
        url = f"{self._url}/HNAP1/"

        if action == "Login":
            soap_action = _HNAP_LOGIN_URI
        else:
            soap_action = _HNAP_MULTI_URI

        headers = {
            "Content-Type": "application/json",
            "SOAPACTION": soap_action,
        }

        if auth:
            ts = str(int(time.time() * 1000) % 2_000_000_000_000)
            auth_payload = ts + soap_action
            auth_hash = hmac.new(
                self._private_key.encode(),
                auth_payload.encode(),
                hashlib.sha256,
            ).hexdigest().upper()
            headers["HNAP_AUTH"] = f"{auth_hash} {ts}"

        r = self._session.post(url, json=body, headers=headers, timeout=30)
        if not r.ok:
            log.debug("HNAP %s returned HTTP %d (%d bytes): %s",
                       action, r.status_code, len(r.content), r.text[:500])
            self._logged_in = False
        r.raise_for_status()
        return r.json()

    # -- Channel parsers --

    def _parse_downstream(self, raw: str) -> tuple[list, list]:
        """Parse downstream channel string into (docsis30, docsis31) lists."""
        if not raw:
            return [], []

        ds30 = []
        ds31 = []

        for entry in raw.split("|+|"):
            entry = entry.strip()
            if not entry:
                continue

            fields = entry.split("^")
            # Remove trailing empty from trailing "^"
            if fields and fields[-1] == "":
                fields = fields[:-1]

            if len(fields) < _DS_FIELDS:
                continue

            lock = fields[1].strip()
            if lock != "Locked":
                continue

            try:
                modulation = fields[2].strip()
                channel_id = int(fields[3])
                freq_hz = int(fields[4])
                power = float(fields[5].strip())
                snr = float(fields[6].strip())
                corr = int(fields[7])
                uncorr = int(fields[8])

                if "OFDM" in modulation.upper():
                    ds31.append({
                        "channelID": channel_id,
                        "type": "OFDM",
                        "frequency": self._hz_to_mhz(freq_hz),
                        "powerLevel": power,
                        "mer": snr,
                        "mse": None,
                        "corrErrors": corr,
                        "nonCorrErrors": uncorr,
                    })
                else:
                    ds30.append({
                        "channelID": channel_id,
                        "frequency": self._hz_to_mhz(freq_hz),
                        "powerLevel": power,
                        "mer": snr,
                        "mse": -snr,
                        "modulation": self._normalize_modulation(modulation),
                        "corrErrors": corr,
                        "nonCorrErrors": uncorr,
                    })
            except (ValueError, IndexError) as e:
                log.warning("Failed to parse SURFboard DS channel: %s", e)

        return ds30, ds31

    def _parse_upstream(self, raw: str) -> tuple[list, list]:
        """Parse upstream channel string into (docsis30, docsis31) lists."""
        if not raw:
            return [], []

        us30 = []
        us31 = []

        for entry in raw.split("|+|"):
            entry = entry.strip()
            if not entry:
                continue

            fields = entry.split("^")
            if fields and fields[-1] == "":
                fields = fields[:-1]

            if len(fields) < _US_FIELDS:
                continue

            lock = fields[1].strip()
            if lock != "Locked":
                continue

            try:
                ch_type = fields[2].strip()
                channel_id = int(fields[3])
                freq_hz = int(fields[5])
                power = float(fields[6].strip())

                if "OFDMA" in ch_type.upper():
                    us31.append({
                        "channelID": channel_id,
                        "type": "OFDMA",
                        "frequency": self._hz_to_mhz(freq_hz),
                        "powerLevel": power,
                        "modulation": "OFDMA",
                        "multiplex": "",
                    })
                else:
                    us30.append({
                        "channelID": channel_id,
                        "frequency": self._hz_to_mhz(freq_hz),
                        "powerLevel": power,
                        "modulation": ch_type,
                        "multiplex": ch_type,
                    })
            except (ValueError, IndexError) as e:
                log.warning("Failed to parse SURFboard US channel: %s", e)

        return us30, us31

    # -- Value helpers --

    @staticmethod
    def _hz_to_mhz(freq_hz: int) -> str:
        """Convert integer Hz to MHz string.

        705000000 -> "705 MHz"
        29200000  -> "29.2 MHz"
        """
        mhz = freq_hz / 1_000_000
        if mhz == int(mhz):
            return f"{int(mhz)} MHz"
        return f"{mhz:.1f} MHz"

    @staticmethod
    def _normalize_modulation(mod: str) -> str:
        """Normalize modulation string.

        "256QAM" -> "256QAM"
        "OFDM PLC" -> "OFDM PLC"
        """
        return mod.strip() if mod else ""
