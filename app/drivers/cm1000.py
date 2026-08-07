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

from ..types import ConnectionInfo, DeviceInfo, DocsisData, RawChannel
from .base import ModemDriver
from .utils import hz_to_mhz, normalize_modulation

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

        ds_tag_values = self._extract_tag_value_list(html, _DS_TAG_VALUE_FUNCTION)
        if ds_tag_values is not None:
            ds30 = self._parse_downstream_tag_values(ds_tag_values)
        else:
            ds30 = self._parse_downstream_table(soup, "dsTable", docsis31=False)

        us_tag_values = self._extract_tag_value_list(html, _US_TAG_VALUE_FUNCTION)
        if us_tag_values is not None:
            us30 = self._parse_upstream_tag_values(us_tag_values)
        else:
            us30 = self._parse_upstream_table(soup, "usTable", docsis31=False)

        ds31 = self._parse_downstream_table(soup, "d31dsTable", docsis31=True)
        us31 = self._parse_upstream_table(soup, "d31usTable", docsis31=True)

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
            CM1000Driver._extract_tag_value_list(html, function_name) is not None
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

    @staticmethod
    def _normalize_header(value: str) -> str:
        return _HEADER_RE.sub("", value.lower())

    @classmethod
    def _table_rows(cls, soup: BeautifulSoup, table_id: str) -> list[dict[str, str]]:
        table = soup.find("table", id=table_id)
        if table is None:
            return []

        headers: list[str] = []
        result: list[dict[str, str]] = []
        for row in table.find_all("tr"):
            cells = row.find_all(["th", "td"], recursive=False)
            if not cells:
                cells = row.find_all(["th", "td"])
            values = [cell.get_text(" ", strip=True) for cell in cells]
            if not values:
                continue

            normalized = [cls._normalize_header(value) for value in values]
            if not headers and cls._looks_like_header(normalized):
                headers = normalized
                continue

            if headers:
                # Ignore malformed/placeholder rows rather than shifting cells.
                if len(values) < len(headers):
                    continue
                result.append(dict(zip(headers, values)))
            else:
                result.append({str(index): value for index, value in enumerate(values)})
        return result

    @staticmethod
    def _looks_like_header(values: list[str]) -> bool:
        known = set().union(*_ALIASES.values())
        return "channel" in values and any(value in known for value in values[1:])

    @staticmethod
    def _get(row: dict[str, str], field: str, default: str = "") -> str:
        for alias in _ALIASES[field]:
            if alias in row:
                return row[alias]
        return default

    @classmethod
    def _is_locked(cls, row: dict[str, str]) -> bool:
        status = cls._get(row, "lock")
        if not status and "1" in row:
            status = row["1"]
        return status.strip().lower() == "locked"

    @classmethod
    def _channel_id(cls, row: dict[str, str]) -> int | None:
        value = cls._get(row, "channel_id")
        if not value:
            value = cls._get(row, "channel") or row.get("0", "")
        return cls._parse_int(value)

    @classmethod
    def _parse_downstream_tag_values(cls, raw: str) -> list[RawChannel]:
        """Parse seven-field DOCSIS 3.0 downstream JavaScript rows."""
        rows = cls._split_tag_value_rows(raw)
        if rows is None:
            return []

        result: list[RawChannel] = []
        for row in rows:
            if row[1].strip().lower() != "locked":
                continue

            channel_id = cls._parse_int(row[3])
            if channel_id is None:
                continue
            snr = cls._parse_float(row[6])
            modulation = normalize_modulation(row[2])
            channel: RawChannel = {
                "channelID": channel_id,
                "frequency": hz_to_mhz(row[4]),
                "powerLevel": cls._parse_float(row[5]),
                "mer": snr,
                "mse": -snr if snr is not None else None,
                "modulation": modulation,
                "corrErrors": None,
                "nonCorrErrors": None,
            }
            symbol_rate = _ANNEX_B_DOWNSTREAM_SYMBOL_RATES.get(modulation)
            if symbol_rate is not None:
                channel["symbolRate"] = symbol_rate
            result.append(channel)
        return result

    @classmethod
    def _parse_upstream_tag_values(cls, raw: str) -> list[RawChannel]:
        """Parse seven-field DOCSIS 3.0 upstream JavaScript rows."""
        rows = cls._split_tag_value_rows(raw)
        if rows is None:
            return []

        result: list[RawChannel] = []
        for row in rows:
            if row[1].strip().lower() != "locked":
                continue

            channel_id = cls._parse_int(row[3])
            if channel_id is None:
                continue
            modulation = normalize_modulation(row[2])
            channel: RawChannel = {
                "channelID": channel_id,
                "frequency": hz_to_mhz(row[5]),
                "powerLevel": cls._parse_float(row[6]),
                "modulation": modulation,
                "multiplex": modulation,
            }
            symbol_rate = cls._parse_int(row[4])
            if symbol_rate is not None:
                channel["symbolRate"] = symbol_rate
            result.append(channel)
        return result

    @staticmethod
    def _extract_function_body(html: str, function_name: str) -> str | None:
        """Return the body of a named no-argument JavaScript function."""
        for match in _FUNCTION_START_RE.finditer(html):
            if match.group("name") != function_name:
                continue

            body_start = match.end()
            depth = 1
            index = body_start
            while index < len(html) and depth:
                if html[index] == "{":
                    depth += 1
                elif html[index] == "}":
                    depth -= 1
                index += 1

            if depth == 0:
                return html[body_start : index - 1]
            return None
        return None

    @staticmethod
    def _strip_javascript_comments(source: str) -> str:
        """Remove JavaScript comments while preserving quoted string contents."""
        result: list[str] = []
        index = 0
        quote: str | None = None

        while index < len(source):
            char = source[index]
            if quote is not None:
                result.append(char)
                if char == "\\" and index + 1 < len(source):
                    index += 1
                    result.append(source[index])
                elif char == quote:
                    quote = None
                index += 1
                continue

            if char in {"'", '"'}:
                quote = char
                result.append(char)
                index += 1
                continue

            if source.startswith("//", index):
                newline = source.find("\n", index + 2)
                if newline == -1:
                    break
                result.append("\n")
                index = newline + 1
                continue

            if source.startswith("/*", index):
                comment_end = source.find("*/", index + 2)
                if comment_end == -1:
                    break
                result.append(" ")
                index = comment_end + 2
                continue

            result.append(char)
            index += 1

        return "".join(result)

    @classmethod
    def _extract_tag_value_list(cls, html: str, function_name: str) -> str | None:
        """Extract the live, possibly concatenated tagValueList assignment."""
        body = cls._extract_function_body(html, function_name)
        if body is None:
            return None

        body = cls._strip_javascript_comments(body)
        assignment = _TAG_VALUE_ASSIGNMENT_RE.search(body)
        if assignment is None:
            return None

        literals: list[str] = []
        for match in _STRING_LITERAL_RE.finditer(assignment.group("value")):
            value = match.group("single")
            if value is None:
                value = match.group("double")
            literals.append(
                value.replace(r"\'", "'")
                .replace(r'\"', '"')
                .replace(r"\\", "\\")
            )
        if not literals:
            return None

        payload = "".join(literals)
        return payload if cls._split_tag_value_rows(payload) is not None else None

    @staticmethod
    def _split_tag_value_rows(raw: str) -> list[list[str]] | None:
        """Validate and split a leading-count tagValueList into seven-field rows."""
        parts = raw.split("|")
        count_prefix = parts[0].strip()
        if not count_prefix.isdecimal():
            return None

        row_count = int(count_prefix)
        values = parts[1:]
        if values and not values[-1]:
            values.pop()
        if len(values) != row_count * _TAG_VALUE_FIELDS_PER_ROW:
            return None

        return [
            values[index : index + _TAG_VALUE_FIELDS_PER_ROW]
            for index in range(0, len(values), _TAG_VALUE_FIELDS_PER_ROW)
        ]

    @classmethod
    def _parse_downstream_table(
        cls, soup: BeautifulSoup, table_id: str, *, docsis31: bool
    ) -> list[RawChannel]:
        result: list[RawChannel] = []
        for row in cls._table_rows(soup, table_id):
            if not cls._is_locked(row):
                continue

            positional = not any(key.isalpha() for key in row)
            if positional:
                row = cls._map_downstream_positional(row)

            channel_id = cls._channel_id(row)
            if channel_id is None:
                continue
            frequency = cls._get(row, "frequency")
            power = cls._parse_float(cls._get(row, "power"))
            snr = cls._parse_float(cls._get(row, "snr"))
            modulation_raw = cls._get(row, "modulation")
            corr = cls._parse_int(cls._get(row, "corr"))
            uncorr = cls._parse_int(cls._get(row, "uncorr"))

            if docsis31:
                channel: RawChannel = {
                    "channelID": channel_id,
                    "type": "OFDM",
                    "frequency": hz_to_mhz(frequency),
                    "powerLevel": power,
                    "mer": snr,
                    "mse": None,
                    "modulation": "OFDM",
                    "corrErrors": corr,
                    "nonCorrErrors": uncorr,
                }
            else:
                modulation = normalize_modulation(modulation_raw)
                channel = {
                    "channelID": channel_id,
                    "frequency": hz_to_mhz(frequency),
                    "powerLevel": power,
                    "mer": snr,
                    "mse": -snr if snr is not None else None,
                    "modulation": modulation,
                    "corrErrors": corr,
                    "nonCorrErrors": uncorr,
                }
                symbol_rate = _ANNEX_B_DOWNSTREAM_SYMBOL_RATES.get(modulation)
                if symbol_rate is not None:
                    channel["symbolRate"] = symbol_rate
            result.append(channel)
        return result

    @classmethod
    def _parse_upstream_table(
        cls, soup: BeautifulSoup, table_id: str, *, docsis31: bool
    ) -> list[RawChannel]:
        result: list[RawChannel] = []
        for row in cls._table_rows(soup, table_id):
            if not cls._is_locked(row):
                continue

            positional = not any(key.isalpha() for key in row)
            if positional:
                row = cls._map_upstream_positional(row)

            channel_id = cls._channel_id(row)
            if channel_id is None:
                continue
            frequency = cls._get(row, "frequency")
            power = cls._parse_float(cls._get(row, "power"))
            modulation_raw = cls._get(row, "modulation")
            modulation = normalize_modulation(modulation_raw)

            if docsis31:
                channel: RawChannel = {
                    "channelID": channel_id,
                    "type": "OFDMA",
                    "frequency": hz_to_mhz(frequency),
                    "powerLevel": power,
                    "modulation": "OFDMA",
                    "multiplex": "",
                }
            else:
                channel = {
                    "channelID": channel_id,
                    "frequency": hz_to_mhz(frequency),
                    "powerLevel": power,
                    "modulation": modulation,
                    "multiplex": modulation,
                }
                symbol_rate = cls._parse_int(cls._get(row, "symbol_rate"))
                if symbol_rate is not None:
                    channel["symbolRate"] = symbol_rate
            result.append(channel)
        return result

    @classmethod
    def _map_downstream_positional(cls, row: dict[str, str]) -> dict[str, str]:
        values = [row[str(index)] for index in range(len(row))]
        if len(values) < 9:
            return row
        mapped = {
            "channel": values[0],
            "lockstatus": values[1],
            "modulation": values[2],
            "channelid": values[3],
            "frequency": values[4],
            "power": values[5],
            "snr": values[6],
        }
        # Ten/eleven-column layouts include Unerrored before Correctables.
        if len(values) >= 10:
            mapped["correctables"] = values[-2]
            mapped["uncorrectables"] = values[-1]
        else:
            mapped["correctables"] = values[7]
            mapped["uncorrectables"] = values[8]
        return mapped

    @staticmethod
    def _map_upstream_positional(row: dict[str, str]) -> dict[str, str]:
        values = [row[str(index)] for index in range(len(row))]
        if len(values) < 6:
            return row
        mapped = {
            "channel": values[0],
            "lockstatus": values[1],
            "modulation": values[2],
            "channelid": values[3],
        }
        if len(values) >= 7:
            mapped["symbolrate"] = values[4]
            mapped["frequency"] = values[5]
            mapped["power"] = values[6]
        else:
            mapped["frequency"] = values[4]
            mapped["power"] = values[5]
        return mapped

    @staticmethod
    def _parse_float(value: str) -> float | None:
        if not value:
            return None
        match = _NUMBER_RE.search(value.replace(",", ""))
        return float(match.group(0)) if match else None

    @classmethod
    def _parse_int(cls, value: str) -> int | None:
        number = cls._parse_float(value)
        return int(number) if number is not None else None
