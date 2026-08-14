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
                                        (docsisVersion is not firmware)
    /rest/v1/cablemodem/serviceflows  provisioned max rates
    /rest/v1/cablemodem/registration  used as the connectivity/login check

Firmware quirk: OFDM/OFDMA channel `power` and OFDM `rxMer` are reported
scaled x10 (380 == 38.0 dBmV, -118 == -11.8 dBmV, 390 == 39.0 dB).
SC-QAM/ATDMA values are not scaled.
This API does not expose a firmware/software version.
Verified against a Virgin Media (UK) Hub 5 in modem mode.
"""

from __future__ import annotations

import logging

import requests

from ..types import ConnectionInfo, DeviceInfo, DocsisData, RawChannel
from .base import ModemDriver
from .formats.sagemcom import parse_f3896lg_downstream, parse_f3896lg_upstream
from .format_compat import unwrap_f3896lg

log = logging.getLogger("docsis.driver.f3896lg")

_TIMEOUT = 10


class F3896LGDriver(ModemDriver):
    """Virgin Media Hub 5 / Sagemcom F3896LG (Liberty Global REST API)."""

    FORMAT_FAMILIES = ("f3896lg_rest_json",)

    def __init__(self, url: str, user: str, password: str):
        super().__init__(url.rstrip("/"), user, password)
        self._session = requests.Session()
        self._session.verify = False  # self-signed cert on the modem

    # -- transport --

    def _get(self, path: str) -> dict:
        r = self._session.get(f"{self._url}/rest/v1/{path}", timeout=_TIMEOUT)
        r.raise_for_status()
        payload = r.json()
        if not isinstance(payload, dict):
            raise RuntimeError("F3896LG REST API returned a non-object JSON payload")
        return payload

    def _get_channels(self, path: str, section_name: str) -> list[dict]:
        payload = self._get(path)
        section = payload.get(section_name)
        if not isinstance(section, dict):
            raise RuntimeError(f"F3896LG REST API returned invalid {section_name} payload")
        channels = section.get("channels")
        if not isinstance(channels, list):
            raise RuntimeError(f"F3896LG REST API returned invalid {section_name} channels")
        return channels

    # -- ModemDriver interface --

    def login(self) -> None:
        """No auth needed; verify the REST API answers so setup test is real."""
        try:
            data = self._get("cablemodem/registration")
        except requests.RequestException as e:
            raise RuntimeError(f"F3896LG REST API not reachable: {e}") from e
        if not isinstance(data.get("registration"), dict):
            raise RuntimeError("F3896LG REST API returned unexpected registration payload")

    def get_docsis_data(self) -> DocsisData:
        ds = self._get_channels("cablemodem/downstream", "downstream")
        us = self._get_channels("cablemodem/upstream", "upstream")

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
            if cm.get("status"):
                info["docsis_status"] = str(cm["status"])
            if cm.get("upTime") is not None:
                info["uptime_seconds"] = int(cm["upTime"])
        except (requests.RequestException, RuntimeError, ValueError, TypeError) as e:
            log.warning("F3896LG device info fetch failed: %s", e)
        return info

    def get_connection_info(self) -> ConnectionInfo:
        out: ConnectionInfo = {"connection_type": "DOCSIS 3.1"}
        max_rates: dict[str, int] = {}
        try:
            flows = self._get("cablemodem/serviceflows").get("serviceFlows", [])
            for entry in flows:
                if not isinstance(entry, dict):
                    continue
                flow = entry.get("serviceFlow", {})
                if not isinstance(flow, dict):
                    continue
                try:
                    rate = int(flow.get("maxTrafficRate"))
                except (TypeError, ValueError):
                    continue
                if rate <= 0:
                    continue
                direction = flow.get("direction")
                if direction == "downstream":
                    key = "max_downstream_kbps"
                elif direction == "upstream":
                    key = "max_upstream_kbps"
                else:
                    continue
                max_rates[key] = max(max_rates.get(key, 0), rate)
            if "max_downstream_kbps" in max_rates:
                out["max_downstream_kbps"] = max_rates["max_downstream_kbps"] // 1000
            if "max_upstream_kbps" in max_rates:
                out["max_upstream_kbps"] = max_rates["max_upstream_kbps"] // 1000
        except (requests.RequestException, RuntimeError, ValueError, TypeError) as e:
            log.warning("F3896LG connection info fetch failed: %s", e)
        return out

    # Compatibility parser seams.

    def _parse_downstream(self, channels: list[dict]) -> tuple[list[RawChannel], list[RawChannel]]:
        return unwrap_f3896lg(parse_f3896lg_downstream(channels), channels, "downstream", log)

    def _parse_upstream(self, channels: list[dict]) -> tuple[list[RawChannel], list[RawChannel]]:
        return unwrap_f3896lg(parse_f3896lg_upstream(channels), channels, "upstream", log)
