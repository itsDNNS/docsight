"""Authenticated Sercom DM1000 modem driver for DOCSight.

The DM1000 web UI uses a classic ``/setup.cgi`` form login and exposes
DOCSIS signal tables through JSON endpoints selected by a ``todo`` query
parameter. The captured UI labels the JSON MIME type as ``applation/json``;
this driver parses the response body directly through ``requests`` instead of
relying on the header.

The reporter-provided capture covers signal data only. Vendor modem event logs
are intentionally out of scope here, matching DOCSight's other modem drivers.
"""

from __future__ import annotations

import base64
import logging
import math
import os
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from ..types import ConnectionInfo, DeviceInfo, DocsisData, RawChannel
from .base import ModemDriver
from .utils import hz_to_mhz, normalize_modulation

log = logging.getLogger("docsis.driver.sercom_dm1000")

_AUTH_STATUSES = {401, 403}
_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_BROWSER_ACCEPT_LANGUAGE = "en-GB,en-US;q=0.9,en;q=0.8"
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/147.0.0.0 Safari/537.36"
)
_DIAGNOSTIC_ENV = "DOCSIGHT_SERCOM_DM1000_DIAGNOSTICS"
_SAFE_DIAGNOSTIC_HEADER_VALUES = {
    "connection",
    "content-length",
    "content-type",
    "location",
    "pragma",
    "server",
    "transfer-encoding",
}
_DIAGNOSTIC_HEADER_CAP = 512
_DIAGNOSTIC_BODY_PEEK = 64
_LOGIN_REJECTION_PHRASES = ("redirected to login", "html login page", "login was redirected")


