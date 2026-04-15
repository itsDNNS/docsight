"""Netgear CM3000 driver for DOCSight.

The CM3000 is a standalone DOCSIS 3.1 cable modem by Netgear. It embeds
all channel data as pipe-delimited JavaScript variables on the
/DocsisStatus.htm page -- no HTML tables, no XHR calls.

Five JS functions each contain a ``var tagValueList = '...'`` string:
- InitDsTableTagValue()      -- DS SC-QAM (32 channels, 9 fields each)
- InitUsTableTagValue()      -- US ATDMA  (8 channels, 7 fields each)
- InitDsOfdmTableTagValue()  -- DS OFDM   (2 channels, 11 fields each)
- InitUsOfdmaTableTagValue() -- US OFDMA  (2 channels, 6 fields each)
- InitTagValue()             -- system/device info

Authentication starts with direct status page access and falls back to the
web login form on firmware that redirects through Login.htm first.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin

import requests

from .base import ModemDriver
from ..types import DocsisData, DeviceInfo, ConnectionInfo, RawChannel

log = logging.getLogger("docsis.driver.cm3000")

_STATUS_PATH = "/DocsisStatus.htm"

# Match the single-quoted live tagValueList in each function.
# Commented-out examples use double quotes or /* */ blocks, so
# targeting single quotes skips them reliably.
# Uses .*? (lazy) instead of [^}]*? to support nested braces in
# function bodies (e.g. if-blocks in some firmware versions).
_RE_FUNCTION_START = re.compile(r"function\s+(?P<name>\w+)\s*\(\)\s*\{", re.DOTALL)
_RE_SINGLE_QUOTED = re.compile(r"'([^'\\]*(?:\\.[^'\\]*)*)'", re.DOTALL)
_RE_DOUBLE_QUOTED = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"', re.DOTALL)
_LOGIN_MARKERS = (
    "login.htm",
    "login.html",
    "window.location.replace",
    "sessionstorage.getitem('privatekey')",
    "sessionstorage.getitem(\"privatekey\")",
)
_RE_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_RE_FORM_ACTION = re.compile(r"<form[^>]+action=['\"]([^'\"]+)['\"]", re.IGNORECASE)
_RE_FORM_BLOCK = re.compile(
    r"<form[^>]*action=['\"](?P<action>[^'\"]+)['\"][^>]*>(?P<body>.*?)</form>",
    re.IGNORECASE | re.DOTALL,
)
_RE_INPUT = re.compile(r"<input\b(?P<attrs>[^>]*)>", re.IGNORECASE | re.DOTALL)
_RE_ATTR = re.compile(r"(?P<name>[A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*['\"](?P<value>[^'\"]*)['\"]")

# Fields per channel for each section (after the leading count value).
_DS_QAM_FIELDS = 9   # num|lock|mod|chID|freq|power|snr|corrErr|uncorrErr
_US_ATDMA_FIELDS = 7  # num|lock|type|chID|symbolRate|freq|power
_DS_OFDM_FIELDS = 11  # num|lock|profiles|chID|freq|power|snr|subcarriers|corrErr|uncorrErr|unknown
_US_OFDMA_FIELDS = 6  # num|lock|profiles|chID|freq|power
_RE_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)


class CM3000Driver(ModemDriver):
    """Driver for Netgear CM3000 DOCSIS 3.1 cable modem.

    Authentication uses direct DocsisStatus access with a Login.htm form
    fallback on newer firmware variants.
    DOCSIS data is extracted from JavaScript variables on /DocsisStatus.htm.
    """

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url, user, password)
        self._session = requests.Session()
        self._session.auth = (user, password)
        self._status_html = None

    def login(self) -> None:
        """Establish session and verify DocsisStatus.htm is actually readable.

        Retries once with a fresh session if the modem drops a stale
        TCP connection (common after container restarts).
        """
        for attempt in range(2):
            try:
                r = self._session.get(f"{self._url}{_STATUS_PATH}", timeout=30)
                r.raise_for_status()
                try:
                    self._ensure_status_page(r.text)
                except RuntimeError:
                    if not self._looks_like_login_page(r.text):
                        self._log_status_page_diagnostics(r.text, "login")
                        raise
                    if not self._login_via_form():
                        self._log_status_page_diagnostics(r.text, "login")
                        raise
                    r = self._session.get(f"{self._url}{_STATUS_PATH}", timeout=30)
                    r.raise_for_status()
                    self._ensure_status_page(r.text)
                self._status_html = r.text
                log.info("CM3000 auth OK")
                return
            except requests.ConnectionError:
                if attempt == 0:
                    log.warning("CM3000 connection lost, retrying with fresh session")
                    self._session.close()
                    self._session = requests.Session()
                    self._session.auth = (self._user, self._password)
                    self._status_html = None
                    continue
                raise RuntimeError("CM3000 authentication failed: connection refused after retry")
            except requests.RequestException as e:
                raise RuntimeError(f"CM3000 authentication failed: {e}")
            except RuntimeError as e:
                self._log_status_page_diagnostics(r.text, "login")
                raise e

    def get_docsis_data(self) -> DocsisData:
        """Retrieve DOCSIS channel data from JavaScript on status page.

        Returns pre-split format so the analyzer correctly labels
        QAM channels as DOCSIS 3.0 and OFDM/OFDMA channels as 3.1.
        """
        html = self._fetch_status_page()

        ds30 = self._parse_ds_qam(html)
        us30 = self._parse_us_atdma(html)
        ds31 = self._parse_ds_ofdm(html)
        us31 = self._parse_us_ofdma(html)

        total = len(ds30) + len(us30) + len(ds31) + len(us31)
        if total == 0:
            log.warning(
                "CM3000 parsed 0 channels "
                "(InitDsTableTagValue=%s, InitUsTableTagValue=%s, "
                "InitDsOfdmTableTagValue=%s, InitUsOfdmaTableTagValue=%s, "
                "page length=%d)",
                bool(self._extract_tag_value_list(html, "InitDsTableTagValue")),
                bool(self._extract_tag_value_list(html, "InitUsTableTagValue")),
                bool(self._extract_tag_value_list(html, "InitDsOfdmTableTagValue")),
                bool(self._extract_tag_value_list(html, "InitUsOfdmaTableTagValue")),
                len(html),
            )

        return {
            "channelDs": {"docsis30": ds30, "docsis31": ds31},
            "channelUs": {"docsis30": us30, "docsis31": us31},
        }

    def get_device_info(self) -> DeviceInfo:
        """Extract device info from InitTagValue()."""
        try:
            html = self._fetch_status_page()
            raw_sys_info = self._extract_tag_value_list(html, "InitTagValue")
            if not raw_sys_info:
                return {"manufacturer": "Netgear", "model": "CM3000", "sw_version": ""}

            fields = raw_sys_info.split("|")
            result = {
                "manufacturer": "Netgear",
                "model": "CM3000",
                "sw_version": "",
            }

            # Uptime is at index 14: "23 days 09:26:24"
            if len(fields) > 14:
                uptime = self._parse_uptime(fields[14])
                if uptime is not None:
                    result["uptime_seconds"] = uptime

            return result
        except Exception:
            return {"manufacturer": "Netgear", "model": "CM3000", "sw_version": ""}

    def get_connection_info(self) -> ConnectionInfo:
        """Standalone modem -- no connection info available."""
        return {}

    # -- Internal helpers --

    def _fetch_status_page(self) -> str:
        """Fetch the raw HTML of /DocsisStatus.htm.

        Reuses the validated HTML captured during login when available.
        The cache persists until the next login() call overwrites it,
        so all methods in a single collect cycle use the same page.
        """
        if self._status_html is not None:
            return self._status_html

        try:
            r = self._session.get(
                f"{self._url}{_STATUS_PATH}",
                timeout=30,
            )
            r.raise_for_status()
        except requests.RequestException as e:
            raise RuntimeError(f"CM3000 status page retrieval failed: {e}")
        try:
            self._ensure_status_page(r.text)
        except RuntimeError:
            self._log_status_page_diagnostics(r.text, "fetch")
            raise
        return r.text

    def _login_via_form(self) -> bool:
        """Try the newer Netgear web login flow used before DocsisStatus access."""
        login_url = urljoin(f"{self._url}/", "Login.htm")
        try:
            r = self._session.get(login_url, timeout=30)
            r.raise_for_status()
            action, payload = self._extract_login_form(r.text)
            if not action:
                action = "/goform/Login"
            payload = payload or {}
            self._apply_login_credentials(payload)
            if not any(v for k, v in payload.items() if "pass" in k.lower()):
                payload["loginPassword"] = self._password
            if not any(v for k, v in payload.items() if "user" in k.lower() or "name" in k.lower()):
                payload["loginName"] = self._user
            post_url = urljoin(f"{self._url}/", action.lstrip("/"))
            r = self._session.post(post_url, data=payload, timeout=30)
            r.raise_for_status()
            return True
        except requests.RequestException as exc:
            log.debug("CM3000 form login failed: %s", exc)
            return False

    def _apply_login_credentials(self, payload: dict[str, str]) -> None:
        """Populate parsed login form fields with configured credentials."""
        lowered = {k.lower(): k for k in payload}
        user_keys = [k for k in payload if any(token in k.lower() for token in ("loginname", "username", "user", "name"))]
        pass_keys = [k for k in payload if "pass" in k.lower()]
        for key in user_keys:
            payload[key] = self._user
        for key in pass_keys:
            payload[key] = self._password
        if not user_keys and "loginname" not in lowered:
            payload["loginName"] = self._user
        if not pass_keys and "loginpassword" not in lowered:
            payload["loginPassword"] = self._password

    @staticmethod
    def _extract_login_form(html: str) -> tuple[str | None, dict]:
        """Extract login form action and input values from Login.htm."""
        match = _RE_FORM_BLOCK.search(html or "")
        if not match:
            return None, {}
        action = match.group("action").strip()
        body = match.group("body")
        payload = {}
        for input_match in _RE_INPUT.finditer(body):
            attrs = {
                attr_match.group("name").lower(): attr_match.group("value")
                for attr_match in _RE_ATTR.finditer(input_match.group("attrs"))
            }
            name = attrs.get("name")
            if not name:
                continue
            input_type = attrs.get("type", "").lower()
            if input_type in {"submit", "button", "image"}:
                continue
            payload[name] = attrs.get("value", "")
        return action, payload

    @staticmethod
    def _looks_like_login_page(html: str) -> bool:
        lower_html = (html or "").lower()
        return any(marker in lower_html for marker in _LOGIN_MARKERS)

    @staticmethod
    def _ensure_status_page(html: str) -> None:
        """Reject login/placeholder pages that would otherwise parse as zero channels."""
        if not html:
            raise RuntimeError("CM3000 returned an empty status page")

        has_sys_info = bool(CM3000Driver._extract_tag_value_list(html, "InitTagValue"))
        has_channel_data = any(
            CM3000Driver._extract_tag_value_list(html, function_name)
            for function_name in (
                "InitDsTableTagValue",
                "InitUsTableTagValue",
                "InitDsOfdmTableTagValue",
                "InitUsOfdmaTableTagValue",
            )
        )
        if has_sys_info and has_channel_data:
            return

        lower_html = html.lower()
        if any(marker in lower_html for marker in _LOGIN_MARKERS):
            raise RuntimeError(
                "CM3000 authentication failed: modem returned a login page instead "
                "of DocsisStatus.htm after authentication"
            )

        if not has_sys_info or not has_channel_data:
            raise RuntimeError(
                "CM3000 status page did not contain the expected DOCSIS data blocks"
            )

    @staticmethod
    def _status_page_diagnostics(html: str) -> dict[str, object]:
        """Summarize the response shape for debugging failed CM3000 auth."""
        if not html:
            return {
                "length": 0,
                "title": "",
                "form_action": "",
                "login_markers": [],
                "has_sys_info": False,
                "has_channel_data": False,
            }

        lower_html = html.lower()
        title_match = _RE_TITLE.search(html)
        form_match = _RE_FORM_ACTION.search(html)
        login_markers = [marker for marker in _LOGIN_MARKERS if marker in lower_html]
        has_sys_info = bool(CM3000Driver._extract_tag_value_list(html, "InitTagValue"))
        has_channel_data = any(
            CM3000Driver._extract_tag_value_list(html, function_name)
            for function_name in (
                "InitDsTableTagValue",
                "InitUsTableTagValue",
                "InitDsOfdmTableTagValue",
                "InitUsOfdmaTableTagValue",
            )
        )

        return {
            "length": len(html),
            "title": (title_match.group(1).strip() if title_match else ""),
            "form_action": (form_match.group(1).strip() if form_match else ""),
            "login_markers": login_markers,
            "has_sys_info": has_sys_info,
            "has_channel_data": has_channel_data,
        }

    @staticmethod
    def _log_status_page_diagnostics(html: str, context: str) -> None:
        """Emit a compact debug summary of the CM3000 response page."""
        diag = CM3000Driver._status_page_diagnostics(html)
        log.debug(
            "CM3000 %s diagnostics: len=%s title=%r form_action=%r login_markers=%s "
            "has_sys_info=%s has_channel_data=%s",
            context,
            diag["length"],
            diag["title"],
            diag["form_action"],
            ",".join(diag["login_markers"]) or "(none)",
            diag["has_sys_info"],
            diag["has_channel_data"],
        )

    # -- Channel parsers --

    def _parse_ds_qam(self, html: str) -> list[RawChannel]:
        """Parse downstream SC-QAM channels from InitDsTableTagValue().

        Per channel (9 fields):
        num | lock | modulation | channelID | frequency | power | snr | corrErrors | uncorrErrors
        """
        raw = self._extract_tag_value_list(html, "InitDsTableTagValue")
        if not raw:
            return []

        channels = self._split_channels(raw, _DS_QAM_FIELDS)
        result = []
        for ch in channels:
            if ch[1] != "Locked":
                continue
            try:
                result.append({
                    "channelID": int(ch[3]),
                    "frequency": self._hz_to_mhz(ch[4]),
                    "powerLevel": float(ch[5]),
                    "mer": float(ch[6]),
                    "mse": -float(ch[6]),
                    "modulation": self._normalize_modulation(ch[2]),
                    "corrErrors": int(ch[7]),
                    "nonCorrErrors": int(ch[8]),
                })
            except (ValueError, IndexError) as e:
                log.warning("Failed to parse CM3000 DS QAM channel: %s", e)
        return result

    def _parse_us_atdma(self, html: str) -> list[RawChannel]:
        """Parse upstream ATDMA channels from InitUsTableTagValue().

        Per channel (7 fields):
        num | lock | type | channelID | symbolRate | frequency | power
        """
        raw = self._extract_tag_value_list(html, "InitUsTableTagValue")
        if not raw:
            return []

        channels = self._split_channels(raw, _US_ATDMA_FIELDS)
        result = []
        for ch in channels:
            if ch[1] != "Locked":
                continue
            try:
                result.append({
                    "channelID": int(ch[3]),
                    "frequency": self._hz_to_mhz(ch[5]),
                    "powerLevel": self._parse_number(ch[6]),
                    "modulation": self._normalize_modulation(ch[2]),
                    "multiplex": ch[2].upper() if ch[2] else "",
                })
            except (ValueError, IndexError) as e:
                log.warning("Failed to parse CM3000 US ATDMA channel: %s", e)
        return result

    def _parse_ds_ofdm(self, html: str) -> list[RawChannel]:
        """Parse downstream OFDM channels from InitDsOfdmTableTagValue().

        Per channel (11 fields):
        num | lock | profiles | channelID | frequency | power | snr | subcarriers | corrErrors | uncorrErrors | unknown
        """
        raw = self._extract_tag_value_list(html, "InitDsOfdmTableTagValue")
        if not raw:
            return []

        channels = self._split_channels(raw, _DS_OFDM_FIELDS)
        result = []
        for ch in channels:
            if ch[1] != "Locked":
                continue
            try:
                result.append({
                    "channelID": int(ch[3]),
                    "type": "OFDM",
                    "frequency": self._hz_to_mhz(ch[4]),
                    "powerLevel": self._parse_number(ch[5]),
                    "mer": self._parse_number(ch[6]),
                    "mse": None,
                    "corrErrors": int(ch[8]),
                    "nonCorrErrors": int(ch[9]),
                })
            except (ValueError, IndexError) as e:
                log.warning("Failed to parse CM3000 DS OFDM channel: %s", e)
        return result

    def _parse_us_ofdma(self, html: str) -> list[RawChannel]:
        """Parse upstream OFDMA channels from InitUsOfdmaTableTagValue().

        Per channel (6 fields):
        num | lock | profiles | channelID | frequency | power
        """
        raw = self._extract_tag_value_list(html, "InitUsOfdmaTableTagValue")
        if not raw:
            return []

        channels = self._split_channels(raw, _US_OFDMA_FIELDS)
        result = []
        for ch in channels:
            if ch[1] != "Locked":
                continue
            try:
                result.append({
                    "channelID": int(ch[3]),
                    "type": "OFDMA",
                    "frequency": self._hz_to_mhz(ch[4]),
                    "powerLevel": self._parse_number(ch[5]),
                    "modulation": "OFDMA",
                    "multiplex": "",
                })
            except (ValueError, IndexError) as e:
                log.warning("Failed to parse CM3000 US OFDMA channel: %s", e)
        return result

    # -- Value parsers --

    @staticmethod
    def _extract_tag_value_list(html: str, function_name: str) -> str | None:
        """Extract the live tagValueList payload from a firmware JS function.

        CM3000 firmware variants use different quoting styles and may build
        the string across multiple concatenated literals. We extract the full
        function body, remove block comments, and then join the string
        literals from the live tagValueList assignment.
        """
        body = CM3000Driver._extract_function_body(html, function_name)
        if not body:
            return None

        body = _RE_BLOCK_COMMENT.sub("", body)
        assign_idx = body.find("var tagValueList")
        if assign_idx == -1:
            return None

        assign_expr = body[assign_idx:]
        assign_expr = assign_expr.split("=", 1)
        if len(assign_expr) != 2:
            return None

        assign_expr = assign_expr[1]
        return_idx = assign_expr.find("return tagValueList.split")
        if return_idx != -1:
            assign_expr = assign_expr[:return_idx]
        assign_expr = assign_expr.strip().rstrip(";").strip()

        singles = _RE_SINGLE_QUOTED.findall(assign_expr)
        doubles = _RE_DOUBLE_QUOTED.findall(assign_expr)
        literals = singles + doubles
        if not literals:
            return None

        return "".join(bytes(value, "utf-8").decode("unicode_escape") for value in literals)

    @staticmethod
    def _extract_function_body(html: str, function_name: str) -> str | None:
        """Return the body text for a named JavaScript function."""
        for match in _RE_FUNCTION_START.finditer(html):
            if match.group("name") != function_name:
                continue

            body_start = match.end()
            depth = 1
            idx = body_start
            while idx < len(html) and depth > 0:
                char = html[idx]
                if char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                idx += 1

            if depth == 0:
                return html[body_start : idx - 1]
            return None
        return None

    @staticmethod
    def _split_channels(raw: str, fields_per_channel: int) -> list[list[str]]:
        """Split a pipe-delimited tagValueList into per-channel field lists.

        The first value is the channel count, followed by repeating groups
        of ``fields_per_channel`` fields.
        """
        parts = raw.split("|")
        # First element is the count -- skip it
        data = parts[1:]
        # Remove trailing empty element from trailing pipe
        if data and data[-1] == "":
            data = data[:-1]

        channels = []
        for i in range(0, len(data), fields_per_channel):
            chunk = data[i : i + fields_per_channel]
            if len(chunk) == fields_per_channel:
                channels.append(chunk)
        return channels

    @staticmethod
    def _hz_to_mhz(freq_str: str) -> str:
        from .utils import hz_to_mhz
        return hz_to_mhz(freq_str)

    @staticmethod
    def _parse_number(value: str) -> float:
        from .utils import parse_number
        return parse_number(value)

    @staticmethod
    def _normalize_modulation(mod: str) -> str:
        """Normalize modulation string.

        'QAM256' -> 'QAM256'
        'ATDMA' -> 'ATDMA'
        We preserve the original format since the CM3500 driver does the same.
        """
        return mod.strip() if mod else ""

    @staticmethod
    def _parse_uptime(uptime_str: str) -> int | None:
        """Parse uptime string to seconds.

        '23 days 09:26:24' -> 2020784
        """
        m = re.match(r"(\d+)\s+days?\s+(\d+):(\d+):(\d+)", uptime_str.strip())
        if m:
            return (
                int(m.group(1)) * 86400
                + int(m.group(2)) * 3600
                + int(m.group(3)) * 60
                + int(m.group(4))
            )
        return None
