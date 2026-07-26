"""Sagemcom F3896LG driver (Liberty Global firmware: Virgin Media Hub 5, Ziggo).

The F@st 3896 ships with (at least) two incompatible firmware families:

* Tele2/Com Hem ("Wi-Fi Hub C3/C4"): Sagemcom XMO JSON-RPC at /cgi/json-req
  with SHA-512 digest login -- handled by app.drivers.sagemcom (issue #163).
* Liberty Global (Virgin Media Hub 5 "F3896LG-VMB", Ziggo, etc.): a read-only
  REST API at /rest/v1/ that requires NO authentication for cable-modem
  status. The community client github.com/ties/sagemcom-f3896-py documents
  the same API. /cgi/json-req does not exist on this firmware (404).

Endpoints used (unauthenticated GETs against the modem management IP,
usually https://192.168.100.1 -- self-signed certificate):

    /rest/v1/cablemodem/downstream    channels: sc_qam + ofdm
    /rest/v1/cablemodem/upstream      channels: atdma + ofdma
    /rest/v1/cablemodem/state_        docsisVersion/uptime/status
    /rest/v1/cablemodem/serviceflows  provisioned max rates
    /rest/v1/cablemodem/registration  used as the connectivity/login check

Firmware quirk: OFDM/OFDMA channel `power` is reported scaled x10
(380 == 38.0 dBmV, -118 == -11.8 dBmV). SC-QAM/ATDMA power is not scaled.
Verified against a Virgin Media (UK) Hub 5 in modem mode.
"""

from __future__ import annotations

import logging

import requests
import urllib3

from .base import ModemDriver
from ..types import ConnectionInfo, DeviceInfo, DocsisData, RawChannel

log = logging.getLogger("docsis.driver.f3896lg")

_TIMEOUT = 10


