"""Sagemcom F@st 3896 driver for DOCSight.

Supports Sagemcom F@st 3896 cable modems (Tele2/Com Hem C3/C4, Ziggo)
using the Sagemcom XMO JSON-RPC API at /cgi/json-req.

Authentication uses SHA-512 digest:
1. POST logIn action, receive session_id and server_nonce
2. credential_hash = SHA512(username + ":" + nonce + ":" + SHA512(password))
3. Per-request auth_key = SHA512(credential_hash + ":" + req_id + ":" + cnonce + ":JSON:/cgi/json-req")

Channel data is retrieved via getValue actions with XPaths into the device
data model (Device/Docsis/CableModem/Downstreams and Upstreams).
"""

from __future__ import annotations

import hashlib
import logging
import random
import time

import requests

from .base import ModemDriver
from .formats.sagemcom import (
    _sagemcom_frequency,
    _sagemcom_is_ofdm,
    _sagemcom_modulation,
    parse_sagemcom_xmo_downstream,
    parse_sagemcom_xmo_upstream,
)
from ..types import ConnectionInfo, DeviceInfo, DocsisData, RawChannel

log = logging.getLogger("docsis.driver.sagemcom")


class XMOSessionError(RuntimeError):
    """Raised when the modem returns a session-related XMO error."""

_API_PATH = "/cgi/json-req"
_NSS = [{"name": "gtw", "uri": "http://sagemcom.com/gateway-data"}]

_SESSION_OPTIONS = {
    "nss": _NSS,
    "language": "ident",
    "context-flags": {"get-content-name": True, "local-time": True},
    "capability-depth": 2,
    "capability-flags": {
        "name": True,
        "default-value": False,
        "restriction": True,
        "description": False,
    },
    "time-format": "ISO_8601",
    "write-only-string": "_XMO_WRITE_ONLY_",
    "undefined-write-only-string": "_XMO_UNDEFINED_WRITE_ONLY_",
}


