"""Netgear CM1000 driver for DOCSight.

The CM1000 exposes DOCSIS channel data on ``/DocsisStatus.asp``. Firmware
variants use either pipe-delimited JavaScript values or server-rendered
tables, and authenticate with HTTP Basic auth or a Netgear Genie form login
with a per-page ``webToken``. Table columns are mapped by header name so
layouts with or without an ``Unerrored Codewords`` column remain compatible.
"""

from __future__ import annotations

import logging
import re

import requests
from bs4 import BeautifulSoup

from ..types import ConnectionInfo, DeviceInfo, DocsisData
from .base import ModemDriver
from .formats.html_rows import (
    parse_cm1000_downstream_table,
    parse_cm1000_upstream_table,
)
from .formats.javascript import (
    extract_cm1000_tag_value_list,
    parse_cm1000_downstream_tag_values,
    parse_cm1000_upstream_tag_values,
)

log = logging.getLogger("docsis.driver.cm1000")

_STATUS_PATH = "/DocsisStatus.asp"
_LOGIN_PATH = "/GenieLogin.asp"
_LOGIN_ACTION = "/goform/GenieLogin"
_TABLE_IDS = ("dsTable", "usTable", "d31dsTable", "d31usTable")
_NUMBER_RE = re.compile(r"[-+]?\d+(?:\.\d+)?")
_HEADER_RE = re.compile(r"[^a-z0-9]+")
_FUNCTION_START_RE = re.compile(r"function\s+(?P<name>\w+)\s*\(\)\s*\{")
_TAG_VALUE_ASSIGNMENT_RE = re.compile(
    r"\bvar\s+tagValueList\s*=\s*(?P<value>.*?);", re.DOTALL
)
_STRING_LITERAL_RE = re.compile(
    r"'(?P<single>(?:\\.|[^'\\])*)'|\"(?P<double>(?:\\.|[^\"\\])*)\"",
    re.DOTALL,
)
_DS_TAG_VALUE_FUNCTION = "InitDsTableTagValue"
_US_TAG_VALUE_FUNCTION = "InitUsTableTagValue"
_TAG_VALUE_FIELDS_PER_ROW = 7

# CM1000 downstream SC-QAM channels use the North American 6 MHz
# ITU-T J.83 Annex B profiles. The modem status page does not expose symbol
# rate, so provide the standardized kSym/s value for DOCSight capacity math.
_ANNEX_B_DOWNSTREAM_SYMBOL_RATES = {
    "64QAM": 5057,
    "256QAM": 5361,
}

_ALIASES = {
    "channel": {"channel", "channelnumber", "channelno"},
    "lock": {"lockstatus", "status"},
    "modulation": {
        "modulation",
        "channeltype",
        "uschanneltype",
        "profile",
        "profiles",
        "profileid",
        "profileids",
        "profilemodulation",
    },
    "channel_id": {"channelid", "id"},
    "frequency": {"frequency", "frequencyhz"},
    "power": {"power", "powerlevel", "powerdbmv"},
    "snr": {"snr", "mer", "snrmer"},
    "symbol_rate": {"symbolrate", "symbolrateksymsec"},
    "corr": {
        "correctables",
        "correctable",
        "correctablecodewords",
        "corrected",
        "correctedcodewords",
    },
    "uncorr": {
        "uncorrectables",
        "uncorrectable",
        "uncorrectablecodewords",
        "uncorrected",
        "uncorrectedcodewords",
    },
}


