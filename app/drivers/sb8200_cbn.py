"""ARRIS SURFboard SB8200 (CBN firmware) driver for DOCSight.

The SB8200 units built by Compal Broadband Networks serve a CBN web UI instead
of the HNAP1 interface used by the other SURFboard models, so `/HNAP1/` returns
404 and the `surfboard` driver cannot drive them. Status tables are fetched
from `/xml/getter.xml` with numeric function codes and normalized by the
`sb8200_cbn_xml` profile.

Login mirrors the firmware's `CBN_Encrypt()` helper: username and password are
each AES-256-CBC encrypted with a key and IV derived from the `sessionToken`
cookie, then wrapped in a `HS:<HwModel>:<hex>` envelope. That cookie rotates on
every response, so the credentials must be keyed with the token the login
request itself carries.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import re
import weakref
import xml.etree.ElementTree as ET
from enum import Enum

import requests
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from .base import ModemDriver
from .formats.xml_payloads import parse_sb8200_cbn_xml
from ..types import ConnectionInfo, DeviceInfo, DocsisData

log = logging.getLogger("docsis.driver.sb8200_cbn")

# The status tables top out around 9 KB. Bound the response so a broken or
# hostile endpoint cannot stream an unbounded document into memory.
MAX_RESPONSE_BYTES = 1_048_576

_UPTIME_RE = re.compile(r"(\d+)\s*day\(s\)\s*(\d+)h:(\d+)m:(\d+)s")
_SID_RE = re.compile(r"[A-Za-z0-9]{1,64}")
_UNREADABLE = (requests.RequestException, RuntimeError, ValueError, ET.ParseError)
_FALLBACK_DEVICE: DeviceInfo = {
    "manufacturer": "ARRIS", "model": "SB8200", "sw_version": "",
}


class Query(Enum):
    """Getter function codes usable with `_get_data()`."""

    GLOBAL_SETTINGS = 1
    SYSTEM_INFO = 2
    UPSTREAM_OFDMA_TABLE = 6
    DOWNSTREAM_OFDM_TABLE = 9
    DOWNSTREAM_TABLE = 10
    UPSTREAM_TABLE = 11
    SIGNAL_TABLE = 19


class Action(Enum):
    """Setter function codes usable with `_set_data()`."""

    LOGIN = 15
    LOGOUT = 16


def _node_text(node: ET.Element | None, default: str = "") -> str:
    """Extract one element's text, falling back to `default` when absent."""
    if node is not None and node.text is not None:
        return node.text.strip()
    return default


