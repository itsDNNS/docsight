"""Arris SURFboard HNAP driver for DOCSight.

Supports Arris/CommScope DOCSIS 3.1 SURFboard modems (S33, S34, SB8200)
that expose an HNAP1 JSON API at /HNAP1/.

Authentication is a two-phase HMAC handshake:
1. POST Action "request" -- server returns Challenge, Cookie, PublicKey
2. Derive PrivateKey = HMAC(PublicKey+password, Challenge)
3. Derive LoginPassword = HMAC(PrivateKey, Challenge)
4. POST Action "login" with LoginPassword
5. All subsequent requests use HNAP_AUTH header with timestamp-based HMAC

The S34 uses HMAC-SHA256 while the SB8200 uses HMAC-MD5. The driver
auto-detects the algorithm based on the modem's challenge response.

Every HNAP request requires an HNAP_AUTH header, including the initial
login request. Before authentication, the key ``withoutloginkey`` is used.

Channel data arrives as pipe-delimited strings ("|+|" between channels,
"^" between fields within a channel).
"""

import hashlib
import hmac
import logging
import ssl
import time
from urllib.parse import urlparse, urlunparse

import requests
from requests.adapters import HTTPAdapter

from .base import ModemDriver

log = logging.getLogger("docsis.driver.surfboard")

_HNAP_LOGIN_URI = '"http://purenetworks.com/HNAP1/Login"'
_HNAP_MULTI_URI = '"http://purenetworks.com/HNAP1/GetMultipleHNAPs"'
_HNAP_PRELOGIN_KEY = "withoutloginkey"

# Fields per downstream channel (split by "^"):
# num ^ lock ^ modulation ^ channelID ^ frequency ^ power ^ snr ^ corrErrors ^ uncorrErrors ^
_DS_FIELDS = 9

# Fields per upstream channel (split by "^"):
# num ^ lock ^ type ^ channelID ^ width ^ frequency ^ power ^
_US_FIELDS = 7

_HAS_LEGACY_TLS = hasattr(ssl, "OP_LEGACY_SERVER_CONNECT")


class _LegacyTLSAdapter(HTTPAdapter):
    """HTTPS adapter for SURFboard modems with old TLS stacks.

    Some SB8200 firmware only supports TLS 1.0/1.1 with legacy ciphers
    that OpenSSL 3.x rejects at default security level 2.  This adapter
    lowers the requirements just enough to allow the handshake.

    Only mounted on the driver's session after a normal TLS handshake fails.
    """

    def init_poolmanager(self, *args, **kwargs):
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        ctx.options |= ssl.OP_LEGACY_SERVER_CONNECT
        ctx.minimum_version = ssl.TLSVersion.MINIMUM_SUPPORTED
        ctx.set_ciphers("DEFAULT:@SECLEVEL=1")
        kwargs["ssl_context"] = ctx
        super().init_poolmanager(*args, **kwargs)