class CM1000Driver(ModemDriver):
    """Driver for the Netgear CM1000 DOCSIS 3.1 cable modem."""

    FORMAT_FAMILIES = ("cm1000_html_table", "cm1000_javascript")

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url.rstrip("/"), user, password)
        self._session = self._new_session()
        self._status_html: str | None = None

    def _new_session(self) -> requests.Session:
        session = requests.Session()
        session.auth = (self._user, self._password)
        return session

    def login(self) -> None:
        """Authenticate and cache a validated ``DocsisStatus.asp`` page.

        A direct Basic-auth request is attempted first because some CM1000
        firmware exposes the page that way. If it does not return a status
        page, the driver performs the Genie token/form login and retries.
        """
        self._status_html = None
        for attempt in range(2):
            try:
                direct = self._session.get(self._url + _STATUS_PATH, timeout=30)
                if direct.status_code == 200 and self._is_status_page(direct.text):
                    self._status_html = direct.text
                    log.info("CM1000 auth OK via direct status access")
                    return

                # A 401/403 or a 200 login wrapper is expected on form-login
                # firmware. Other HTTP errors should still be surfaced.
                if direct.status_code not in (200, 401, 403):
                    direct.raise_for_status()

                # Do not send a stale/preemptive Basic Authorization header to
                # the form-login firmware. The authenticated cookie established
                # below is sufficient for the status-page request.
                self._session.auth = None
                self._login_via_form()
                status = self._session.get(self._url + _STATUS_PATH, timeout=30)
                status.raise_for_status()
                self._ensure_status_page(status.text)
                self._status_html = status.text
                log.info("CM1000 auth OK via Genie form login")
                return
            except requests.ConnectionError as exc:
                if attempt == 0:
                    log.warning("CM1000 connection lost, retrying with fresh session")
                    self._session.close()
                    self._session = self._new_session()
                    continue
                raise RuntimeError(
                    "CM1000 authentication failed: connection refused after retry"
                ) from exc
            except requests.RequestException as exc:
                raise RuntimeError(f"CM1000 authentication failed: {exc}") from exc

    def get_docsis_data(self) -> DocsisData:
        html = self._fetch_status_page()
        soup = BeautifulSoup(html, "html.parser")

        ds_tag_values = extract_cm1000_tag_value_list(html, _DS_TAG_VALUE_FUNCTION)
        if ds_tag_values is not None:
            ds30 = parse_cm1000_downstream_tag_values(ds_tag_values).value
        else:
            ds30 = parse_cm1000_downstream_table(soup, "dsTable", docsis31=False).value

        us_tag_values = extract_cm1000_tag_value_list(html, _US_TAG_VALUE_FUNCTION)
        if us_tag_values is not None:
            us30 = parse_cm1000_upstream_tag_values(us_tag_values).value
        else:
            us30 = parse_cm1000_upstream_table(soup, "usTable", docsis31=False).value

        ds31 = parse_cm1000_downstream_table(soup, "d31dsTable", docsis31=True).value
        us31 = parse_cm1000_upstream_table(soup, "d31usTable", docsis31=True).value

        if not any((ds30, us30, ds31, us31)):
            log.warning("CM1000 parsed 0 locked channels from DocsisStatus.asp")

        return {
            "channelDs": {"docsis30": ds30, "docsis31": ds31},
            "channelUs": {"docsis30": us30, "docsis31": us31},
        }

    def get_device_info(self) -> DeviceInfo:
        return {"manufacturer": "Netgear", "model": "CM1000", "sw_version": ""}

    def get_connection_info(self) -> ConnectionInfo:
        return {}

    def _fetch_status_page(self) -> str:
        if self._status_html is not None:
            return self._status_html
        try:
            response = self._session.get(self._url + _STATUS_PATH, timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"CM1000 status page retrieval failed: {exc}") from exc
        self._ensure_status_page(response.text)
        return response.text

    def _login_via_form(self) -> None:
        login_url = self._url + _LOGIN_PATH
        response = self._session.get(login_url, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")
        form = soup.find("form", action=re.compile(r"GenieLogin", re.IGNORECASE))
        if form is None:
            form = soup.find("form")
        if form is None:
            raise RuntimeError("CM1000 login page did not contain a login form")

        payload: dict[str, str] = {}
        for field in form.find_all("input"):
            name = field.get("name")
            if not name:
                continue
            field_type = str(field.get("type", "")).lower()
            if field_type in {"submit", "button", "image"}:
                continue
            payload[str(name)] = str(field.get("value", ""))

        # A few firmware revisions render webToken outside the form. Preserve
        # it when present so the same login path covers both page variants.
        if "webToken" not in payload:
            token = soup.find("input", attrs={"name": "webToken"})
            if token is not None:
                payload["webToken"] = str(token.get("value", ""))

        payload["loginUsername"] = self._user
        payload["loginPassword"] = self._password
        payload.setdefault("login", "1")

        post_url = self._url + _LOGIN_ACTION
        submit = self._session.post(
            post_url, data=payload, timeout=30, allow_redirects=False
        )
        submit.raise_for_status()

    @staticmethod
    def _is_status_page(html: str) -> bool:
        if not html:
            return False
        soup = BeautifulSoup(html, "html.parser")
        if any(soup.find("table", id=table_id) is not None for table_id in _TABLE_IDS):
            return True
        return any(
            extract_cm1000_tag_value_list(html, function_name) is not None
            for function_name in (_DS_TAG_VALUE_FUNCTION, _US_TAG_VALUE_FUNCTION)
        )

    @staticmethod
    def _ensure_status_page(html: str) -> None:
        if not html:
            raise RuntimeError("CM1000 returned an empty status page")
        if not CM1000Driver._is_status_page(html):
            raise RuntimeError(
                "CM1000 authentication failed: modem did not return DocsisStatus.asp"
            )