class SercomDM1000Driver(ModemDriver):
    """Driver for authenticated Sercom DM1000 cable modem UIs."""

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url.rstrip("/"), user, password)
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Accept-Language": _BROWSER_ACCEPT_LANGUAGE,
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self._url}/status.html",
            "User-Agent": _BROWSER_USER_AGENT,
        })
        self._diagnostics_enabled = self._env_flag_enabled(os.environ.get(_DIAGNOSTIC_ENV, ""))
        self._diagnostic_signatures: set[tuple[Any, ...]] = set()

    def login(self) -> None:
        """Authenticate with the Sercom form and verify a protected endpoint."""
        errors: list[RuntimeError] = []
        for label, password_value in self._login_password_variants():
            try:
                self._login_with_password_value(password_value)
            except RuntimeError as exc:
                errors.append(exc)
                if not self._is_login_rejection(exc):
                    raise
                log.info("Sercom DM1000 %s login attempt was rejected; trying fallback", label)
                self._session.cookies.clear()
                continue
            log.info("Sercom DM1000 login OK")
            return

        if errors:
            raise errors[-1]
        raise RuntimeError("Sercom DM1000 login failed: no password payload variants available")

    def _login_with_password_value(self, password_value: str) -> None:
        payload = self._login_payload(password_value)
        self._load_login_page()
        self._log_diagnostic_snapshot("before_login_post")
        try:
            resp = self._session.post(
                f"{self._url}/setup.cgi",
                data=payload,
                headers={
                    "Accept": _HTML_ACCEPT,
                    "Accept-Language": _BROWSER_ACCEPT_LANGUAGE,
                    "Origin": self._url,
                    "Referer": f"{self._url}/login.html",
                    "Upgrade-Insecure-Requests": "1",
                    # Override the session-level XHR header for the form POST;
                    # requests omits headers set to None when preparing the call.
                    "X-Requested-With": None,
                },
                allow_redirects=False,
                timeout=15,
            )
            self._log_response_diagnostics("login_post", resp)
            resp.raise_for_status()
        except requests.RequestException as exc:
            self._log_failure_diagnostics("login_post", exc)
            raise RuntimeError(f"Sercom DM1000 login failed: {exc}") from exc

        if marker := self._login_redirect_marker(resp):
            raise RuntimeError(f"Sercom DM1000 login was redirected to login ({marker})")

        # The captured browser flow first primes the authenticated UI context
        # from setup.cgi, then performs a normal status-page navigation before
        # the RF JSON XHRs run. Some firmware builds redirect status.html back
        # to login.html unless this post-login JSON probe has happened first.
        self._fetch_payload(
            "Pd_info",
            raise_on_error=False,
            allow_reauth=False,
            referer=f"{self._url}/setup.cgi",
        )
        self._load_status_page()

        # A Sercom login can return 200 + HTML even when authentication failed.
        # Probe a protected JSON endpoint before reporting success.
        self._fetch_payload("RF_DS_param", raise_on_error=True, allow_reauth=False)

    def _login_payload(self, password_value: str) -> dict[str, str]:
        return {
            "login_user": self._user,
            # Sercom's login form populates both fields. The UI loads
            # base64.js, so the primary attempt mirrors that browser-side
            # encoded value while a raw fallback preserves older captures.
            "pws": password_value,
            "submit": "Apply",
            "is_parent_window": "1",
            "todo": "login",
            "this_file": "login.html",
            "next_file": "",
            "language": "en",
            "message": "",
            "passwd": password_value,
            "cur_passwd": "",
        }

    def _login_password_variants(self) -> list[tuple[str, str]]:
        raw = self._password
        encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
        variants = [("base64", encoded), ("raw", raw)]
        deduped: list[tuple[str, str]] = []
        seen: set[str] = set()
        for label, value in variants:
            if value in seen:
                continue
            seen.add(value)
            deduped.append((label, value))
        return deduped

    @staticmethod
    def _is_login_rejection(exc: RuntimeError) -> bool:
        message = str(exc).lower()
        return any(phrase in message for phrase in _LOGIN_REJECTION_PHRASES)

    def _load_login_page(self) -> None:
        try:
            resp = self._session.get(
                f"{self._url}/login.html",
                headers={
                    "Accept": _HTML_ACCEPT,
                    "Accept-Language": _BROWSER_ACCEPT_LANGUAGE,
                    "Referer": f"{self._url}/login.html",
                    "Upgrade-Insecure-Requests": "1",
                    # Remove the session-level XHR marker for normal page navigation.
                    "X-Requested-With": None,
                },
                timeout=15,
            )
            self._log_response_diagnostics("login_page", resp)
            resp.raise_for_status()
        except requests.RequestException as exc:
            self._log_failure_diagnostics("login_page", exc)
            raise RuntimeError(f"Sercom DM1000 login page load failed: {exc}") from exc

    def _load_status_page(self) -> None:
        try:
            resp = self._session.get(
                f"{self._url}/status.html",
                headers={
                    "Accept": _HTML_ACCEPT,
                    "Accept-Language": _BROWSER_ACCEPT_LANGUAGE,
                    # The HAR records status.html as a normal navigation from
                    # setup.cgi, not as an XHR. Preserve that shape before the
                    # first protected RF JSON probe.
                    "Referer": f"{self._url}/setup.cgi",
                    "Upgrade-Insecure-Requests": "1",
                    "X-Requested-With": None,
                },
                timeout=15,
            )
            self._log_response_diagnostics("status_page", resp)
            resp.raise_for_status()
        except requests.RequestException as exc:
            self._log_failure_diagnostics("status_page", exc)
            raise RuntimeError(f"Sercom DM1000 status page load failed: {exc}") from exc

    def get_docsis_data(self) -> DocsisData:
        """Retrieve DOCSIS channel data from the captured Sercom endpoints."""
        ds_info = self._fetch_payload("RF_DS_param")
        ds_ofdm = self._fetch_payload("RF_DS_31_param")
        us_info = self._fetch_payload("RF_US_param")
        us_ofdma = self._fetch_payload("RF_US_31_param")

        return {
            "channelDs": {
                "docsis30": self._parse_ds_scqam(self._nodes(ds_info)),
                "docsis31": self._parse_ds_ofdm(self._nodes(ds_ofdm)),
            },
            "channelUs": {
                "docsis30": self._parse_us_scqam(self._nodes(us_info)),
                "docsis31": self._parse_us_ofdma(self._nodes(us_ofdma)),
            },
        }

    def get_device_info(self) -> DeviceInfo:
        """Return model metadata, using safe static fallback when Pd_info is absent."""
        payload = self._fetch_payload("Pd_info")
        model = self._first_text(payload, "model", "Model", "ModelName", "ProductName") or "DM1000"
        sw_version = self._first_text(payload, "sw_version", "SoftwareVersion", "firmware", "FirmwareVersion")
        return {"manufacturer": "Sercom", "model": model, "sw_version": sw_version}

    def get_connection_info(self) -> ConnectionInfo:
        """Retrieve basic interface state when exposed by the modem."""
        payload = self._fetch_payload("Interface_param")
        nodes = self._nodes(payload)
        wan = next((row for row in nodes if str(row.get("name", "")).lower() == "wan0"), None)
        if not wan:
            return {}
        return {
            "connection_type": "DOCSIS",
            "status": str(wan.get("state") or ""),
        }

    def _fetch_payload(
        self,
        todo: str,
        *,
        raise_on_error: bool = False,
        allow_reauth: bool = True,
        referer: str | None = None,
    ) -> dict[str, Any]:
        """Fetch a ``/setup.cgi?todo=...`` JSON object with one reauth retry."""
        try:
            headers = {"Referer": referer} if referer else None
            resp = self._session.get(
                f"{self._url}/setup.cgi",
                params={"todo": todo},
                headers=headers,
                allow_redirects=False,
                timeout=30,
            )
            self._log_response_diagnostics(f"fetch_{todo}", resp)
            resp.raise_for_status()
        except requests.HTTPError as exc:
            if allow_reauth and self._is_auth_error(exc):
                log.info("Sercom DM1000 session expired while fetching %s; retrying after login", todo)
                return self._retry_after_reauth(todo, raise_on_error=raise_on_error)
            if raise_on_error:
                raise RuntimeError(f"Sercom DM1000 fetch {todo} failed: {exc}") from exc
            log.warning("Sercom DM1000 fetch %s failed: %s", todo, exc)
            return {}
        except requests.RequestException as exc:
            self._log_failure_diagnostics(f"fetch_{todo}", exc)
            if raise_on_error:
                raise RuntimeError(f"Sercom DM1000 fetch {todo} failed: {exc}") from exc
            log.warning("Sercom DM1000 fetch %s failed: %s", todo, exc)
            return {}

        if marker := self._login_redirect_marker(resp):
            message = f"Sercom DM1000 fetch {todo} redirected to login ({marker})"
            if allow_reauth:
                log.info("%s; retrying after login", message)
                return self._retry_after_reauth(todo, raise_on_error=raise_on_error)
            if raise_on_error:
                raise RuntimeError(message)
            log.warning(message)
            return {}

        if self._looks_like_html(resp):
            message = f"Sercom DM1000 fetch {todo} returned an HTML login page"
            if allow_reauth:
                log.info("%s; retrying after login", message)
                return self._retry_after_reauth(todo, raise_on_error=raise_on_error)
            if raise_on_error:
                raise RuntimeError(message)
            log.warning(message)
            return {}

        try:
            payload = resp.json()
        except ValueError as exc:
            if raise_on_error:
                raise RuntimeError(f"Sercom DM1000 fetch {todo} returned invalid JSON payload") from exc
            log.warning("Sercom DM1000 fetch %s returned invalid JSON payload", todo)
            return {}

        if not isinstance(payload, dict):
            if raise_on_error:
                raise RuntimeError(f"Sercom DM1000 fetch {todo} returned non-object JSON payload")
            log.warning("Sercom DM1000 fetch %s returned non-object JSON payload", todo)
            return {}

        if not self._ensure_ok(payload, todo, raise_on_error=raise_on_error):
            return {}
        return payload

    def _retry_after_reauth(self, todo: str, *, raise_on_error: bool) -> dict[str, Any]:
        try:
            self.login()
        except RuntimeError as exc:
            if raise_on_error:
                raise RuntimeError(f"Sercom DM1000 re-login before fetching {todo} failed: {exc}") from exc
            log.warning("Sercom DM1000 re-login before fetching %s failed: %s", todo, exc)
            return {}
        return self._fetch_payload(todo, raise_on_error=raise_on_error, allow_reauth=False)

    @staticmethod
    def _is_auth_error(exc: requests.HTTPError) -> bool:
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None) in _AUTH_STATUSES

    @staticmethod
    def _env_flag_enabled(value: str) -> bool:
        return value.strip().lower() in {"1", "true", "yes", "on"}

    def _log_diagnostic_snapshot(self, label: str) -> None:
        if not self._diagnostics_enabled:
            return
        self._emit_diagnostic(
            label,
            {
                "session_cookie_names": self._session_cookie_names(),
            },
        )

    def _log_response_diagnostics(self, label: str, resp: requests.Response) -> None:
        if not self._diagnostics_enabled:
            return
        headers = getattr(resp, "headers", {}) or {}
        request = getattr(resp, "request", None)
        request_headers = getattr(request, "headers", {}) or {}
        raw_unparsed = self._raw_unparsed_header_payload(resp)
        self._emit_diagnostic(
            label,
            {
                "status_code": getattr(resp, "status_code", None),
                "parsed_header_names": sorted(str(name) for name in headers.keys()),
                "set_cookie_names": self._set_cookie_names(headers),
                "session_cookie_names": self._session_cookie_names(),
                "request_cookie_names": self._cookie_header_names(str(request_headers.get("Cookie", "") or "")),
                "content_type": str(headers.get("Content-Type", "") or ""),
                "text_len": len(str(getattr(resp, "text", "") or "")),
                "body_shape": self._body_shape(resp),
                "malformed_headers": self._redacted_header_block(raw_unparsed) if raw_unparsed else "",
            },
        )

    def _log_failure_diagnostics(self, label: str, exc: requests.RequestException) -> None:
        if not self._diagnostics_enabled:
            return
        self._emit_diagnostic(
            label,
            {
                "exception_type": exc.__class__.__name__,
                "session_cookie_names": self._session_cookie_names(),
            },
        )

    def _emit_diagnostic(self, label: str, fields: dict[str, Any]) -> None:
        if not self._diagnostics_enabled:
            return
        signature = (
            label,
            fields.get("status_code"),
            tuple(fields.get("session_cookie_names") or []),
            tuple(fields.get("request_cookie_names") or []),
            fields.get("body_shape"),
            fields.get("malformed_headers"),
            fields.get("exception_type"),
        )
        if signature in self._diagnostic_signatures:
            return
        self._diagnostic_signatures.add(signature)
        rendered = " ".join(f"{key}={value!r}" for key, value in fields.items() if value not in (None, "", []))
        log.warning("Sercom DM1000 diagnostic %s: %s", label, rendered)

    def _session_cookie_names(self) -> list[str]:
        try:
            return sorted(str(cookie.name) for cookie in self._session.cookies)
        except Exception:
            return []

    @staticmethod
    def _set_cookie_names(headers: Any) -> list[str]:
        value = str(headers.get("Set-Cookie", "") or "")
        names: list[str] = []
        for segment in value.split(","):
            first = segment.strip().split(";", 1)[0]
            name, separator, _ = first.partition("=")
            if separator and name.strip():
                names.append(name.strip())
        return names

    @staticmethod
    def _cookie_header_names(header_value: str) -> list[str]:
        names: list[str] = []
        for segment in header_value.split(";"):
            name, separator, _ = segment.strip().partition("=")
            if separator and name:
                names.append(name)
        return names

    @staticmethod
    def _body_shape(resp: requests.Response) -> str:
        text = str(getattr(resp, "text", "") or "").lstrip()[:_DIAGNOSTIC_BODY_PEEK].lower()
        if not text:
            return "empty"
        if text.startswith(("<html", "<!doctype html")):
            return "html"
        if text.startswith(("{", "[")):
            return "jsonish"
        return "other"

    @staticmethod
    def _redacted_header_block(block: str) -> str:
        lines: list[str] = []
        for raw_line in str(block or "").splitlines():
            name, separator, value = raw_line.partition(":")
            header_name = name.strip()
            if not separator or not header_name:
                lines.append("[redacted]")
                continue
            normalized = header_name.lower()
            if normalized in _SAFE_DIAGNOSTIC_HEADER_VALUES:
                rendered_value = value.strip()
                if normalized == "location":
                    rendered_value = SercomDM1000Driver._sanitize_location_header(rendered_value)
                lines.append(f"{header_name}: {rendered_value}")
            else:
                lines.append(f"{header_name}: [redacted]")
        redacted = " | ".join(lines)
        if len(redacted) > _DIAGNOSTIC_HEADER_CAP:
            return f"{redacted[:_DIAGNOSTIC_HEADER_CAP]}..."
        return redacted

    @staticmethod
    def _sanitize_location_header(value: str) -> str:
        try:
            parts = urlsplit(value.strip())
            netloc = parts.hostname or ""
            if parts.port is not None:
                netloc = f"{netloc}:{parts.port}"
        except ValueError:
            return "[redacted]"
        if parts.scheme or parts.netloc:
            return urlunsplit((parts.scheme, netloc, parts.path, "", ""))
        if parts.query or parts.fragment:
            return urlunsplit(("", "", parts.path, "", ""))
        return value.strip()

    @staticmethod
    def _looks_like_html(resp: requests.Response) -> bool:
        content_type = str(resp.headers.get("Content-Type", "")).lower()
        text = str(getattr(resp, "text", "") or "").lstrip().lower()
        return "text/html" in content_type or text.startswith(("<html", "<!doctype html"))

    @staticmethod
    def _login_redirect_marker(resp: requests.Response) -> str:
        location = str(resp.headers.get("Location", "") or "")
        if "login.html" in location.lower():
            return f"Location: {location}"

        text = str(getattr(resp, "text", "") or "")
        if SercomDM1000Driver._contains_login_location_header_line(text):
            return "body Location: login.html"

        raw_text = SercomDM1000Driver._raw_unparsed_header_payload(resp)
        if SercomDM1000Driver._contains_login_location_header_line(raw_text):
            return "malformed header Location: login.html"

        return ""

    @staticmethod
    def _contains_login_location_header_line(text: str) -> bool:
        for line in text.splitlines():
            key, separator, value = line.strip().partition(":")
            if separator and key.lower() == "location" and "login.html" in value.lower():
                return True
        return False

    @staticmethod
    def _raw_unparsed_header_payload(resp: requests.Response) -> str:
        # Best-effort fallback for Sercom's malformed header block. urllib3
        # stores the unparsed remainder behind private attributes, which may be
        # absent or change across versions, so failures here must stay harmless.
        try:
            original_response = getattr(resp.raw, "_original_response", None)
            message = getattr(original_response, "msg", None)
            payload = message.get_payload() if message is not None else ""
        except Exception:
            return ""
        return str(payload or "")

    @staticmethod
    def _ensure_ok(payload: dict[str, Any], context: str, *, raise_on_error: bool = False) -> bool:
        code = payload.get("errCode")
        if code is None or str(code) == "000":
            return True
        message = str(payload.get("errMsg") or f"errCode {code}")
        if raise_on_error:
            raise RuntimeError(f"Sercom DM1000 {context} failed: {message}")
        log.warning("Sercom DM1000 %s failed: %s", context, message)
        return False

    @staticmethod
    def _nodes(payload: dict[str, Any]) -> list[dict[str, Any]]:
        nodes = payload.get("nodes") if isinstance(payload, dict) else None
        if not isinstance(nodes, list):
            return []
        return [row for row in nodes if isinstance(row, dict)]

    @staticmethod
    def _first_text(payload: dict[str, Any], *keys: str) -> str:
        for key in keys:
            value = payload.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
        for row in SercomDM1000Driver._nodes(payload):
            name = str(row.get("name") or row.get("key") or "").lower()
            for key in keys:
                if name == key.lower():
                    value = row.get("value") or row.get("text") or row.get("index1")
                    if value is not None and str(value).strip():
                        return str(value).strip()
        return ""

    def _parse_ds_scqam(self, rows: list[dict[str, Any]]) -> list[RawChannel]:
        channels: list[RawChannel] = []
        for row in rows:
            try:
                modulation = normalize_modulation(row.get("qamD", ""))
                if not modulation or modulation in {"QAM_NONE", "NONE"}:
                    continue
                snr = float(row["SNRD"])
                channels.append({
                    "channelID": int(row["DCIDD"]),
                    "frequency": hz_to_mhz(row.get("FreqD", "")),
                    "powerLevel": float(row["PowerD"]),
                    "modulation": modulation,
                    "mer": snr,
                    # Keep the long-standing DOCSight raw-channel convention:
                    # drivers expose MSE as the inverse of SNR/MER when the
                    # modem does not provide a separate MSE counter.
                    "mse": -snr,
                    "corrErrors": int(row["correctedsD"]),
                    "nonCorrErrors": int(row["uncorrectedsD"]),
                })
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Failed to parse Sercom DM1000 DS row: %s", exc)
        return channels

    def _parse_ds_ofdm(self, rows: list[dict[str, Any]]) -> list[RawChannel]:
        channels: list[RawChannel] = []
        for row in rows:
            try:
                if str(row.get("PLC", "")).strip().upper() != "YES":
                    continue
                if str(row.get("MDC1", "")).strip().upper() != "YES":
                    continue
                mer = self._optional_float(row.get("AV_Data"))
                if mer is None:
                    mer = self._optional_float(row.get("AV_PLC"))
                if mer is None:
                    continue
                channels.append({
                    "channelID": int(row["num"]),
                    "type": "OFDM",
                    "frequency": hz_to_mhz(row.get("OFDMFreq", "")),
                    "powerLevel": float(row["PLC_power"]),
                    "modulation": "OFDM",
                    # The Sercom UI labels these as average OFDM values; use
                    # data-subcarrier MER first and PLC MER only as a fallback.
                    "mer": mer,
                    "mse": None,
                    "corrErrors": None,
                    "nonCorrErrors": None,
                })
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Failed to parse Sercom DM1000 DS OFDM row: %s", exc)
        return channels

    def _parse_us_scqam(self, rows: list[dict[str, Any]]) -> list[RawChannel]:
        channels: list[RawChannel] = []
        for row in rows:
            try:
                modulation = normalize_modulation(row.get("modulation", ""))
                upstream = str(row.get("upstream", "")).strip()
                rate_text = str(row.get("rate", "")).strip()
                power = float(row["rep_power"])
                if (
                    not modulation
                    or modulation in {"QAM_NONE", "NONE"}
                    or upstream in {"", "---"}
                    or not math.isfinite(power)
                    or rate_text.lower() == "invalid"
                ):
                    continue
                channel: RawChannel = {
                    "channelID": int(upstream),
                    "frequency": hz_to_mhz(row.get("Freq", "")),
                    "powerLevel": power,
                    "modulation": modulation,
                    "multiplex": "ATDMA",
                }
                symbol_rate = self._symbol_rate_ksym(rate_text)
                if symbol_rate is not None:
                    channel["symbolRate"] = symbol_rate
                channels.append(channel)
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Failed to parse Sercom DM1000 US row: %s", exc)
        return channels

    def _parse_us_ofdma(self, rows: list[dict[str, Any]]) -> list[RawChannel]:
        channels: list[RawChannel] = []
        for column in self._pivot_indexed_rows(rows):
            try:
                state = str(column.get("STATE", "")).strip().upper()
                power_state = str(column.get("Power", "")).strip().upper()
                # Captured active state was RNG3. Treat any explicit non-disabled
                # state as usable because Sercom firmware may report other
                # ranging/operational labels while the OFDMA channel is up.
                if power_state != "ON" or state in {"", "DISABLED", "OFF"}:
                    continue
                frequency_value = column.get("Center Freq SC0")
                frequency_mhz = self._optional_float(frequency_value)
                if frequency_mhz is None or frequency_mhz <= 0:
                    continue
                channel: RawChannel = {
                    "channelID": int(str(column.get("CH", "")).strip()),
                    "type": "OFDMA",
                    # The captured label is SC0 rather than a guaranteed center;
                    # preserve the modem-exposed frequency instead of inventing one.
                    "frequency": hz_to_mhz(frequency_value),
                    "powerLevel": self._ofdma_power(column),
                    "modulation": "OFDMA",
                    "multiplex": "OFDMA",
                }
                profile_modulation = self._profile_modulation_from_bits(column.get("bit Loading"))
                if profile_modulation:
                    channel["profile_modulation"] = profile_modulation
                channels.append(channel)
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Failed to parse Sercom DM1000 US OFDMA row: %s", exc)
        return channels

    @staticmethod
    def _pivot_indexed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        indexes: list[str] = []
        pivot: dict[str, dict[str, Any]] = {}
        for row in rows:
            name = str(row.get("name") or "").strip()
            if not name:
                continue
            for key, value in row.items():
                if not key.startswith("index"):
                    continue
                if key not in pivot:
                    pivot[key] = {}
                    indexes.append(key)
                pivot[key][name] = value
        return [pivot[key] for key in sorted(indexes, key=SercomDM1000Driver._index_sort_key)]

    @staticmethod
    def _index_sort_key(index_name: str) -> int:
        suffix = index_name.removeprefix("index")
        try:
            return int(suffix)
        except ValueError:
            return 0

    @staticmethod
    def _ofdma_power(column: dict[str, Any]) -> float | None:
        if "rep power1_6" not in column:
            log.warning("Sercom DM1000 OFDMA row missing rep power1_6; leaving power unsupported")
            return None
        return SercomDM1000Driver._optional_float(column.get("rep power1_6"))

    @staticmethod
    def _optional_float(value: Any) -> float | None:
        try:
            number = float(str(value).strip())
        except (TypeError, ValueError):
            return None
        return number if math.isfinite(number) else None

    @staticmethod
    def _symbol_rate_ksym(value: Any) -> int | None:
        try:
            number = float(str(value).strip())
        except (TypeError, ValueError):
            return None
        if not math.isfinite(number):
            return None
        return int(round(number * 1000))

    @staticmethod
    def _profile_modulation_from_bits(value: Any) -> str | None:
        try:
            bits = int(float(str(value).strip()))
        except (TypeError, ValueError):
            return None
        if bits == 2:
            return "QPSK"
        if bits <= 0 or bits > 12:
            return None
        return f"{2 ** bits}QAM"