class SagemcomDriver(ModemDriver):
    """Driver for Sagemcom F@st 3896 cable modems.

    Uses XMO JSON-RPC API with SHA-512 digest authentication.
    """

    FORMAT_FAMILIES = ("sagemcom_xmo_json",)

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url.rstrip("/"), user, password)
        self._session = requests.Session()
        self._session.verify = False
        self._session_id = 0
        self._server_nonce = ""
        self._credential_hash = ""
        self._request_id = 0
        self._logged_in = False
        self._password_hash = hashlib.sha512(password.encode()).hexdigest()

    def login(self) -> None:
        if self._logged_in:
            return

        for attempt in range(2):
            try:
                self._do_login()
                log.info("Sagemcom login OK (session %s)", self._session_id)
                self._logged_in = True
                return
            except requests.ConnectionError:
                if attempt == 0:
                    log.warning("Sagemcom connection lost, retrying")
                    self._reset_session()
                    time.sleep(1)
                    continue
                raise RuntimeError("Sagemcom login failed: connection refused after retry")
            except XMOSessionError:
                if attempt == 0:
                    log.warning("Sagemcom session error during login, resetting")
                    self._reset_session()
                    time.sleep(1)
                    continue
                raise RuntimeError("Sagemcom login failed: session error after retry")
            except requests.RequestException as e:
                raise RuntimeError(f"Sagemcom login failed: {e}")

    def _reset_session(self) -> None:
        self._session.close()
        self._session = requests.Session()
        self._session.verify = False
        self._session_id = 0
        self._server_nonce = ""
        self._credential_hash = ""
        self._request_id = 0
        self._logged_in = False

    def _do_login(self) -> None:
        self._request_id = 0
        # Initial credential hash uses empty server nonce (nonce not yet known)
        self._credential_hash = hashlib.sha512(
            f"{self._user}::{self._password_hash}".encode()
        ).hexdigest()

        body = self._build_request([{
            "id": 0,
            "method": "logIn",
            "parameters": {
                "user": self._user,
                "persistent": True,
                "session-options": _SESSION_OPTIONS,
            },
        }], priority=True)

        resp = self._raw_post(body)
        reply = resp.get("reply", {})

        error = reply.get("error", {})
        if error.get("description") != "XMO_REQUEST_NO_ERR":
            raise RuntimeError(f"Sagemcom login failed: {error.get('description', 'unknown')}")

        actions = reply.get("actions", [])
        if not actions:
            raise RuntimeError("Sagemcom login failed: no actions in response")

        action = actions[0]
        callbacks = action.get("callbacks", [])
        if not callbacks:
            raise RuntimeError("Sagemcom login failed: no callbacks in response")

        params = callbacks[0].get("parameters", {})
        self._session_id = params.get("id", 0)
        self._server_nonce = str(params.get("nonce", ""))

        if not self._session_id or not self._server_nonce:
            raise RuntimeError("Sagemcom login failed: missing session_id or nonce")

        self._credential_hash = hashlib.sha512(
            f"{self._user}:{self._server_nonce}:{self._password_hash}".encode()
        ).hexdigest()

    def get_docsis_data(self) -> DocsisData:
        try:
            return self._fetch_docsis_data()
        except (requests.HTTPError, RuntimeError) as e:
            log.warning("DOCSIS data fetch failed (%s), re-authenticating", e)
            self._logged_in = False
            self.login()
            return self._fetch_docsis_data()

    def _fetch_docsis_data(self) -> DocsisData:
        actions = [
            {"id": 0, "method": "getValue",
             "xpath": "Device/Docsis/CableModem/Downstreams",
             "options": {"capability-flags": {"interface": True}}},
            {"id": 1, "method": "getValue",
             "xpath": "Device/Docsis/CableModem/Upstreams",
             "options": {"capability-flags": {"interface": True}}},
        ]
        resp = self._api_call(actions)
        reply_actions = resp.get("reply", {}).get("actions", [])

        ds_raw = []
        us_raw = []
        for action in reply_actions:
            for cb in action.get("callbacks", []):
                xpath = cb.get("xpath", "")
                values = cb.get("parameters", {}).get("value", [])
                if "Downstreams" in xpath:
                    ds_raw = values
                elif "Upstreams" in xpath:
                    us_raw = values

        ds30, ds31 = self._parse_downstream(ds_raw)
        us30, us31 = self._parse_upstream(us_raw)

        return {
            "channelDs": {"docsis30": ds30, "docsis31": ds31},
            "channelUs": {"docsis30": us30, "docsis31": us31},
        }

    def get_device_info(self) -> DeviceInfo:
        try:
            actions = [
                {"id": 0, "method": "getValue",
                 "xpath": "Device/DeviceInfo/ModelName"},
                {"id": 1, "method": "getValue",
                 "xpath": "Device/DeviceInfo/SoftwareVersion"},
            ]
            resp = self._api_call(actions)
            reply_actions = resp.get("reply", {}).get("actions", [])

            model = ""
            sw_version = ""
            for action in reply_actions:
                for cb in action.get("callbacks", []):
                    xpath = cb.get("xpath", "")
                    value = cb.get("parameters", {}).get("value", "")
                    if "ModelName" in xpath:
                        model = value
                    elif "SoftwareVersion" in xpath:
                        sw_version = value

            return {
                "manufacturer": "Sagemcom",
                "model": model,
                "sw_version": sw_version,
            }
        except Exception:
            self._logged_in = False
            return {"manufacturer": "Sagemcom", "model": "", "sw_version": ""}

    def get_connection_info(self) -> ConnectionInfo:
        return {}

    # -- XMO API transport --

    def _api_call(self, actions: list[dict[str, object]]) -> dict[str, object]:
        self._request_id += 1
        body = self._build_request(actions)
        return self._raw_post(body)

    def _build_request(self, actions: list[dict[str, object]], priority: bool = False) -> dict[str, object]:
        cnonce = random.randint(0, 4294967295)
        auth_key = ""

        if self._credential_hash:
            auth_key = hashlib.sha512(
                f"{self._credential_hash}:{self._request_id}:{cnonce}:JSON:{_API_PATH}".encode()
            ).hexdigest()

        return {
            "request": {
                "id": self._request_id,
                "session-id": self._session_id,
                "priority": priority,
                "actions": actions,
                "cnonce": cnonce,
                "auth-key": auth_key,
            }
        }

    def _raw_post(self, body: dict[str, object]) -> dict[str, object]:
        url = f"{self._url}{_API_PATH}"
        r = self._session.post(
            url,
            data={"req": self._json_encode(body)},
            headers={
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "X-Requested-With": "XMLHttpRequest",
            },
            timeout=30,
        )
        if not r.ok:
            log.debug("Sagemcom returned HTTP %d: %s", r.status_code, r.text[:500])
            self._logged_in = False
        r.raise_for_status()

        resp = r.json()
        error = resp.get("reply", {}).get("error", {})
        if error.get("description") not in ("XMO_REQUEST_NO_ERR", None):
            for action in resp.get("reply", {}).get("actions", []):
                act_err = action.get("error", {})
                if act_err.get("description") != "XMO_NO_ERR":
                    log.debug("Sagemcom action error: %s", act_err)
            desc = error.get("description", "")
            code = error.get("code")
            msg = f"Sagemcom XMO error: {desc} (code={code})"
            if code == 16777219 or "SESSION" in desc:  # XMO_INVALID_SESSION_ERR
                raise XMOSessionError(msg)
            raise RuntimeError(msg)
        return resp

    @staticmethod
    def _json_encode(obj) -> str:
        import json
        return json.dumps(obj, separators=(",", ":"))

    # Compatibility parser seams.

    def _parse_downstream(self, channels: list[dict[str, object]]) -> tuple[list[RawChannel], list[RawChannel]]:
        return parse_sagemcom_xmo_downstream(channels).value

    def _parse_upstream(self, channels: list[dict[str, object]]) -> tuple[list[RawChannel], list[RawChannel]]:
        return parse_sagemcom_xmo_upstream(channels).value

    @staticmethod
    def _hz_to_mhz(freq_hz) -> str:
        return _sagemcom_frequency(freq_hz)

    @staticmethod
    def _is_ofdm_downstream(modulation: str, bandwidth: int) -> bool:
        return _sagemcom_is_ofdm(modulation, bandwidth)

    @staticmethod
    def _normalize_modulation(modulation: str) -> str:
        return _sagemcom_modulation(modulation)

    @staticmethod
    def _normalize_us_modulation(modulation: str) -> str:
        return modulation.strip().upper() if modulation else ""