class SB8200CBNDriver(ModemDriver):
    """Driver for ARRIS SURFboard SB8200 modems running CBN firmware.

    The firmware allows one Web-UI session at a time, rotates its CSRF token on
    every response, and rate-limits repeated logins, so the session is held
    across polls and released on shutdown.
    """

    FORMAT_FAMILIES = ("sb8200_cbn_xml",)

    def __init__(self, url: str, user: str, password: str):
        if url.startswith("http://"):
            url = "https://" + url[len("http://"):]
            log.info("SB8200 requires HTTPS, upgraded URL to %s", url)
        super().__init__(url, user, password)
        session = requests.Session()
        # The modem presents a self-signed per-device ARRIS certificate.
        session.verify = False
        session.headers["Referer"] = url.rstrip("/") + "/"
        session.headers["X-Requested-With"] = "XMLHttpRequest"
        # The session is bound to the client address and User-Agent, so this
        # must stay stable for the lifetime of the login.
        session.headers["User-Agent"] = "docsight/2"
        # The size bound counts the bytes that arrive on the socket, so the
        # transport must not hand back a stream that inflates while it is read.
        session.headers["Accept-Encoding"] = "identity"
        self._session: requests.Session = session
        self._logged_in = False
        self._reauthenticated = False
        self._hw_model: str | None = None
        # Release the single Web-UI session so the operator is not locked out
        # of their own modem when DOCSight exits or swaps drivers.
        self._finalizer = weakref.finalize(self, SB8200CBNDriver._cleanup, url, session)
        self._finalizer.atexit = True

    @staticmethod
    def _clear_sid(session: requests.Session) -> None:
        """Drop every `SID` cookie the jar holds.

        `clear(name=...)` requires a domain and a path, and a duplicated SID
        makes `__delitem__` raise, so each match is dropped explicitly.
        """
        for cookie in list(session.cookies):
            if cookie.name == "SID":
                session.cookies.clear(cookie.domain, cookie.path, cookie.name)

    @staticmethod
    def _held_sid(session: requests.Session) -> str:
        """Read the session cookie without tripping over a duplicate."""
        for cookie in session.cookies:
            if cookie.name == "SID" and cookie.value:
                return cookie.value
        return ""

    @staticmethod
    def _cleanup(url: str, session: requests.Session) -> None:
        """Close the Web-UI session so another client can connect."""
        try:
            if SB8200CBNDriver._held_sid(session):
                session.post(
                    f"{url}/xml/setter.xml",
                    data={
                        "token": session.cookies.get("sessionToken", ""),
                        "fun": str(Action.LOGOUT.value),
                    },
                    timeout=10,
                    stream=True,
                ).close()
            SB8200CBNDriver._clear_sid(session)
        except Exception:  # noqa: BLE001 - must never raise from a finalizer
            pass
        finally:
            session.close()

    def login(self) -> None:
        """Authenticate with the modem, reusing an already-open session."""
        if self._logged_in:
            return

        # Release a session this driver still holds before discarding the
        # cookies that identify it, so a failed login cannot strand an open
        # session on a modem that permits only one.
        self._release_session()

        # Only the rotating session cookie is needed, so the login page body
        # is never downloaded.
        response = self._session.get(
            f"{self._url}/common_page/login.html", timeout=10, stream=True
        )
        response.close()
        response.raise_for_status()

        # Resolve the hardware model first: that request rotates the session
        # token, and the credentials must be keyed with the token the login
        # request will carry.
        hw_model = self._hardware_model()
        token = self._session_token()
        if not token:
            raise RuntimeError("Modem did not issue a session token")

        body = self._set_data(Action.LOGIN, {
            "Username": self._encrypt(self._user or "admin", token, hw_model),
            "Password": self._encrypt(self._password, token, hw_model),
        })
        sid = body.split("SID=", 1)[1].strip() if "SID=" in body else ""
        if not body.lstrip().startswith("successful") or not _SID_RE.fullmatch(sid):
            # The response body can echo account state, so it is not logged.
            raise RuntimeError("Modem authentication failed: check username and password")

        # The modem may also answer the login with its own `Set-Cookie: SID`.
        # `cookies.set()` only replaces a cookie carrying the same domain and
        # path, so both would survive, be sent together, and make every later
        # read of the cookie raise `CookieConflictError`.
        self._clear_sid(self._session)
        self._session.cookies.set("SID", sid)
        self._logged_in = True
        log.info("Auth OK (%s)", hw_model)

    def get_docsis_data(self) -> DocsisData:
        """Query the SC-QAM, OFDM, OFDMA, and codeword tables.

        Only the two SC-QAM tables are required. The OFDM, OFDMA, and codeword
        tables enrich the result, so an endpoint this firmware does not serve
        degrades to `None` instead of discarding the channels that were read.
        """
        self._begin_call()
        downstream_xml = self._get_data(Query.DOWNSTREAM_TABLE)
        upstream_xml = self._get_data(Query.UPSTREAM_TABLE)
        parsed = parse_sb8200_cbn_xml(
            downstream_xml=downstream_xml,
            upstream_xml=upstream_xml,
            downstream_ofdm_xml=self._get_optional_data(Query.DOWNSTREAM_OFDM_TABLE),
            upstream_ofdma_xml=self._get_optional_data(Query.UPSTREAM_OFDMA_TABLE),
            signal_xml=self._get_optional_data(Query.SIGNAL_TABLE),
        )
        if parsed.value is None:
            raise ValueError("invalid SB8200 channel XML")
        return parsed.value

    def get_device_info(self) -> DeviceInfo:
        """Read model, firmware, and uptime metadata.

        The serial number reported by this table is deliberately not exposed.
        """
        self._begin_call()
        try:
            root = self._xml(self._get_data(Query.SYSTEM_INFO))
        except _UNREADABLE as e:
            log.warning("Failed to get device info: %s", e)
            return dict(_FALLBACK_DEVICE)
        if root is None:
            log.warning("Modem returned unreadable system info")
            return dict(_FALLBACK_DEVICE)

        info: DeviceInfo = {
            "manufacturer": "ARRIS",
            "model": _node_text(root.find("HwModel"), "SB8200"),
            "hw_version": _node_text(root.find("cm_hardware_version")),
            "sw_version": _node_text(root.find("SwVersion")),
            "docsis_status": _node_text(root.find("cm_status")),
        }
        uptime = self._uptime_seconds(_node_text(root.find("cm_system_uptime")))
        if uptime is not None:
            info["uptime_seconds"] = uptime
        return info

    def get_connection_info(self) -> ConnectionInfo:
        """Report the DOCSIS mode.

        This firmware exposes no service-flow table, so provisioned rates are
        left unset rather than guessed.
        """
        self._begin_call()
        try:
            root = self._xml(self._get_data(Query.SYSTEM_INFO))
        except _UNREADABLE as e:
            log.warning("Failed to get connection info: %s", e)
            return {}
        mode = _node_text(root.find("cm_docsis_mode")) if root is not None else ""
        return {"connection_type": mode} if mode else {}

    @staticmethod
    def _encrypt(value: str, token: str, hw_model: str) -> str:
        """Reproduce the firmware's `CBN_Encrypt()` field envelope."""
        key = hashlib.sha256(token.encode()).digest()
        iv = hashlib.md5(token.encode(), usedforsecurity=False).digest()
        padder = padding.PKCS7(128).padder()
        padded = padder.update(value.encode()) + padder.finalize()
        encryptor = Cipher(algorithms.AES(key), modes.CBC(iv)).encryptor()
        ciphertext = encryptor.update(padded) + encryptor.finalize()
        return base64.b64encode(f"HS:{hw_model}:{ciphertext.hex()}".encode()).decode()

    @staticmethod
    def _uptime_seconds(uptime: str) -> int | None:
        """Convert the `14day(s)20h:50m:40s` uptime string to seconds."""
        match = _UPTIME_RE.search(uptime)
        if not match:
            return None
        days, hours, minutes, seconds = (int(part) for part in match.groups())
        return days * 86400 + hours * 3600 + minutes * 60 + seconds

    @staticmethod
    def _xml(payload: str) -> ET.Element | None:
        try:
            return ET.fromstring(payload)
        except ET.ParseError:
            return None

    def _session_token(self) -> str:
        """Read the CSRF token the modem rotates on every response."""
        return self._session.cookies.get("sessionToken", "")

    def _begin_call(self) -> None:
        """Open one driver call with a fresh single-re-authentication budget."""
        self._reauthenticated = False

    def _release_session(self) -> None:
        """Close a session this driver still holds, then drop its cookies."""
        if self._held_sid(self._session):
            try:
                self._request(Action.LOGOUT)
            except _UNREADABLE as e:
                log.debug("Logout before re-authentication failed: %s", e)
        self._session.cookies.clear()
        self._logged_in = False

    def _hardware_model(self) -> str:
        """Read the hardware model that keys the login envelope."""
        if self._hw_model:
            return self._hw_model
        root = self._xml(self._request(Query.GLOBAL_SETTINGS)[0])
        model = _node_text(root.find("HwModel")) if root is not None else ""
        if not model:
            raise RuntimeError("Modem did not report a hardware model")
        self._hw_model = model
        return model

    def _request(
        self, function: Query | Action, data: dict[str, str] | None = None
    ) -> tuple[str, int]:
        """Post one function call, returning its body and HTTP status."""
        endpoint = "getter.xml" if isinstance(function, Query) else "setter.xml"
        payload = {"token": self._session_token(), "fun": str(function.value)}
        if data:
            payload |= data
        response = self._session.post(
            f"{self._url}/xml/{endpoint}",
            data=payload,
            timeout=10,
            allow_redirects=False,
            stream=True,
        )
        try:
            response.raise_for_status()
            # Reading with `decode_content=True` bounds the compressed bytes
            # taken from the socket, not the bytes they expand to, so a
            # kilobyte of gzip could still inflate past the limit before it is
            # measured. The request asks for `identity`; anything else is
            # refused before a single byte is buffered.
            encoding = response.headers.get("Content-Encoding", "").strip().lower()
            if encoding not in ("", "identity"):
                raise RuntimeError(
                    f"Modem response for fun={function.value} is {encoding}-encoded"
                )
            body = response.raw.read(MAX_RESPONSE_BYTES + 1, decode_content=False)
        finally:
            response.close()
        if len(body) > MAX_RESPONSE_BYTES:
            raise RuntimeError(f"Modem response for fun={function.value} exceeds the size limit")
        return body.decode("utf-8", errors="replace"), response.status_code

    @staticmethod
    def _session_lost(body: str, status: int) -> bool:
        """Report whether an answer means the session is no longer valid.

        Measured against the device: once the session lapses, every table code
        answers `302` with an empty body while `fun=1` still returns 200. Any
        request carrying a stale CSRF token drops the session, so this is a
        routine condition rather than an error.
        """
        return status == 302 or not body.strip()

    def _reauthenticate(self) -> bool:
        """Re-establish a lapsed session, at most once per call.

        Only a session this driver believed it held is re-established, which
        keeps a failing login off the modem's rate limiter when a table is
        unreadable for any other reason. The budget is spent once per call, so
        a poll reading five tables still costs the limiter a single login.
        """
        if self._reauthenticated or not self._logged_in:
            return False
        self._reauthenticated = True
        log.info("Session lost, re-authenticating")
        self._logged_in = False
        self.login()
        return True

    def _get_data(self, query: Query) -> str:
        """Query a required table, re-authenticating at most once per call."""
        body, status = self._request(query)
        if not self._session_lost(body, status):
            return body
        if not self._reauthenticate():
            raise RuntimeError(f"Modem returned no data for fun={query.value}")

        body, status = self._request(query)
        if self._session_lost(body, status):
            raise RuntimeError(
                f"Modem returned no data for fun={query.value} after re-authentication"
            )
        return body

    def _get_optional_data(self, query: Query) -> str | None:
        """Query an enrichment table, degrading to `None` when it is absent.

        A `302` is session loss and is worth the call's single
        re-authentication. A `200` carrying an empty body is how this firmware
        answers for a table it does not serve, so it must not spend a login on
        the modem's rate limiter. A transport or HTTP failure here must not
        discard the SC-QAM channels the required tables already returned.
        """
        try:
            body, status = self._request(query)
            if status == 302 and self._reauthenticate():
                body, status = self._request(query)
        except _UNREADABLE as e:
            # The response body can echo session state, so only the failure
            # class is logged.
            log.warning(
                "Optional table fun=%s is unavailable (%s)", query.value, type(e).__name__
            )
            return None
        if status == 302 or not body.strip():
            log.debug("Optional table fun=%s reported no data", query.value)
            return None
        return body

    def _set_data(self, action: Action, data: dict[str, str]) -> str:
        """Execute one action on the modem."""
        if "fun" in data or "token" in data:
            raise ValueError("invalid data key in SB8200 command")
        return self._request(action, data)[0]
