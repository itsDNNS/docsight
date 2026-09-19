"""Experimental PYUR FAST3896-15 /api/v1 driver; hardware test pending."""

from hashlib import sha512
from http.cookies import CookieError, SimpleCookie
import json
import re
import secrets
from urllib.parse import urlsplit

import requests

from ..types import ConnectionInfo, DeviceInfo, DocsisData
from .base import ModemDriver
from .formats.pyur import parse_pyur_api_v1, parse_pyur_device_info
from .pyur_auth import sha512_crypt


class PyurFast3896Driver(ModemDriver):
    """Session transport for PYUR firmware, incompatible with XMO and LG."""

    FORMAT_FAMILIES = ("pyur_api_v1",)

    def __init__(self, url: str, user: str, password: str):
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme in {"http", "https"} and parsed.hostname
                     and not parsed.username and not parsed.password
                     and not parsed.query and not parsed.fragment
                     and parsed.path in {"", "/"})
            parsed.port  # Validate an explicitly configured port before requests.
        except ValueError:
            valid = False
        if not valid:
            raise ValueError("PYUR requires an HTTP(S) modem origin URL")
        super().__init__(url.rstrip("/"), user or "admin", password)
        self._session = requests.Session()
        self._session.trust_env = False  # No ambient netrc credentials or proxies.
        self._authenticated = False

    def _cookie(self, name: str, path: str) -> str:
        # Use requests' domain/path/secure matching instead of a global jar get.
        request = requests.Request("GET", f"{self._url}/api/v1/{path}").prepare()
        header = requests.cookies.get_cookie_header(self._session.cookies, request) or ""
        if len(header) > 8192:
            raise RuntimeError("PYUR cookie header exceeds limit")
        if sum(part.partition("=")[0].strip() == name for part in header.split(";")) > 1:
            raise RuntimeError("PYUR ambiguous session cookie")
        cookie = SimpleCookie()
        try:
            cookie.load(header)
        except CookieError:
            raise RuntimeError("PYUR invalid session cookies") from None
        return cookie[name].value if name in cookie else ""

    def _request(self, method: str, path: str, data: dict | None = None) -> tuple[int, object]:
        response = None
        try:
            csrf = self._cookie("Host-csrf_token", path)
            if csrf and not re.fullmatch(r"[!-~]{1,256}", csrf):
                raise RuntimeError("PYUR invalid CSRF cookie")
            headers = {"X-Csrf-Token": csrf} if csrf else {}
            response = self._session.request(
                method, f"{self._url}/api/v1/{path}", data=data, headers=headers,
                timeout=(5, 15), allow_redirects=False, stream=True,
            )
            status = response.status_code
            if status == 401:
                return status, None
            if status != (201 if method == "POST" else 200):
                # Never include response text, headers, URL or request data.
                raise RuntimeError(f"PYUR API returned HTTP {status}")
            if method == "POST":
                return status, None  # Captured 201 responses have empty bodies.
            body = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                body.extend(chunk)
                if len(body) > 1024 * 1024:
                    raise RuntimeError("PYUR JSON response exceeds limit")
            return status, json.loads(body)
        except requests.RequestException:
            raise RuntimeError("PYUR API request failed") from None
        except (ValueError, RecursionError):
            raise RuntimeError("PYUR API returned invalid JSON or session data") from None
        finally:
            if response is not None:
                try:
                    response.close()
                except (requests.RequestException, OSError):
                    raise RuntimeError("PYUR response close failed") from None

    def login(self) -> None:
        if self._authenticated:
            return
        # A new challenge must provide both cookies; stale values cannot mask
        # a malformed login-params response. Preserve the remaining session.
        for cookie in list(self._session.cookies):
            if cookie.name in {"salt", "nonce"}:
                self._session.cookies.clear(cookie.domain, cookie.path, cookie.name)
        status, _ = self._request("POST", "login-params", {"login": self._user})
        if status == 401:
            raise RuntimeError("PYUR login challenge rejected")
        salt, nonce = self._cookie("salt", "login"), self._cookie("nonce", "login")
        if not re.fullmatch(r"[./A-Za-z0-9]{8}", salt) or not re.fullmatch(r"[0-9]{1,32}", nonce):
            raise RuntimeError("PYUR invalid login challenge")
        try:
            encrypted = sha512_crypt(self._password, salt)
            first = sha512(f"{self._user}:{nonce}:{encrypted[3:]}".encode("utf-8")).hexdigest()
        except ValueError:
            raise RuntimeError("PYUR invalid login credentials") from None
        cnonce = f"{secrets.randbelow(10**19):019d}"
        auth_key = sha512(f"{first}:0:{cnonce}".encode("ascii")).hexdigest()
        status, _ = self._request("POST", "login", {"login": self._user, "auth_key": auth_key, "cnonce": cnonce})
        if status == 401:
            raise RuntimeError("PYUR login rejected")
        status, payload = self._request("GET", "authenticated")
        if status != 200 or payload != [{"authenticated": "true"}]:
            raise RuntimeError("PYUR authentication verification failed")
        self._authenticated = True

    def _get(self, path: str) -> object:
        self.login()
        for attempt in range(2):
            status, payload = self._request("GET", path)
            if status != 401:
                return payload
            self._authenticated = False
            if attempt == 0:
                self.login()
        raise RuntimeError("PYUR session expired after one retry")

    def get_docsis_data(self) -> DocsisData:
        payload = self._get("docsis-info/connection")
        try:
            return parse_pyur_api_v1(payload).value
        except ValueError:
            raise RuntimeError("PYUR invalid connection payload") from None

    def get_device_info(self) -> DeviceInfo:
        payload = self._get("device")
        try:
            return parse_pyur_device_info(payload).value
        except ValueError:
            raise RuntimeError("PYUR invalid device payload") from None

    def get_connection_info(self) -> ConnectionInfo:
        # Rates are not in the examined connection/device responses.
        return {}