class SurfboardDriver(ModemDriver):
    """Driver for Arris SURFboard DOCSIS 3.1 modems (S33/S34/SB8200).

    Uses HNAP1 JSON API with HMAC authentication (SHA256 for S34,
    MD5 for SB8200 -- auto-detected on first login).

    Every HNAP request must include an ``HNAP_AUTH`` header, even the
    initial login.  Before authentication the pre-shared key
    ``withoutloginkey`` is used.

    Session management: The modem tracks active sessions by IP address and
    only allows one concurrent login. Re-logging in while a session is active
    causes the modem to return ``LoginResult: RELOAD`` instead of a challenge.
    To avoid this, the driver reuses the existing session across polls and only
    re-authenticates when a request fails or when no session exists yet.
    """

    def __init__(self, url: str, user: str, password: str):
        url = self._normalize_url(url)
        self._http_fallback_url = ""
        self._transport_fallback_used = False
        self._legacy_tls_attempted = False
        self._legacy_tls_needed = False
        if url.startswith("http://"):
            self._http_fallback_url = url
            url = "https://" + url[len("http://"):]
            log.info("SURFboard trying HTTPS first, upgraded URL to %s", url)
        elif url.startswith("https://"):
            self._http_fallback_url = "http://" + url[len("https://"):]
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._session.verify = False
        self._private_key = ""
        self._cookie = ""
        self._logged_in = False
        # HMAC algorithm -- auto-detected during login.
        # S34 uses SHA256, SB8200 uses MD5.
        self._hmac_algo: str = ""
        # Action namespace: "" = unknown, "Customer" (S34) or "Moto" (SB8200).
        # Persists across session resets (firmware property, not session state).
        self._action_ns: str = ""

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize modem base URL by removing paths, queries, and trailing slashes."""
        parsed = urlparse(url)
        if parsed.scheme and parsed.netloc:
            if parsed.path or parsed.params or parsed.query or parsed.fragment:
                url = urlunparse(
                    parsed._replace(path="", params="", query="", fragment="")
                )
                log.info("SURFboard stripped path from URL: %s", url)
            return url
        return url.rstrip("/")

    def _fresh_session(self) -> None:
        """Reset HTTP session to clear stale cookies/state."""
        self._session.close()
        self._session = requests.Session()
        self._session.verify = False
        if self._legacy_tls_active():
            self._mount_legacy_tls()
        self._private_key = ""
        self._cookie = ""
        self._logged_in = False
        self._hmac_algo = ""

    def _fallback_to_http(self) -> bool:
        """Switch to HTTP once when HTTPS transport fails before login."""
        if (
            self._transport_fallback_used
            or not self._http_fallback_url
            or self._url == self._http_fallback_url
        ):
            return False
        old_url = self._url
        self._url = self._http_fallback_url
        self._transport_fallback_used = True
        self._fresh_session()
        log.warning(
            "SURFboard HTTPS transport failed, retrying over HTTP (%s -> %s)",
            old_url,
            self._url,
        )
        return True

    def _mount_legacy_tls(self) -> None:
        """Mount the legacy TLS adapter on the current session."""
        self._session.mount("https://", _LegacyTLSAdapter())
        self._session.headers["Connection"] = "close"

    def _legacy_tls_active(self) -> bool:
        """Return True once legacy TLS has been tried or successfully used."""
        return self._legacy_tls_attempted or self._legacy_tls_needed

    def _fallback_to_legacy_tls(self) -> bool:
        """Retry HTTPS with legacy TLS context once after a handshake failure."""
        if self._legacy_tls_attempted or not _HAS_LEGACY_TLS:
            return False
        self._legacy_tls_attempted = True
        self._mount_legacy_tls()
        log.warning(
            "SURFboard TLS handshake failed, retrying with legacy TLS context"
        )
        return True

    def login(self) -> None:
        """Two-phase HNAP login with HMAC.

        Reuses the existing session if already authenticated. Only performs
        a fresh login when no session exists or after a failed request
        invalidated the session.

        RELOAD handling (modem considers previous session still active):
        1. First RELOAD: wait 5s, retry on same session
        2. Second RELOAD: fresh session + 15s wait, retry
        3. Third RELOAD: fail

        TLS fallback: If the initial TLS handshake fails (old firmware),
        retries with a legacy TLS context before falling back to HTTP.
        """
        if self._logged_in:
            return

        reload_count = 0
        conn_errors = 0
        tls_error = ""
        while True:
            try:
                self._do_login()
                if self._legacy_tls_attempted:
                    self._legacy_tls_needed = True
                log.info("SURFboard HNAP login OK")
                self._logged_in = True
                return
            except requests.exceptions.SSLError as e:
                if not tls_error:
                    tls_error = str(e)
                if self._fallback_to_legacy_tls():
                    time.sleep(1)
                    continue
                if self._fallback_to_http():
                    time.sleep(1)
                    continue
                conn_errors += 1
                self._fresh_session()
                if conn_errors >= 3:
                    raise RuntimeError(
                        f"SURFboard login failed: TLS error ({tls_error}), "
                        "connection refused on HTTP fallback"
                    )
                log.warning(
                    "SURFboard TLS error, retrying with fresh session"
                )
                time.sleep(1)
            except requests.ConnectionError as e:
                # If legacy TLS was in use (Phase 1 may have succeeded),
                # preserve the adapter so _fresh_session() remounts it.
                if self._legacy_tls_attempted:
                    self._legacy_tls_needed = True
                if not self._legacy_tls_needed and self._fallback_to_http():
                    time.sleep(1)
                    continue
                conn_errors += 1
                self._fresh_session()
                if conn_errors >= 3:
                    if self._legacy_tls_needed and self._fallback_to_http():
                        conn_errors = 0
                        time.sleep(1)
                        continue
                    msg = f"SURFboard login failed: {e}"
                    if tls_error:
                        msg = (
                            f"SURFboard login failed: TLS error ({tls_error}), "
                            f"{e}"
                        )
                    raise RuntimeError(msg)
                log.warning(
                    "SURFboard connection lost, retrying with fresh session: %s",
                    e,
                )
                time.sleep(1)
            except RuntimeError as e:
                if "no challenge received" not in str(e):
                    raise
                reload_count += 1
                if reload_count == 1:
                    log.warning(
                        "SURFboard RELOAD (stale session on modem), "
                        "waiting 5s, retrying on same session (reload %d/3)",
                        reload_count,
                    )
                    time.sleep(5)
                elif reload_count == 2:
                    log.warning(
                        "SURFboard RELOAD persists, fresh session + "
                        "15s wait (reload %d/3)",
                        reload_count,
                    )
                    self._fresh_session()
                    time.sleep(15)
                else:
                    raise
            except requests.RequestException as e:
                raise RuntimeError(f"SURFboard login failed: {e}")

    def _do_login(self) -> None:
        """Execute the two-phase HNAP login handshake.

        The HNAP_AUTH header is required on *every* request, including
        the initial login.  Before we have a PrivateKey the modem
        expects the pre-shared key ``withoutloginkey``.

        Phase 1 (challenge request) is algorithm-agnostic -- the modem
        returns the same challenge regardless.  Phase 2 (password
        derivation) depends on the firmware's HMAC algorithm: S34 uses
        SHA-256, SB8200 uses MD5.  We request the challenge once, then
        try SHA-256 first; if the modem rejects the derived password we
        re-derive with MD5 using the same challenge -- no extra round
        trip that could trigger a RELOAD.
        """
        # Phase 1: request challenge (algorithm-agnostic, only hit modem once)
        self._private_key = _HNAP_PRELOGIN_KEY
        body = {
            "Login": {
                "Action": "request",
                "Username": self._user,
                "LoginPassword": "",
                "Captcha": "",
                "PrivateLogin": "LoginPassword",
            }
        }
        resp = self._hnap_post("Login", body)
        login_resp = resp.get("LoginResponse", {})

        challenge = login_resp.get("Challenge", "")
        cookie = login_resp.get("Cookie", "")
        public_key = login_resp.get("PublicKey", "")

        if not challenge or not public_key:
            log.debug("HNAP login response: %s", login_resp)
            raise RuntimeError("SURFboard login failed: no challenge received")

        self._cookie = cookie
        self._session.cookies.set("uid", cookie)

        # Phase 2: derive keys and authenticate.
        # Try known algorithm first, otherwise SHA-256 then MD5.
        if self._hmac_algo == "md5":
            algos = [hashlib.md5]
        elif self._hmac_algo == "sha256":
            algos = [hashlib.sha256]
        else:
            algos = [hashlib.sha256, hashlib.md5]

        last_error: str | None = None
        for algo in algos:
            algo_name = "sha256" if algo is hashlib.sha256 else "md5"
            try:
                self._try_phase2(algo, challenge, public_key, cookie)
                self._hmac_algo = algo_name
                log.debug("SURFboard HMAC algorithm: %s", algo_name)
                return
            except RuntimeError as e:
                last_error = str(e)
                if len(algos) > 1:
                    log.debug(
                        "SURFboard phase 2 with %s failed (%s), trying next algorithm",
                        algo_name, last_error,
                    )
                    continue
                raise

        raise RuntimeError(last_error or "SURFboard login failed")

    def _try_phase2(self, algo, challenge: str, public_key: str,
                    cookie: str) -> None:
        """Derive keys and send Phase 2 login using the given algorithm."""
        retried = False
        while True:
            self._private_key = hmac.new(
                (public_key + self._password).encode(),
                challenge.encode(),
                algo,
            ).hexdigest().upper()

            login_password = hmac.new(
                self._private_key.encode(),
                challenge.encode(),
                algo,
            ).hexdigest().upper()

            self._session.cookies.set("PrivateKey", self._private_key)

            body = {
                "Login": {
                    "Action": "login",
                    "Username": self._user,
                    "LoginPassword": login_password,
                    "Captcha": "",
                    "PrivateLogin": "LoginPassword",
                }
            }
            try:
                resp = self._hnap_post("Login", body, auth_algo=algo)
            except requests.ConnectionError as e:
                if retried or not self._legacy_tls_active():
                    msg = f"SURFboard phase 2 failed: {e}"
                    if self._legacy_tls_active():
                        msg = f"SURFboard phase 2 failed under legacy TLS: {e}"
                    raise requests.ConnectionError(msg) from e
                retried = True
                log.warning(
                    "SURFboard phase 2 connection reset under legacy TLS, "
                    "retrying with fresh session",
                )
                self._fresh_session()
                self._cookie = cookie
                self._session.cookies.set("uid", cookie)
                continue

            login_resp = resp.get("LoginResponse", {})
            result = login_resp.get("LoginResult", "")

            if result != "OK":
                raise RuntimeError(f"SURFboard login failed: {result}")
            return

    def get_docsis_data(self) -> dict:
        """Retrieve DOCSIS channel data via HNAP GetMultipleHNAPs.

        On HTTP 500: tries the other action namespace before re-authenticating.
        On other HTTP errors: re-authenticates (session expired).
        """
        try:
            return self._fetch_docsis_data()
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0

            if status == 500:
                current = self._action_ns or "Customer"
                other = "Moto" if current == "Customer" else "Customer"
                log.warning(
                    "HTTP 500, trying %s namespace (was %s)", other, current,
                )
                prev_ns = self._action_ns
                self._action_ns = other
                try:
                    return self._fetch_docsis_data()
                except requests.HTTPError:
                    self._action_ns = prev_ns

            log.warning(
                "DOCSIS data fetch failed (HTTP %d), re-authenticating",
                status,
            )
            self._logged_in = False
            self.login()
            return self._fetch_docsis_data()

    def _fetch_docsis_data(self) -> dict:
        """Internal: fetch and parse DOCSIS channel data.

        Auto-detects action namespace (Customer vs Moto) on first call
        by trying Customer first, then Moto if no data is returned.
        """
        body = {
            "GetMultipleHNAPs": self._make_actions(
                "DownstreamChannelInfo", "UpstreamChannelInfo"
            )
        }
        resp = self._hnap_post("GetMultipleHNAPs", body)
        multi = resp.get("GetMultipleHNAPsResponse", {})

        ds_raw = (
            multi.get(self._response_key("DownstreamChannelInfo"), {})
            .get(self._conn_field("DownstreamChannel"), "")
        )
        us_raw = (
            multi.get(self._response_key("UpstreamChannelInfo"), {})
            .get(self._conn_field("UpstreamChannel"), "")
        )

        # Auto-detect namespace: if no data and namespace unknown, try Moto
        if not ds_raw and not us_raw and not self._action_ns:
            self._action_ns = "Moto"
            log.info("No channel data with Customer namespace, trying Moto")
            body = {
                "GetMultipleHNAPs": self._make_actions(
                    "DownstreamChannelInfo", "UpstreamChannelInfo"
                )
            }
            resp = self._hnap_post("GetMultipleHNAPs", body)
            multi = resp.get("GetMultipleHNAPsResponse", {})
            ds_raw = (
                multi.get(self._response_key("DownstreamChannelInfo"), {})
                .get(self._conn_field("DownstreamChannel"), "")
            )
            us_raw = (
                multi.get(self._response_key("UpstreamChannelInfo"), {})
                .get(self._conn_field("UpstreamChannel"), "")
            )
            if not ds_raw and not us_raw:
                self._action_ns = ""
                log.warning(
                    "Neither Customer nor Moto namespace returned channel data"
                )
        elif (ds_raw or us_raw) and not self._action_ns:
            self._action_ns = "Customer"

        ds30, ds31 = self._parse_downstream(ds_raw)
        us30, us31 = self._parse_upstream(us_raw)

        return {
            "channelDs": {"docsis30": ds30, "docsis31": ds31},
            "channelUs": {"docsis30": us30, "docsis31": us31},
        }

    def get_device_info(self) -> dict:
        """Retrieve device model and firmware from HNAP."""
        try:
            model, sw = self._fetch_device_fields()

            # Fallback to other namespace if no model and namespace unknown
            if not model and not self._action_ns:
                self._action_ns = "Moto"
                model, sw = self._fetch_device_fields()
                if not model:
                    self._action_ns = ""

            return {
                "manufacturer": "Arris",
                "model": model,
                "sw_version": sw,
            }
        except Exception:
            log.warning("Failed to retrieve device info, will retry next poll")
            return {"manufacturer": "Arris", "model": "", "sw_version": ""}

    def _fetch_device_fields(self) -> tuple[str, str]:
        """Fetch model and firmware from HNAP, with HTTP 500 namespace fallback.

        Returns (model, sw_version) strings. On HTTP 500 with unknown
        namespace, tries the other namespace before propagating.
        """
        try:
            body = {
                "GetMultipleHNAPs": self._make_actions(
                    "StartupSequence", "ConnectionInfo"
                )
            }
            resp = self._hnap_post("GetMultipleHNAPs", body)
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else 0
            if status == 500 and not self._action_ns:
                current = self._action_ns or "Customer"
                other = "Moto" if current == "Customer" else "Customer"
                log.warning(
                    "Device info HTTP 500, trying %s namespace", other,
                )
                self._action_ns = other
                body = {
                    "GetMultipleHNAPs": self._make_actions(
                        "StartupSequence", "ConnectionInfo"
                    )
                }
                resp = self._hnap_post("GetMultipleHNAPs", body)
            else:
                raise

        multi = resp.get("GetMultipleHNAPsResponse", {})
        conn = multi.get(self._response_key("ConnectionInfo"), {})
        return (
            conn.get("StatusSoftwareModelName", ""),
            conn.get("StatusSoftwareSfVer", ""),
        )

    def get_connection_info(self) -> dict:
        """Standalone modem -- no connection info available."""
        return {}

    # -- Namespace helpers --

    def _make_actions(self, *suffixes: str) -> dict:
        """Build HNAP action dict using current namespace.

        Returns e.g. {"GetCustomerStatusDownstreamChannelInfo": "", ...}
        """
        ns = self._action_ns or "Customer"
        return {f"Get{ns}Status{s}": "" for s in suffixes}

    def _response_key(self, suffix: str) -> str:
        """Build response key for the given action suffix.

        Returns e.g. "GetCustomerStatusDownstreamChannelInfoResponse"
        """
        ns = self._action_ns or "Customer"
        return f"Get{ns}Status{suffix}Response"

    def _conn_field(self, field: str) -> str:
        """Build connection data field name.

        Returns e.g. "CustomerConnDownstreamChannel"
        """
        ns = self._action_ns or "Customer"
        return f"{ns}Conn{field}"

    # -- HNAP transport --

    def _hnap_post(self, action: str, body: dict, *,
                   auth_algo=None) -> dict:
        """Send an HNAP1 JSON POST request.

        HNAP_AUTH is sent on **every** request.  Before login the
        pre-shared key ``withoutloginkey`` is used as PrivateKey.

        Args:
            action: HNAP action name (e.g. "Login", "GetMultipleHNAPs")
            body: JSON body to send
            auth_algo: Hash constructor for HNAP_AUTH HMAC.  When *None*
                the previously detected algorithm is used (sha256 default).
        """
        url = f"{self._url}/HNAP1/"

        if action == "Login":
            soap_action = _HNAP_LOGIN_URI
        else:
            soap_action = _HNAP_MULTI_URI

        # Determine HMAC algorithm
        if auth_algo is not None:
            algo = auth_algo
        elif self._hmac_algo == "md5":
            algo = hashlib.md5
        else:
            algo = hashlib.sha256

        ts = str(int(time.time() * 1000) % 2_000_000_000_000)
        auth_key = self._private_key or _HNAP_PRELOGIN_KEY
        auth_payload = ts + soap_action
        auth_hash = hmac.new(
            auth_key.encode(),
            auth_payload.encode(),
            algo,
        ).hexdigest().upper()

        headers = {
            "Content-Type": "application/json",
            "SOAPACTION": soap_action,
            "HNAP_AUTH": f"{auth_hash} {ts}",
        }
        if self._legacy_tls_active():
            headers["Connection"] = "close"

        try:
            r = self._session.post(url, json=body, headers=headers, timeout=30)
            if not r.ok:
                log.debug("HNAP %s returned HTTP %d (%d bytes): %s",
                           action, r.status_code, len(r.content), r.text[:500])
            r.raise_for_status()
            return r.json()
        except requests.exceptions.ChunkedEncodingError as e:
            # Some SB8200 units reset the socket after sending HTTP 200 headers
            # but before the response body is fully readable. Treat that as the
            # same transport-level failure path as a dropped connection.
            raise requests.ConnectionError(str(e)) from e

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
