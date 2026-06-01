"""Authenticated Hitron CODA-4680 modem driver for DOCSight.

The CODA-4680 web UI uses Backbone endpoints under ``/1/Device/CM`` and
requires a simple form login before DOCSIS data is available.  Unlike the
CODA-56-style Hitron driver, this UI returns object payloads whose channel
lists live under ``Freq_List``, ``OFDMs_List``, and ``OFDMAs_List``.

DOCSIS Event pages are intentionally not collected here. DOCSight currently
normalizes modem signal data and generates its own analyzer events; it does
not import vendor modem event logs for other drivers either.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from ..types import ConnectionInfo, DeviceInfo, DocsisData, RawChannel
from .base import ModemDriver
from .utils import hz_to_mhz, make_legacy_tls_adapter, normalize_modulation

log = logging.getLogger("docsis.driver.hitron_coda_4680")


class HitronCoda4680Driver(ModemDriver):
    """Driver for authenticated Hitron CODA-4680 modem/router UIs."""

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url.rstrip("/"), user, password)
        self._session = requests.Session()
        self._session.verify = False
        self._session.headers.update({
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": f"{self._url}/webpages/index.html",
        })
        self._session.mount("https://", make_legacy_tls_adapter(sec_level=1))
        self._device_info_cache: DeviceInfo | None = None

    def login(self) -> None:
        """Authenticate with the CODA-4680 web UI."""
        payload = {
            "model": json.dumps({"username": self._user, "password": self._password}),
        }
        try:
            resp = self._session.post(
                f"{self._url}/1/Device/Users/Login",
                data=payload,
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise RuntimeError(f"Hitron CODA-4680 login failed: {exc}") from exc

        body = self._json_body(resp)
        if body is not None:
            if not isinstance(body, dict):
                raise RuntimeError("Hitron CODA-4680 login returned invalid JSON payload")
            self._ensure_ok(body, "login")

        # The login response can be an empty 200. Verify that the authenticated
        # session can read a protected endpoint before reporting success.
        self._device_info_cache = self._parse_device_info(
            self._fetch_payload("/1/Device/CM/Version", raise_on_error=True, allow_reauth=False)
        )
        log.info("Hitron CODA-4680 login OK")

    def get_docsis_data(self) -> DocsisData:
        """Retrieve DOCSIS channel data from the CODA-4680 CM endpoints."""
        ds_info = self._fetch_payload("/1/Device/CM/DsInfo")
        us_info = self._fetch_payload("/1/Device/CM/UsInfo")
        ds_ofdm = self._fetch_payload("/1/Device/CM/DsOfdm")
        us_ofdma = self._fetch_payload("/1/Device/CM/UsOfdm")

        return {
            "channelDs": {
                "docsis30": self._parse_ds_scqam(ds_info.get("Freq_List", [])),
                "docsis31": self._parse_ds_ofdm(ds_ofdm.get("OFDMs_List", [])),
            },
            "channelUs": {
                "docsis30": self._parse_us_scqam(us_info.get("Freq_List", [])),
                "docsis31": self._parse_us_ofdma(us_ofdma.get("OFDMAs_List", [])),
            },
        }

    def get_device_info(self) -> DeviceInfo:
        """Retrieve model and firmware from the version endpoint."""
        if self._device_info_cache is not None:
            return self._device_info_cache
        self._device_info_cache = self._parse_device_info(self._fetch_payload("/1/Device/CM/Version"))
        return self._device_info_cache

    def get_connection_info(self) -> ConnectionInfo:
        """Retrieve basic DOCSIS WAN state from SysInfo."""
        payload = self._fetch_payload("/1/Device/CM/SysInfo")
        if not payload:
            return {}
        ip_values = payload.get("ip")
        wan_ip = ""
        if isinstance(ip_values, list) and ip_values:
            wan_ip = str(ip_values[0])
        return {
            "connection_type": "DOCSIS",
            "status": str(payload.get("ntAccess") or ""),
            "wan_ip": wan_ip,
            "max_downstream_kbps": self._parse_rate_kbps(payload.get("DsDataRate")),
            "max_upstream_kbps": self._parse_rate_kbps(payload.get("UsDataRate")),
        }

    def _fetch_payload(
        self,
        path: str,
        *,
        raise_on_error: bool = False,
        allow_reauth: bool = True,
    ) -> dict[str, Any]:
        """Fetch and validate a JSON object endpoint."""
        try:
            resp = self._session.get(
                f"{self._url}{path}?_={self._cache_bust()}",
                timeout=30,
            )
            resp.raise_for_status()
            payload = self._json_body(resp)
        except requests.HTTPError as exc:
            if allow_reauth and self._is_auth_error(exc):
                log.info("Hitron CODA-4680 session expired while fetching %s; retrying after login", path)
                return self._retry_after_reauth(path, raise_on_error=raise_on_error)
            if raise_on_error:
                raise RuntimeError(f"Hitron CODA-4680 fetch {path} failed: {exc}") from exc
            log.warning("Hitron CODA-4680 fetch %s failed: %s", path, exc)
            return {}
        except requests.RequestException as exc:
            if raise_on_error:
                raise RuntimeError(f"Hitron CODA-4680 fetch {path} failed: {exc}") from exc
            log.warning("Hitron CODA-4680 fetch %s failed: %s", path, exc)
            return {}

        if not isinstance(payload, dict):
            if raise_on_error:
                raise RuntimeError(f"Hitron CODA-4680 fetch {path} returned invalid JSON payload")
            log.warning("Hitron CODA-4680 fetch %s returned non-object payload", path)
            return {}
        if allow_reauth and self._is_auth_payload(payload):
            log.info("Hitron CODA-4680 endpoint %s returned an auth error; retrying after login", path)
            return self._retry_after_reauth(path, raise_on_error=raise_on_error)
        if not self._ensure_ok(payload, path, raise_on_error=raise_on_error):
            return {}
        return payload

    def _retry_after_reauth(self, path: str, *, raise_on_error: bool) -> dict[str, Any]:
        try:
            self.login()
        except RuntimeError as exc:
            if raise_on_error:
                raise RuntimeError(f"Hitron CODA-4680 re-login before fetching {path} failed: {exc}") from exc
            log.warning("Hitron CODA-4680 re-login before fetching %s failed: %s", path, exc)
            return {}
        return self._fetch_payload(path, raise_on_error=raise_on_error, allow_reauth=False)

    @staticmethod
    def _is_auth_error(exc: requests.HTTPError) -> bool:
        response = getattr(exc, "response", None)
        return getattr(response, "status_code", None) in {401, 403}

    @staticmethod
    def _is_auth_payload(payload: Any) -> bool:
        return isinstance(payload, dict) and str(payload.get("errCode", "")) in {"401", "403"}

    @staticmethod
    def _json_body(resp: requests.Response) -> Any:
        try:
            return resp.json()
        except ValueError:
            return None

    @staticmethod
    def _ensure_ok(payload: dict[str, Any], context: str, *, raise_on_error: bool = True) -> bool:
        code = str(payload.get("errCode", "000"))
        if code == "000":
            return True
        message = str(payload.get("errMsg") or f"errCode {code}")
        if raise_on_error:
            raise RuntimeError(f"Hitron CODA-4680 {context} failed: {message}")
        log.warning("Hitron CODA-4680 %s failed: %s", context, message)
        return False

    @staticmethod
    def _parse_device_info(payload: dict[str, Any]) -> DeviceInfo:
        return {
            "manufacturer": str(payload.get("vendorName") or "Hitron Technologies"),
            "model": str(payload.get("ModelReport") or payload.get("modelName") or "CODA-4680"),
            "sw_version": str(payload.get("SoftwareVersion") or ""),
        }

    def _parse_ds_scqam(self, rows: list[dict[str, Any]]) -> list[RawChannel]:
        channels: list[RawChannel] = []
        for row in rows:
            try:
                snr = float(row["snr"])
                channels.append({
                    "channelID": int(row["channelId"]),
                    "frequency": hz_to_mhz(row["frequency"]),
                    "powerLevel": float(row["signalStrength"]),
                    "modulation": normalize_modulation(row.get("modulation", "")),
                    "mer": snr,
                    "mse": -snr,
                    "corrErrors": int(row["correcteds"]),
                    "nonCorrErrors": int(row["uncorrect"]),
                })
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Failed to parse Hitron CODA-4680 DS row: %s", exc)
        return channels

    def _parse_us_scqam(self, rows: list[dict[str, Any]]) -> list[RawChannel]:
        channels: list[RawChannel] = []
        for row in rows:
            try:
                modulation = normalize_modulation(row.get("modulationType") or row.get("modtype") or "")
                channel: RawChannel = {
                    "channelID": int(row["channelId"]),
                    "frequency": hz_to_mhz(row["frequency"]),
                    "powerLevel": float(row["signalStrength"]),
                    "modulation": modulation,
                    # CODA-4680 does not expose scdmaMode in the captured API;
                    # ATDMA is the SC-QAM upstream lane DOCSight should score.
                    "multiplex": "ATDMA",
                }
                symbol_rate = row.get("symbolrate")
                if symbol_rate is not None:
                    channel["symbolRate"] = int(symbol_rate)
                channels.append(channel)
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Failed to parse Hitron CODA-4680 US row: %s", exc)
        return channels

    def _parse_ds_ofdm(self, rows: list[dict[str, Any]]) -> list[RawChannel]:
        channels: list[RawChannel] = []
        for row in rows:
            try:
                if str(row.get("plclock", "")).strip().upper() != "YES":
                    continue
                channels.append({
                    "channelID": int(row["receive"]),
                    "type": "OFDM",
                    "frequency": hz_to_mhz(row.get("Subcarr0freqFreq", "")),
                    "powerLevel": float(row["plcpower"]),
                    "modulation": "OFDM",
                    "mer": None,
                    "mse": None,
                    "corrErrors": None,
                    "nonCorrErrors": None,
                })
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Failed to parse Hitron CODA-4680 DS OFDM row: %s", exc)
        return channels

    def _parse_us_ofdma(self, rows: list[dict[str, Any]]) -> list[RawChannel]:
        channels: list[RawChannel] = []
        for row in rows:
            try:
                if str(row.get("state", "")).strip().upper() != "OPERATE":
                    continue
                channels.append({
                    "channelID": int(row["uschindex"]),
                    "type": "OFDMA",
                    # The captured CODA-4680 OFDMA API does not expose center
                    # frequency. Preserve unsupported as blank instead of 0 MHz.
                    "frequency": "",
                    "powerLevel": float(row["repPower"]),
                    "modulation": "OFDMA",
                    "multiplex": "OFDMA",
                })
            except (KeyError, TypeError, ValueError) as exc:
                log.warning("Failed to parse Hitron CODA-4680 US OFDMA row: %s", exc)
        return channels

    @staticmethod
    def _parse_rate_kbps(value: Any) -> int:
        try:
            return int(value or 0)
        except (TypeError, ValueError):
            return 0

    @staticmethod
    def _cache_bust() -> str:
        return str(int(time.time() * 1000))
