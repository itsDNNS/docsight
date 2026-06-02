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

import logging
import math
from typing import Any

import requests

from ..types import ConnectionInfo, DeviceInfo, DocsisData, RawChannel
from .base import ModemDriver
from .utils import hz_to_mhz, normalize_modulation

log = logging.getLogger("docsis.driver.sercom_dm1000")

_AUTH_STATUSES = {401, 403}
_HTML_ACCEPT = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"


class SercomDM1000Driver(ModemDriver):
    """Driver for authenticated Sercom DM1000 cable modem UIs."""

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url.rstrip("/"), user, password)
        self._session = requests.Session()
        self._session.headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": f"{self._url}/status.html",
        })

    def login(self) -> None:
        """Authenticate with the Sercom form and verify a protected endpoint."""
        payload = {
            "login_user": self._user,
            # The captured login form sends both names with the same password
            # value; firmware variants may read either field. Keep both until
            # a live modem confirms which field this firmware validates.
            "pws": self._password,
            "submit": "Apply",
            "is_parent_window": "1",
            "todo": "login",
            "this_file": "login.html",
            "next_file": "",
            "language": "en",
            "message": "",
            "passwd": self._password,
            "cur_passwd": "",
        }
        try:
            resp = self._session.post(
                f"{self._url}/setup.cgi",
                data=payload,
                headers={
                    "Accept": _HTML_ACCEPT,
                    "Origin": self._url,
                    "Referer": f"{self._url}/login.html",
                    # Override the session-level XHR header for the form POST;
                    # requests omits headers set to None when preparing the call.
                    "X-Requested-With": None,
                },
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Sercom DM1000 login failed: {exc}") from exc

        # The captured browser flow performs a normal page navigation after the
        # form post before the RF JSON XHRs run. Some firmware builds only make
        # the authenticated RF endpoints return JSON after this status page load.
        self._load_status_page()

        # A Sercom login can return 200 + HTML even when authentication failed.
        # Probe a protected JSON endpoint before reporting success.
        self._fetch_payload("RF_DS_param", raise_on_error=True, allow_reauth=False)
        log.info("Sercom DM1000 login OK")

    def _load_status_page(self) -> None:
        try:
            resp = self._session.get(
                f"{self._url}/status.html",
                headers={
                    "Accept": _HTML_ACCEPT,
                    # The HAR records status.html as a normal navigation from
                    # setup.cgi, not as an XHR. Preserve that shape before the
                    # first protected RF JSON probe.
                    "Referer": f"{self._url}/setup.cgi",
                    "X-Requested-With": None,
                },
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
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
    ) -> dict[str, Any]:
        """Fetch a ``/setup.cgi?todo=...`` JSON object with one reauth retry."""
        try:
            resp = self._session.get(f"{self._url}/setup.cgi", params={"todo": todo}, timeout=30)
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
            if raise_on_error:
                raise RuntimeError(f"Sercom DM1000 fetch {todo} failed: {exc}") from exc
            log.warning("Sercom DM1000 fetch %s failed: %s", todo, exc)
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
    def _looks_like_html(resp: requests.Response) -> bool:
        content_type = str(resp.headers.get("Content-Type", "")).lower()
        text = str(getattr(resp, "text", "") or "").lstrip().lower()
        return "text/html" in content_type or text.startswith(("<html", "<!doctype html"))

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
