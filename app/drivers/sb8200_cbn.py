"""ARRIS SURFboard SB8200 (CBN firmware) driver for DOCSight.

The SB8200 units built by Compal Broadband Networks serve a CBN web UI instead
of the HNAP1 interface used by the other SURFboard models, so `/HNAP1/` returns
404 and the `surfboard` driver cannot drive them. Status tables are fetched
from `/xml/getter.xml` with numeric function codes and normalized by the
`sb8200_cbn_xml` profile.

Login mirrors the firmware's `CBN_Encrypt()` helper: username and password are
each AES-256-CBC encrypted with a key and IV derived from the rotating
`sessionToken` cookie, then wrapped in a `HS:<HwModel>:<hex>` envelope.
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

# The status tables top out around 9 KB. Bound the response so a hostile or
# broken endpoint cannot feed an unbounded document to the XML parser.
MAX_RESPONSE_BYTES = 1_048_576

_UPTIME_RE = re.compile(r"(\d+)\s*day\(s\)\s*(\d+)h:(\d+)m:(\d+)s")


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

    The firmware allows one Web-UI session at a time and rotates its CSRF
    token on every response, so the session is held open across polls and
    released on shutdown.
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
        # The session is locked to one IP plus User-Agent, so this must stay
        # stable for the lifetime of the login.
        session.headers["User-Agent"] = "docsight/2"
        self._session: requests.Session = session
        self._logged_in = False
        self._hw_model: str | None = None
        # Release the single Web-UI session so the operator is not locked out
        # of their own modem when DOCSight exits.
        self._finalizer = weakref.finalize(self, SB8200CBNDriver._cleanup, url, session)
        self._finalizer.atexit = True

    @staticmethod
    def _cleanup(url: str, session: requests.Session) -> None:
        """Close the Web-UI session so another client can connect."""
        if "SID" not in session.cookies:
            return
        try:
            session.post(
                f"{url}/xml/setter.xml",
                data={
                    "token": session.cookies.get("sessionToken", ""),
                    "fun": str(Action.LOGOUT.value),
                },
                timeout=10,
            )
        except requests.RequestException:
            pass
        session.cookies.pop("SID", None)

    def login(self) -> None:
        """Authenticate with the modem, reusing an already-open session.

        The firmware rate-limits repeated login attempts, so an established
        session is kept rather than re-authenticated on every poll.
        """
        if self._logged_in:
            return

        self._session.cookies.clear()
        response = self._session.get(f"{self._url}/common_page/login.html", timeout=10)
        response.raise_for_status()
        response.close()

        token = self._session_token()
        if not token:
            raise RuntimeError("Modem did not issue a session token")

        hw_model = self._hardware_model()
        body = self._set_data(Action.LOGIN, {
            "Username": self._encrypt(self._user or "admin", token, hw_model),
            "Password": self._encrypt(self._password, token, hw_model),
        })

        if "successful" not in body or "SID=" not in body:
            # The response body can echo account state, so it is not logged.
            raise RuntimeError("Modem authentication failed: check username and password")

        self._session.cookies.set("SID", body.split("SID=", 1)[1].strip())
        self._logged_in = True
        log.info("Auth OK (%s)", hw_model)

    def get_docsis_data(self) -> DocsisData:
        """Query the SC-QAM, OFDM, OFDMA, and codeword tables."""
        parsed = parse_sb8200_cbn_xml(
            self._get_data(Query.DOWNSTREAM_TABLE),
            self._get_data(Query.UPSTREAM_TABLE),
            self._get_data(Query.DOWNSTREAM_OFDM_TABLE),
            self._get_data(Query.UPSTREAM_OFDMA_TABLE),
            self._get_data(Query.SIGNAL_TABLE),
        )
        if parsed.value is None:
            raise ValueError("invalid SB8200 channel XML")
        return parsed.value

    def get_device_info(self) -> DeviceInfo:
        """Read model, firmware, and uptime metadata.

        The serial number reported by this table is deliberately not exposed.
        """
        try:
            root = self._xml(self._get_data(Query.SYSTEM_INFO))
            if root is None:
                raise ValueError("missing system info")
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
        except Exception:
            return {"manufacturer": "ARRIS", "model": "SB8200", "sw_version": ""}

    def get_connection_info(self) -> ConnectionInfo:
        """Report the DOCSIS mode.

        This firmware exposes no service-flow table, so provisioned rates are
        left unset rather than guessed.
        """
        try:
            root = self._xml(self._get_data(Query.SYSTEM_INFO))
            mode = _node_text(root.find("cm_docsis_mode")) if root is not None else ""
            return {"connection_type": mode} if mode else {}
        except Exception as e:
            log.warning("Failed to get connection info: %s", e)
            return {}

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

    def _hardware_model(self) -> str:
        """Read the hardware model that keys the login envelope."""
        if self._hw_model:
            return self._hw_model
        root = self._xml(self._request("getter.xml", Query.GLOBAL_SETTINGS.value)[0])
        model = _node_text(root.find("HwModel")) if root is not None else ""
        if not model:
            raise RuntimeError("Modem did not report a hardware model")
        self._hw_model = model
        return model

    def _request(self, endpoint: str, function: int, data: dict[str, str] | None = None) -> tuple[str, int]:
        """Post one function call, returning its body and HTTP status."""
        payload = {"token": self._session_token(), "fun": str(function)}
        if data:
            payload |= data
        response = self._session.post(
            f"{self._url}/xml/{endpoint}",
            data=payload,
            timeout=10,
            allow_redirects=False,
        )
        response.raise_for_status()
        if len(response.content) > MAX_RESPONSE_BYTES:
            raise RuntimeError(f"Modem response for fun={function} exceeds the size limit")
        return response.text, response.status_code

    def _get_data(self, query: Query) -> str:
        """Query one table, re-authenticating once if the session expired."""
        body, status = self._request("getter.xml", query.value)
        if status == 302:
            log.info("Session expired, re-authenticating")
            self._logged_in = False
            self.login()
            body, status = self._request("getter.xml", query.value)
            if status == 302:
                raise RuntimeError(f"Modem rejected fun={query.value} after re-authentication")
        return body

    def _set_data(self, action: Action, data: dict[str, str]) -> str:
        """Execute one action on the modem."""
        if "fun" in data or "token" in data:
            raise ValueError("invalid data key in SB8200 command")
        return self._request("setter.xml", action.value, data)[0]