class F3896LGDriver(ModemDriver):
    """Virgin Media Hub 5 / Sagemcom F3896LG (Liberty Global REST API)."""

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url.rstrip("/"), user, password)
        self._session = requests.Session()
        self._session.verify = False  # self-signed cert on the modem
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

    # -- transport --

    def _get(self, path: str) -> dict:
        r = self._session.get(f"{self._url}/rest/v1/{path}", timeout=_TIMEOUT)
        r.raise_for_status()
        return r.json()

    # -- ModemDriver interface --

    def login(self) -> None:
        """No auth needed; verify the REST API answers so setup test is real."""
        try:
            data = self._get("cablemodem/registration")
        except requests.RequestException as e:
            raise RuntimeError(f"F3896LG REST API not reachable: {e}") from e
        if "registration" not in data:
            raise RuntimeError("F3896LG REST API returned unexpected payload")

    def get_docsis_data(self) -> DocsisData:
        ds = self._get("cablemodem/downstream").get("downstream", {}).get("channels", [])
        us = self._get("cablemodem/upstream").get("upstream", {}).get("channels", [])

        ds30, ds31 = self._parse_downstream(ds)
        us30, us31 = self._parse_upstream(us)
        return {
            "channelDs": {"docsis30": ds30, "docsis31": ds31},
            "channelUs": {"docsis30": us30, "docsis31": us31},
        }

    def get_device_info(self) -> DeviceInfo:
        info: DeviceInfo = {
            "manufacturer": "Sagemcom",
            "model": "F3896LG (Virgin Media Hub 5)",
        }
        try:
            cm = self._get("cablemodem/state_").get("cablemodem", {})
            info["sw_version"] = f"DOCSIS {cm.get('docsisVersion', '?')}"
            if cm.get("status"):
                info["docsis_status"] = str(cm["status"])
            if cm.get("upTime") is not None:
                info["uptime_seconds"] = int(cm["upTime"])
        except (requests.RequestException, ValueError, TypeError) as e:
            log.warning("F3896LG device info fetch failed: %s", e)
        return info

    def get_connection_info(self) -> ConnectionInfo:
        out: ConnectionInfo = {}
        try:
            flows = self._get("cablemodem/serviceflows").get("serviceFlows", [])
            for entry in flows:
                flow = entry.get("serviceFlow", {})
                rate = flow.get("maxTrafficRate")
                if not rate:
                    continue
                if flow.get("direction") == "downstream":
                    out["max_downstream_kbps"] = int(rate) // 1000
                elif flow.get("direction") == "upstream":
                    out["max_upstream_kbps"] = int(rate) // 1000
            out["connection_type"] = "DOCSIS 3.1"
        except (requests.RequestException, ValueError, TypeError) as e:
            log.warning("F3896LG connection info fetch failed: %s", e)
        return out

    # -- parsing --

    def _parse_downstream(self, channels: list[dict]) -> tuple[list[RawChannel], list[RawChannel]]:
        ds30: list[RawChannel] = []
        ds31: list[RawChannel] = []
        for ch in channels:
            if not ch.get("lockStatus", False):
                continue
            try:
                mer = ch.get("rxMer")
                if ch.get("channelType") == "ofdm":
                    ds31.append({
                        "channelID": ch.get("channelId", 0),
                        "type": "OFDM",
                        "frequency": self._hz_to_mhz(ch.get("frequency")),
                        "powerLevel": self._unscale(ch.get("power")),
                        "mer": mer if mer else None,
                        "mse": None,
                        "corrErrors": ch.get("correctedErrors"),
                        "nonCorrErrors": ch.get("uncorrectedErrors"),
                    })
                else:
                    snr = ch.get("snr") or mer
                    ds30.append({
                        "channelID": ch.get("channelId", 0),
                        "frequency": self._hz_to_mhz(ch.get("frequency")),
                        "powerLevel": ch.get("power"),
                        "mer": snr,
                        "mse": -snr if snr else None,
                        "modulation": self._modulation(ch.get("modulation", "")),
                        "corrErrors": ch.get("correctedErrors"),
                        "nonCorrErrors": ch.get("uncorrectedErrors"),
                    })
            except (ValueError, TypeError) as e:
                log.warning("Failed to parse F3896LG DS channel %s: %s", ch, e)
        return ds30, ds31

    def _parse_upstream(self, channels: list[dict]) -> tuple[list[RawChannel], list[RawChannel]]:
        us30: list[RawChannel] = []
        us31: list[RawChannel] = []
        for ch in channels:
            if not ch.get("lockStatus", False):
                continue
            try:
                if ch.get("channelType") == "ofdma":
                    us31.append({
                        "channelID": ch.get("channelId", 0),
                        "type": "OFDMA",
                        "frequency": self._hz_to_mhz(ch.get("frequency")),
                        "powerLevel": self._unscale(ch.get("power")),
                        "modulation": "OFDMA",
                        "multiplex": "",
                    })
                else:
                    us30.append({
                        "channelID": ch.get("channelId", 0),
                        "frequency": self._hz_to_mhz(ch.get("frequency")),
                        "powerLevel": ch.get("power"),
                        "modulation": self._modulation(ch.get("modulation", "")),
                        "multiplex": str(ch.get("channelType", "")).upper(),
                        "symbolRate": ch.get("symbolRate"),
                    })
            except (ValueError, TypeError) as e:
                log.warning("Failed to parse F3896LG US channel %s: %s", ch, e)
        return us30, us31

    # -- helpers --

    @staticmethod
    def _hz_to_mhz(freq_hz) -> str:
        if not freq_hz:
            return ""
        return f"{float(freq_hz) / 1_000_000:g} MHz"

    @staticmethod
    def _unscale(power) -> float | None:
        """OFDM/OFDMA power is reported x10 on this firmware."""
        if power is None:
            return None
        return float(power) / 10.0

    @staticmethod
    def _modulation(raw: str) -> str:
        """qam_256 -> 256QAM (matches other drivers' display convention)."""
        raw = (raw or "").lower()
        if raw.startswith("qam_"):
            return f"{raw[4:]}QAM"
        return raw.upper()
