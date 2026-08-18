"""Network-free characterization cases for built-in modem parser formats.

This module deliberately lives under ``tests/``: it invokes the parser seams
that exist on the source baseline and is also imported by the maintainer golden
matrix script.  Raw samples are either captured fixtures already used by the
suite or minimal malformed/empty variants around fields in those fixtures.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
import json
import logging
from pathlib import Path
from typing import Any, Callable, Iterator
from unittest.mock import patch

from bs4 import BeautifulSoup

from app.drivers.arris_html import parse_arris_channel_tables
from app.drivers.cgm4981 import CGM4981Driver
from app.drivers.ch7465 import CH7465Driver, Query
from app.drivers.cm1000 import CM1000Driver
from app.drivers.cm3000 import CM3000Driver
from app.drivers.cm3500 import CM3500Driver
from app.drivers.f3896lg import F3896LGDriver
from app.drivers.fritzbox import FritzBoxDriver
from app.drivers.generic import GenericDriver
from app.drivers.hitron import HitronDriver
from app.drivers.hitron_coda_4680 import HitronCoda4680Driver
from app.drivers.sagemcom import SagemcomDriver
from app.drivers.sb6141 import SB6141Driver
from app.drivers.sb6183 import SB6183Driver
from app.drivers.sb6190 import SB6190Driver
from app.drivers.sb8200_cbn import Query as SB8200Query, SB8200CBNDriver
from app.drivers.sercom_dm1000 import SercomDM1000Driver
from app.drivers.surfboard import SurfboardDriver
from app.drivers.tc4400 import TC4400Driver
from app.drivers.ultrahub7 import UltraHub7Driver
from app.drivers.vodafone_station import VodafoneStationDriver


ROOT = Path(__file__).resolve().parents[2]

EMPTY_SPLIT = {
    "channelDs": {"docsis30": [], "docsis31": []},
    "channelUs": {"docsis30": [], "docsis31": []},
}
EMPTY_FLAT_31 = {"docsis": "3.1", "downstream": [], "upstream": []}


@dataclass(frozen=True)
class CaseObservation:
    """One parser observation, keeping diagnostics out of normalized data."""

    output: Any
    diagnostics: tuple[dict[str, str], ...] = ()


@dataclass(frozen=True)
class DriverFormatCase:
    """A stable case-registry entry."""

    case_id: str
    driver: str
    family: str
    evidence: str
    invoke: Callable[[], Any]
    expected: Any

    def observe(self) -> CaseObservation:
        with _capture_parser_warnings() as warnings:
            try:
                output = self.invoke()
            except Exception as exc:  # Characterize an existing malformed seam.
                return CaseObservation(
                    output=None,
                    diagnostics=tuple(warnings)
                    + ({"kind": "exception", "type": type(exc).__name__, "message": str(exc)},),
                )
        return CaseObservation(output=output, diagnostics=tuple(warnings))


class _WarningCollector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.items: list[dict[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.items.append(
            {"kind": "log", "level": record.levelname, "message": record.getMessage()}
        )


@contextmanager
def _capture_parser_warnings() -> Iterator[list[dict[str, str]]]:
    handler = _WarningCollector()
    root = logging.getLogger()
    old_level = root.level
    root.addHandler(handler)
    if old_level > logging.WARNING:
        root.setLevel(logging.WARNING)
    try:
        yield handler.items
    finally:
        root.removeHandler(handler)
        root.setLevel(old_level)


class _Response:
    def __init__(self, *, payload: Any = None, text: str = "") -> None:
        self._payload = payload
        self.text = text
        self.status_code = 200

    def json(self) -> Any:
        return self._payload

    def raise_for_status(self) -> None:
        return None


def _split(ds30=None, ds31=None, us30=None, us31=None) -> dict[str, Any]:
    return {
        "channelDs": {"docsis30": ds30 or [], "docsis31": ds31 or []},
        "channelUs": {"docsis30": us30 or [], "docsis31": us31 or []},
    }


def _flat(downstream=None, upstream=None) -> dict[str, Any]:
    return {"docsis": "3.1", "downstream": downstream or [], "upstream": upstream or []}


def _fritz(raw: dict[str, Any]) -> Any:
    driver = FritzBoxDriver("http://modem.invalid", "user", "password")
    response = _Response(payload={"data": raw})
    with patch("app.fritzbox.requests.post", return_value=response):
        return driver.get_docsis_data()


def _tc(ds_html: str, us_html: str) -> Any:
    driver = TC4400Driver("http://modem.invalid", "user", "password")
    ds = BeautifulSoup(ds_html, "html.parser").find("table")
    us = BeautifulSoup(us_html, "html.parser").find("table")
    return _flat(driver._parse_downstream(ds), driver._parse_upstream(us))


def _ultrahub(ds: list[dict[str, Any]], us: list[dict[str, Any]]) -> Any:
    driver = UltraHub7Driver("http://modem.invalid", "", "password")
    return _flat(driver._parse_downstream_channels(ds), driver._parse_upstream_channels(us))


def _vodafone_cga(payload: Any) -> Any:
    driver = VodafoneStationDriver("http://modem.invalid", "admin", "password")
    with patch.object(driver, "_cga_request", return_value=_Response(payload={"data": payload})):
        return driver._get_docsis_cga()


def _vodafone_tg(html: str) -> Any:
    driver = VodafoneStationDriver("http://modem.invalid", "admin", "password")
    driver._tg_nonce = "captured-boundary"
    with patch.object(driver, "_tg_docsis_request", return_value=_Response(text=html)):
        return driver._get_docsis_tg()


def _ch7465(ds_xml: str, us_xml: str) -> Any:
    driver = CH7465Driver("http://modem.invalid", "admin", "password")

    def get_data(query: Query) -> str:
        return ds_xml if query is Query.DOWNSTREAM_TABLE else us_xml

    with patch.object(driver, "_get_data", side_effect=get_data):
        return driver.get_docsis_data()


def _sb8200_cbn(ds: str, us: str, ofdm: str, ofdma: str, signal: str) -> Any:
    driver = SB8200CBNDriver("https://modem.invalid", "admin", "password")
    payloads = {
        SB8200Query.DOWNSTREAM_TABLE: ds,
        SB8200Query.UPSTREAM_TABLE: us,
        SB8200Query.DOWNSTREAM_OFDM_TABLE: ofdm,
        SB8200Query.UPSTREAM_OFDMA_TABLE: ofdma,
        SB8200Query.SIGNAL_TABLE: signal,
    }

    # The OFDM, OFDMA, and codeword tables travel the optional path, which
    # degrades to None rather than raising, so both fetchers must be served.
    with (
        patch.object(driver, "_get_data", side_effect=lambda query: payloads[query]),
        patch.object(driver, "_get_optional_data", side_effect=lambda query: payloads[query]),
    ):
        return driver.get_docsis_data()


def _cm3000_html(ds: str, us: str, ds_ofdm: str, us_ofdma: str) -> str:
    return f"""
    <script>
    function InitDsTableTagValue() {{ var tagValueList = '{ds}'; return tagValueList.split('|'); }}
    function InitUsTableTagValue() {{ var tagValueList = '{us}'; return tagValueList.split('|'); }}
    function InitDsOfdmTableTagValue() {{ var tagValueList = '{ds_ofdm}'; return tagValueList.split('|'); }}
    function InitUsOfdmaTableTagValue() {{ var tagValueList = '{us_ofdma}'; return tagValueList.split('|'); }}
    </script>
    """


def _cm3000(html: str) -> Any:
    driver = CM3000Driver("http://modem.invalid", "admin", "password")
    with patch.object(driver, "_fetch_status_page", return_value=html):
        return driver.get_docsis_data()


def _cm1000(html: str) -> Any:
    driver = CM1000Driver("http://modem.invalid", "admin", "password")
    with patch.object(driver, "_fetch_status_page", return_value=html):
        return driver.get_docsis_data()


def _cm3500(html: str) -> Any:
    driver = CM3500Driver("http://modem.invalid", "admin", "password")
    soup = BeautifulSoup(html, "html.parser")
    with patch.object(driver, "_fetch_status_page", return_value=soup):
        return driver.get_docsis_data()


def _surfboard(ds: str, us: str) -> Any:
    driver = SurfboardDriver("https://modem.invalid", "admin", "password")
    ds30, ds31 = driver._parse_downstream(ds)
    us30, us31 = driver._parse_upstream(us)
    return _split(ds30, ds31, us30, us31)


def _first_data_table(html: str, marker: str) -> Any:
    soup = BeautifulSoup(html, "html.parser")
    for table in soup.find_all("table"):
        if marker in table.get_text(" ", strip=True).lower():
            data_rows = [
                row for row in table.find_all("tr")
                if len(row.find_all("td")) >= 7 and not row.find("strong")
            ]
            if len(data_rows) > 1:
                for row in data_rows[1:]:
                    row.extract()
            return table
    return None


def _sb6141(signal_html: str) -> Any:
    driver = SB6141Driver("http://modem.invalid", "", "")
    soup = BeautifulSoup(signal_html, "html.parser")
    tables = soup.find_all("table")
    ds = us = cw = None
    for table in tables:
        th = table.find("th")
        heading = th.get_text(" ", strip=True).lower() if th else ""
        if "downstream" in heading:
            ds = table
        elif "upstream" in heading:
            us = table
        elif "signal status" in heading or "codeword" in heading:
            cw = table
    return _split(driver._parse_downstream(ds, cw), [], driver._parse_upstream(us), [])


def _row_html_driver(driver_cls: type, html: str) -> Any:
    driver = driver_cls("http://modem.invalid", "admin", "password")
    soup = BeautifulSoup(html, "html.parser")
    ds = _first_data_table(str(soup), "downstream bonded")
    us = _first_data_table(str(soup), "upstream bonded")
    return _split(driver._parse_downstream(ds), [], driver._parse_upstream(us), [])


def _hitron(payloads: dict[str, list[dict[str, Any]]]) -> Any:
    driver = HitronDriver("http://modem.invalid", "", "")
    with patch.object(driver, "_fetch_json", side_effect=lambda path: payloads[path]):
        return driver.get_docsis_data()


def _hitron_4680(payloads: dict[str, dict[str, Any]]) -> Any:
    driver = HitronCoda4680Driver("http://modem.invalid", "admin", "password")
    with patch.object(driver, "_fetch_payload", side_effect=lambda path: payloads[path]):
        return driver.get_docsis_data()


def _sagemcom(ds: list[dict[str, Any]], us: list[dict[str, Any]]) -> Any:
    driver = SagemcomDriver("http://modem.invalid", "admin", "password")
    ds30, ds31 = driver._parse_downstream(ds)
    us30, us31 = driver._parse_upstream(us)
    return _split(ds30, ds31, us30, us31)


def _f3896(ds: list[dict[str, Any]], us: list[dict[str, Any]]) -> Any:
    driver = F3896LGDriver("http://modem.invalid", "", "")
    ds30, ds31 = driver._parse_downstream(ds)
    us30, us31 = driver._parse_upstream(us)
    return _split(ds30, ds31, us30, us31)


def _sercom(
    ds: list[dict[str, Any]],
    ds_ofdm: list[dict[str, Any]],
    us: list[dict[str, Any]],
    us_ofdma: list[dict[str, Any]],
) -> Any:
    driver = SercomDM1000Driver("http://modem.invalid", "technician", "password")
    return _split(
        driver._parse_ds_scqam(ds),
        driver._parse_ds_ofdm(ds_ofdm),
        driver._parse_us_scqam(us),
        driver._parse_us_ofdma(us_ofdma),
    )


def _cgm(ds: dict[str, list[str]], us: dict[str, list[str]], errors: dict[str, list[str]]) -> Any:
    driver = CGM4981Driver("http://modem.invalid", "admin", "password")
    downstream = driver._build_ds_channels(ds, errors)
    upstream = driver._build_us_channels(us)
    return _split(
        [channel for channel in downstream if channel.get("modulation") != "OFDM"],
        [channel for channel in downstream if channel.get("modulation") == "OFDM"],
        [channel for channel in upstream if channel.get("modulation") != "OFDMA"],
        [channel for channel in upstream if channel.get("modulation") == "OFDMA"],
    )


# Captured values reused from the existing focused tests, reduced to one row per
# supported lane so the expected structures stay readable.
TC_DS_SUCCESS = """<table><tr><th>Channel ID</th><th>Lock Status</th><th>Channel Type</th><th>Modulation</th><th>Frequency</th><th>Power</th><th>SNR</th><th>Corrected</th><th>Uncorrected</th></tr><tr><td>7</td><td>Locked</td><td>SC-QAM</td><td>256QAM</td><td>591000000 Hz</td><td>4.6 dBmV</td><td>36.4 dB</td><td>3</td><td>30</td></tr><tr><td>193</td><td>Locked</td><td>OFDM</td><td>OFDM</td><td>275600000 Hz</td><td>3.2 dBmV</td><td>38 dB</td><td>9</td><td>1</td></tr></table>"""
TC_US_SUCCESS = """<table><tr><th>Channel ID</th><th>Lock Status</th><th>Modulation</th><th>Frequency</th><th>Power</th></tr><tr><td>6</td><td>Locked</td><td>ATDMA</td><td>25900000 Hz</td><td>35 dBmV</td></tr><tr><td>41</td><td>Locked</td><td>OFDMA</td><td>42000000 Hz</td><td>37.75 dBmV</td></tr></table>"""

TG_SUCCESS = """<script>json_dsData = [{"ChannelID":"7","ChannelType":"SC-QAM","Frequency":"591000000","Modulation":"256QAM","PowerLevel":"-1.2 dBmV/1158.8 dBuV","SNRLevel":"40.0 dB"},{"ChannelID":"193","ChannelType":"OFDM","Frequency":"275600000~472950000","Modulation":"OFDM","PowerLevel":"3.2 dBmV","SNRLevel":"38 dB"}]; json_usData = [{"ChannelID":"6","ChannelType":"SC-QAM","Frequency":"25900000","Modulation":"64QAM","PowerLevel":"35 dBmV"},{"ChannelID":"41","ChannelType":"OFDMA","Frequency":"42000000","Modulation":"","PowerLevel":"37.75 dBmV"}];</script>"""

CM3000_SUCCESS = _cm3000_html(
    "1|1|Locked|QAM256|7|591000000 Hz|-2.5|40.0|1234|5|",
    "1|1|Locked|ATDMA|3|5120 Ksym/sec|29200000 Hz|43.5 dBmV|",
    "1|1|Locked|0 ,1 ,2 ,3|193|690000000 Hz|-0.32 dBmV|41.8 dB|388 ~ 3707|9|1|0|",
    "1|1|Locked|12 ,13|41|36200000 Hz|36.5 dBmV|",
)

CM1000_TABLE_SUCCESS = """
<table id="dsTable"><tr><th>Channel</th><th>Lock Status</th><th>Modulation</th><th>Channel ID</th><th>Frequency</th><th>Power</th><th>SNR</th><th>Correctables</th><th>UnCorrectables</th></tr><tr><td>1</td><td>Locked</td><td>256QAM</td><td>7</td><td>591000000 Hz</td><td>0.0 dBmV</td><td>40 dB</td><td>0</td><td>5</td></tr></table>
<table id="usTable"><tr><th>Channel</th><th>Lock Status</th><th>Modulation</th><th>Channel ID</th><th>Frequency</th><th>Power</th></tr><tr><td>1</td><td>Locked</td><td>ATDMA</td><td>3</td><td>29200000 Hz</td><td>43.5 dBmV</td></tr></table>
<table id="d31dsTable"><tr><th>Channel</th><th>Lock Status</th><th>Modulation</th><th>Channel ID</th><th>Frequency</th><th>Power</th><th>SNR</th><th>Correctables</th><th>UnCorrectables</th></tr><tr><td>1</td><td>Locked</td><td>OFDM</td><td>193</td><td>690000000 Hz</td><td>-0.32 dBmV</td><td>41.8 dB</td><td>9</td><td>1</td></tr></table>
<table id="d31usTable"><tr><th>Channel</th><th>Lock Status</th><th>Modulation</th><th>Channel ID</th><th>Frequency</th><th>Power</th></tr><tr><td>1</td><td>Locked</td><td>OFDMA</td><td>41</td><td>36200000 Hz</td><td>36.5 dBmV</td></tr></table>
"""

CM3500_SUCCESS = """
<h4>Downstream QAM</h4><table><tr><td></td><td>DCID</td><td>Freq</td><td>Power</td><td>SNR</td><td>Modulation</td><td>Octets</td><td>Correcteds</td><td>Uncorrectables</td></tr><tr><td>Downstream 1</td><td>3</td><td>570 MHz</td><td>4.7 dBmV</td><td>38.98 dB</td><td>256QAM</td><td>100</td><td>92</td><td>0</td></tr></table>
<h4>Downstream OFDM</h4><table><tbody><tr><td>Downstream 1</td><td>4K</td><td>190</td><td>3800</td><td>135</td><td>324</td><td>47</td><td>40</td><td>41</td></tr></tbody></table>
<h4>Upstream QAM</h4><table><tr><td></td><td>UCID</td><td>Freq</td><td>Power</td><td>Channel Type</td><td>Symbol Rate</td><td>Modulation</td></tr><tr><td>Upstream 1</td><td>9</td><td>30.8 MHz</td><td>39.5 dBmV</td><td>DOCSIS2.0 (ATDMA)</td><td>5120</td><td>64QAM</td></tr></table>
<h4>Upstream OFDM</h4><table><tbody><tr><td>Upstream 0</td><td>2K</td><td>32</td><td>640</td><td>74</td><td>773</td><td>29.8</td><td>64.8</td><td>42.25</td></tr></tbody></table>
"""

ARRIS_SUCCESS = """
<table><tr><td><strong>Downstream Bonded Channels</strong></td></tr><tr><th>ID</th><th>Lock</th><th>Modulation</th><th>Frequency</th><th>Power</th><th>SNR</th><th>Corrected</th><th>Uncorrected</th></tr><tr><td>7</td><td>Locked</td><td>256QAM</td><td>591000000 Hz</td><td>0.0 dBmV</td><td>40 dB</td><td>3</td><td>0</td></tr><tr><td>193</td><td>Locked</td><td>Other</td><td>690000000 Hz</td><td></td><td>41.8 dB</td><td>9</td><td>1</td></tr></table>
<table><tr><td><strong>Upstream Bonded Channels</strong></td></tr><tr><th>Channel</th><th>ID</th><th>Lock</th><th>Type</th><th>Frequency</th><th>Width</th><th>Power</th></tr><tr><td>1</td><td>3</td><td>Locked</td><td>SC-QAM Upstream</td><td>29200000 Hz</td><td>6400000</td><td>43.5 dBmV</td></tr><tr><td>2</td><td>41</td><td>Locked</td><td>OFDM Upstream</td><td>36200000 Hz</td><td>44400000</td><td>36.5 dBmV</td></tr></table>
"""

SB6141_SUCCESS = """
<table><tr><th>Downstream</th></tr><tr><td>Channel ID</td><td>7</td></tr><tr><td>Frequency</td><td>591000000 Hz</td></tr><tr><td>Signal to Noise Ratio</td><td>40.0 dB</td></tr><tr><td>Modulation</td><td>256QAM</td></tr><tr><td>Power Level</td><td>0.0 dBmV</td></tr></table>
<table><tr><th>Upstream</th></tr><tr><td>Channel ID</td><td>3</td></tr><tr><td>Frequency</td><td>29200000 Hz</td></tr><tr><td>Power Level</td><td>43.5 dBmV</td></tr><tr><td>Modulation</td><td>[3] QPSK
[3] 64QAM</td></tr></table>
<table><tr><th>Signal Status / Codewords</th></tr><tr><td>Correctable</td><td>3</td></tr><tr><td>Uncorrectable</td><td>1</td></tr></table>
"""


FRITZ_SUCCESS = {
    "channelDs": {
        "docsis30": [
            {"channelID": 1, "frequency": "591 MHz", "powerLevel": 0, "mse": None},
            {"channelID": 1, "frequency": "597 MHz", "powerLevel": None},
            {"frequency": "603 MHz", "powerLevel": "1.0"},
        ],
        "docsis31": [],
    },
    "channelUs": {
        "docsis30": [],
        "docsis31": [
            {"channelID": 5, "type": "OFDMA", "powerLevel": "37.0"},
            {"channelID": 6, "powerLevel": None},
        ],
    },
}


def _cases() -> list[DriverFormatCase]:
    cases: list[DriverFormatCase] = []

    def add(case_id: str, driver: str, family: str, evidence: str, invoke, expected) -> None:
        cases.append(DriverFormatCase(case_id, driver, family, evidence, invoke, expected))

    # Fritz!Box data.lua boundary: input is already normalized by app.fritzbox.
    fritz_expected = json.loads(json.dumps(FRITZ_SUCCESS))
    fritz_expected["channelUs"]["docsis31"][0]["powerLevel"] = "43.0"
    add("fritzbox_data_lua.success_duplicates_missing_id", "fritzbox", "fritzbox_data_lua", "captured-shape", lambda: _fritz(json.loads(json.dumps(FRITZ_SUCCESS))), fritz_expected)
    add("fritzbox_data_lua.empty", "fritzbox", "fritzbox_data_lua", "minimal-empty", lambda: _fritz(json.loads(json.dumps(EMPTY_SPLIT))), EMPTY_SPLIT)
    fritz_bad = _split(us31=[{"channelID": 5, "powerLevel": "not-a-number"}])
    add("fritzbox_data_lua.malformed_power", "fritzbox", "fritzbox_data_lua", "minimal-synthetic-malformed", lambda: _fritz(json.loads(json.dumps(fritz_bad))), fritz_bad)

    tc_expected = _flat(
        [
            {"channelID": "7", "type": "256QAM", "frequency": "591 MHz", "powerLevel": 4.6, "mse": -36.4, "mer": 36.4, "latency": 0, "corrError": 3, "nonCorrError": 30},
            {"channelID": "193", "type": "OFDM", "frequency": "275 MHz", "powerLevel": 3.2, "mse": None, "mer": 38.0, "latency": 0, "corrError": 9, "nonCorrError": 1},
        ],
        [
            {"channelID": "6", "type": "ATDMA", "frequency": "25 MHz", "powerLevel": 35.0, "multiplex": ""},
            {"channelID": "41", "type": "OFDMA", "frequency": "42 MHz", "powerLevel": 37.75, "multiplex": ""},
        ],
    )
    add("tc4400_html.success_scqam_ofdm_ofdma", "tc4400", "tc4400_html", "minimal-synthetic-existing-fields", lambda: _tc(TC_DS_SUCCESS, TC_US_SUCCESS), tc_expected)
    add("tc4400_html.empty_tables", "tc4400", "tc4400_html", "minimal-empty", lambda: _tc("<table></table>", "<table></table>"), EMPTY_FLAT_31)
    add("tc4400_html.malformed_short_rows", "tc4400", "tc4400_html", "minimal-synthetic-malformed", lambda: _tc("<table><tr><th>A</th><th>B</th><th>C</th><th>D</th></tr><tr><td>bad</td></tr></table>", "<table><tr><th>A</th><th>B</th><th>C</th><th>D</th></tr><tr><td>bad</td></tr></table>"), EMPTY_FLAT_31)

    ultra_ds = [{"ChannelID": "7", "Frequency": "591 MHz", "Modulation": "256QAM", "PowerLevel": "0 dBmV", "SNRLevel": "40 dB"}, {"ChannelID": "193", "Frequency": "690 MHz", "Modulation": "OFDM", "PowerLevel": "-0.32 dBmV", "SNRLevel": "41.8 dB"}]
    ultra_us = [{"ChannelID": "3", "Frequency": "29.2 MHz", "Modulation": "ATDMA", "PowerLevel": "43.5 dBmV"}, {"ChannelID": "41", "Frequency": "36.2 MHz", "Modulation": "OFDMA", "PowerLevel": "36.5 dBmV"}]
    ultra_expected = _flat(
        [{"channelID": "7", "type": "256QAM", "frequency": "591 MHz", "powerLevel": 0.0, "mer": 40.0, "mse": None, "latency": 0, "corrErrors": None, "nonCorrErrors": None}, {"channelID": "193", "type": "OFDM", "frequency": "690 MHz", "powerLevel": -0.32, "mer": 41.8, "mse": None, "latency": 0, "corrErrors": None, "nonCorrErrors": None}],
        [{"channelID": "3", "type": "ATDMA", "frequency": "29 MHz", "powerLevel": 43.5, "multiplex": ""}, {"channelID": "41", "type": "OFDMA", "frequency": "36 MHz", "powerLevel": 36.5, "multiplex": ""}],
    )
    add("ultrahub7_json.success_scqam_ofdm_ofdma", "ultrahub7", "ultrahub7_json", "minimal-synthetic-existing-fields", lambda: _ultrahub(ultra_ds, ultra_us), ultra_expected)
    add("ultrahub7_json.missing_fields_become_zero", "ultrahub7", "ultrahub7_json", "minimal-missing", lambda: _ultrahub([{}], [{}]), _flat([{"channelID": "0", "type": "", "frequency": "0 MHz", "powerLevel": 0.0, "mer": None, "mse": None, "latency": 0, "corrErrors": None, "nonCorrErrors": None}], [{"channelID": "0", "type": "", "frequency": "0 MHz", "powerLevel": 0.0, "multiplex": ""}]))
    add("ultrahub7_json.malformed_channel_id", "ultrahub7", "ultrahub7_json", "minimal-synthetic-malformed", lambda: _ultrahub([{"ChannelID": "bad"}], [{"ChannelID": "bad"}]), EMPTY_FLAT_31)

    cga_success = {"downstream": [{"channelid": "7", "CentralFrequency": "591000000", "power": "0", "SNR": "40", "FFT": "256QAM"}], "ofdm_downstream": [{"channelid_ofdm": "193", "CentralFrequency_ofdm": "690000000", "power_ofdm": "-0.32", "SNR_ofdm": "41.8"}], "upstream": [{"channelidup": "3", "CentralFrequency": "29200000", "power": "43.5", "FFT": "64QAM"}], "ofdma_upstream": [{"channelidup": "41", "CentralFrequency": "36200000", "power": "36.5", "FFT": "64-qam", "ChannelType": "OFDMA"}]}
    cga_expected = _split(
        [{"channelID": 7, "type": "256QAM", "frequency": "591 MHz", "powerLevel": 0.0, "mse": -40.0, "mer": 40.0, "latency": 0, "corrError": 0, "nonCorrError": 0}],
        [{"channelID": 193, "type": "OFDM", "frequency": "690 MHz", "powerLevel": -0.32, "mse": -41.8, "mer": 41.8, "latency": 0, "corrError": 0, "nonCorrError": 0}],
        [{"channelID": 3, "type": "64QAM", "frequency": "29 MHz", "powerLevel": 43.5, "multiplex": ""}],
        [{"channelID": 41, "type": "OFDMA", "frequency": "36 MHz", "powerLevel": 36.5, "modulation": "64QAM", "multiplex": ""}],
    )
    add("vodafone_station_cga_json.success_all_lanes", "vodafone_station", "vodafone_station_cga_json", "captured-shape", lambda: _vodafone_cga(cga_success), cga_expected)
    add("vodafone_station_cga_json.empty_object", "vodafone_station", "vodafone_station_cga_json", "minimal-empty", lambda: _vodafone_cga({}), EMPTY_SPLIT)
    add("vodafone_station_cga_json.malformed_non_object_channel", "vodafone_station", "vodafone_station_cga_json", "minimal-synthetic-malformed", lambda: _vodafone_cga({"downstream": [None]}), None)

    tg_expected = _split(
        [{"channelID": 7, "type": "256QAM", "frequency": "591.000 MHz", "powerLevel": -1.2, "mse": -40.0, "mer": 40.0, "latency": 0, "corrError": 0, "nonCorrError": 0}],
        [{"channelID": 193, "type": "OFDM", "frequency": "374.275 MHz", "powerLevel": 3.2, "mse": -38.0, "mer": 38.0, "latency": 0, "corrError": 0, "nonCorrError": 0}],
        [{"channelID": 6, "type": "64QAM", "frequency": "25.900 MHz", "powerLevel": 35.0, "multiplex": ""}],
        [{"channelID": 41, "type": "OFDMA", "frequency": "42.000 MHz", "powerLevel": 37.75, "multiplex": ""}],
    )
    add("vodafone_station_tg_embedded_json.success_all_lanes", "vodafone_station", "vodafone_station_tg_embedded_json", "minimal-synthetic-existing-fields", lambda: _vodafone_tg(TG_SUCCESS), tg_expected)
    add("vodafone_station_tg_embedded_json.empty_arrays", "vodafone_station", "vodafone_station_tg_embedded_json", "minimal-empty", lambda: _vodafone_tg("<script>json_dsData=[];json_usData=[];</script>"), None)
    add("vodafone_station_tg_embedded_json.malformed_json", "vodafone_station", "vodafone_station_tg_embedded_json", "minimal-synthetic-malformed", lambda: _vodafone_tg("<script>json_dsData=[{bad}];</script>"), None)

    ch_ds = "<root><downstream><chid>7</chid><freq>591 MHz</freq><pow>0</pow><RxMER>40</RxMER><mod>256qam</mod><PreRs>3</PreRs><PostRs>1</PostRs></downstream><downstream><chid>7</chid><freq>597 MHz</freq><pow>1</pow></downstream></root>"
    ch_us = "<root><upstream><usid>3</usid><freq>29 MHz</freq><power>43.5</power><mod>64qam</mod><messageType>35</messageType></upstream></root>"
    ch_expected = {"docsis": "3.0", "downstream": [{"channelID": 7, "frequency": "591 MHz", "powerLevel": 0.0, "mer": 40.0, "mse": -40.0, "modulation": "256QAM", "corrErrors": 3, "nonCorrErrors": 1}, {"channelID": 7, "frequency": "597 MHz", "powerLevel": 1.0}], "upstream": [{"channelID": 3, "frequency": "29 MHz", "powerLevel": 43.5, "modulation": "64QAM", "multiplex": "atdma"}]}
    add("ch7465_xml.success_duplicate_ids", "ch7465,ch7465_play", "ch7465_xml", "minimal-synthetic-existing-fields", lambda: _ch7465(ch_ds, ch_us), ch_expected)
    add("ch7465_xml.empty_roots", "ch7465,ch7465_play", "ch7465_xml", "minimal-empty", lambda: _ch7465("<root/>", "<root/>"), {"docsis": "3.0", "downstream": [], "upstream": []})
    add("ch7465_xml.malformed_xml", "ch7465,ch7465_play", "ch7465_xml", "minimal-synthetic-malformed", lambda: _ch7465("<root>", "<root/>"), None)

    sb_ds = '<downstream_table><ds_num>2</ds_num><downstream><freq>567000000</freq><pow>2.300</pow><snr>33</snr><mod>256QAM</mod><chid>32</chid><IsLocked>1</IsLocked></downstream><downstream><freq>417000000</freq><pow>0.100</pow><snr>34</snr><mod>256QAM</mod><chid>9</chid><IsLocked>0</IsLocked></downstream></downstream_table>'
    sb_us = '<upstream_table><us_num>1</us_num><upstream><usid>56</usid><freq>37000000</freq><power>49</power><srate>5.120</srate><mod>64QAM</mod><channeltype>ATDMA</channeltype><bandwidth>6400000</bandwidth><usLocked>1</usLocked></upstream></upstream_table>'
    sb_ofdm = '<downstreamOFDM_table><downstream><Receiver>1</Receiver><Subcarr0Frequency>605600000</Subcarr0Frequency><PLCLocked>YES</PLCLocked><MDC1Locked>YES</MDC1Locked><PLCPower>1.100</PLCPower><DataScAvgMer>33</DataScAvgMer><ofdmModulation>QAM4096</ofdmModulation><dsid>25</dsid><ofdmCorrected>904607089</ofdmCorrected><ofdmUncorrectable>2612685723</ofdmUncorrectable><ofdmIsLocked>1</ofdmIsLocked><ofdmIsActive>1</ofdmIsActive></downstream><ds_num>1</ds_num></downstreamOFDM_table>'
    sb_ofdma = '<upstreamOFDMA_table><us_num>0</us_num></upstreamOFDMA_table>'
    sb_signal = '<signal_table><sig_num>2</sig_num><signal><dsid>25</dsid><unerrored>0</unerrored><correctable>0</correctable><uncorrectable>0</uncorrectable></signal><signal><dsid>32</dsid><unerrored>54275570015</unerrored><correctable>226053938</correctable><uncorrectable>1212</uncorrectable></signal></signal_table>'
    sb_expected = _split(
        [{"channelID": 32, "frequency": "567 MHz", "powerLevel": 2.3, "mer": 33.0, "mse": -33.0, "modulation": "256QAM", "symbolRate": 5361, "corrErrors": 226053938, "nonCorrErrors": 1212}],
        [{"channelID": 25, "type": "OFDM", "frequency": "605.6 MHz", "powerLevel": 1.1, "mse": None, "mer": 33.0, "modulation": "4096QAM"}],
        [{"channelID": 56, "frequency": "37 MHz", "powerLevel": 49.0, "modulation": "64QAM", "multiplex": "ATDMA", "symbolRate": 5120}],
    )
    add("sb8200_cbn_xml.success_all_lanes", "sb8200_cbn", "sb8200_cbn_xml", "captured-subset", lambda: _sb8200_cbn(sb_ds, sb_us, sb_ofdm, sb_ofdma, sb_signal), sb_expected)
    add("sb8200_cbn_xml.empty_tables", "sb8200_cbn", "sb8200_cbn_xml", "minimal-empty", lambda: _sb8200_cbn("<downstream_table/>", "<upstream_table/>", "<downstreamOFDM_table/>", sb_ofdma, "<signal_table/>"), EMPTY_SPLIT)
    add("sb8200_cbn_xml.malformed_xml", "sb8200_cbn", "sb8200_cbn_xml", "minimal-synthetic-malformed", lambda: _sb8200_cbn("<downstream_table>", "<upstream_table/>", sb_ofdm, sb_ofdma, sb_signal), None)

    cm3000_expected = _split(
        [{"channelID": 7, "frequency": "591 MHz", "powerLevel": -2.5, "mer": 40.0, "mse": -40.0, "modulation": "QAM256", "corrErrors": 1234, "nonCorrErrors": 5}],
        [{"channelID": 193, "type": "OFDM", "frequency": "690 MHz", "powerLevel": -0.32, "mer": 41.8, "mse": None, "corrErrors": 9, "nonCorrErrors": 1}],
        [{"channelID": 3, "frequency": "29.2 MHz", "powerLevel": 43.5, "modulation": "ATDMA", "multiplex": "ATDMA"}],
        [{"channelID": 41, "type": "OFDMA", "frequency": "36.2 MHz", "powerLevel": 36.5, "modulation": "OFDMA", "multiplex": ""}],
    )
    add("cm3000_javascript.success_all_lanes", "cm3000", "cm3000_javascript", "captured-subset", lambda: _cm3000(CM3000_SUCCESS), cm3000_expected)
    add("cm3000_javascript.empty_tag_values", "cm3000", "cm3000_javascript", "minimal-empty", lambda: _cm3000(_cm3000_html("", "", "", "")), EMPTY_SPLIT)
    add("cm3000_javascript.malformed_numeric", "cm3000", "cm3000_javascript", "minimal-synthetic-malformed", lambda: _cm3000(_cm3000_html("1|1|Locked|QAM256|bad|591000000 Hz|x|y|z|q|", "", "", "")), EMPTY_SPLIT)

    cm1000_js = (ROOT / "tests/fixtures/cm1000/DocsisStatus.asp.html").read_text(encoding="utf-8")
    cm1000_js_expected = _split(
        [{"channelID": 143, "frequency": "453 MHz", "powerLevel": -2.5, "mer": 48.5, "mse": -48.5, "modulation": "64QAM", "corrErrors": None, "nonCorrErrors": None, "symbolRate": 5057}],
        [],
        [{"channelID": 1, "frequency": "33 MHz", "powerLevel": 34.8, "modulation": "TDMA", "multiplex": "TDMA", "symbolRate": 2560}],
        [],
    )
    add("cm1000_javascript.success_captured_fixture", "cm1000", "cm1000_javascript", "captured-disk", lambda: _cm1000(cm1000_js), cm1000_js_expected)
    add("cm1000_javascript.empty_tag_values", "cm1000", "cm1000_javascript", "minimal-empty", lambda: _cm1000("<script>function InitDsTableTagValue(){var tagValueList='';} function InitUsTableTagValue(){var tagValueList='';}</script>"), EMPTY_SPLIT)
    add("cm1000_javascript.malformed_row_width", "cm1000", "cm1000_javascript", "minimal-synthetic-malformed", lambda: _cm1000("<script>function InitDsTableTagValue(){var tagValueList='1|short';} function InitUsTableTagValue(){var tagValueList='1|short';}</script>"), EMPTY_SPLIT)

    cm1000_table_expected = _split(
        [{"channelID": 7, "frequency": "591 MHz", "powerLevel": 0.0, "mer": 40.0, "mse": -40.0, "modulation": "256QAM", "corrErrors": 0, "nonCorrErrors": 5, "symbolRate": 5361}],
        [{"channelID": 193, "type": "OFDM", "frequency": "690 MHz", "powerLevel": -0.32, "mer": 41.8, "mse": None, "modulation": "OFDM", "corrErrors": 9, "nonCorrErrors": 1}],
        [{"channelID": 3, "frequency": "29.2 MHz", "powerLevel": 43.5, "modulation": "ATDMA", "multiplex": "ATDMA"}],
        [{"channelID": 41, "type": "OFDMA", "frequency": "36.2 MHz", "powerLevel": 36.5, "modulation": "OFDMA", "multiplex": ""}],
    )
    add("cm1000_html_table.success_all_lanes", "cm1000", "cm1000_html_table", "captured-subset", lambda: _cm1000(CM1000_TABLE_SUCCESS), cm1000_table_expected)
    add("cm1000_html_table.empty_document", "cm1000", "cm1000_html_table", "minimal-empty", lambda: _cm1000("<html/ >"), EMPTY_SPLIT)
    add("cm1000_html_table.malformed_missing_channel_id", "cm1000", "cm1000_html_table", "minimal-synthetic-malformed", lambda: _cm1000("<table id='dsTable'><tr><th>Lock Status</th><th>Frequency</th><th>Power</th><th>SNR</th></tr><tr><td>Locked</td><td>591000000</td><td>0</td><td>40</td></tr></table>"), EMPTY_SPLIT)

    cm3500_expected = _split(
        [{"channelID": 3, "frequency": "570 MHz", "powerLevel": 4.7, "mse": -38.98, "mer": 38.98, "modulation": "256QAM", "corrErrors": 92, "nonCorrErrors": 0}],
        [{"channelID": 200, "type": "OFDM", "frequency": "135-324 MHz", "powerLevel": None, "mer": 41.0, "mse": None, "corrErrors": None, "nonCorrErrors": None}],
        [{"channelID": 9, "frequency": "30 MHz", "powerLevel": 39.5, "modulation": "64QAM", "multiplex": "ATDMA"}],
        [{"channelID": 200, "type": "OFDMA", "frequency": "29-64 MHz", "powerLevel": 42.25, "modulation": "OFDMA", "multiplex": ""}],
    )
    add("cm3500_html.success_all_lanes", "cm3500", "cm3500_html", "captured-subset", lambda: _cm3500(CM3500_SUCCESS), cm3500_expected)
    add("cm3500_html.empty_document", "cm3500", "cm3500_html", "minimal-empty", lambda: _cm3500("<html></html>"), EMPTY_SPLIT)
    add("cm3500_html.malformed_numeric", "cm3500", "cm3500_html", "minimal-synthetic-malformed", lambda: _cm3500("<h4>Downstream QAM</h4><table><tr><td>a</td><td>b</td><td>c</td><td>d</td><td>e</td><td>f</td><td>g</td><td>h</td><td>i</td></tr><tr><td>x</td><td>bad</td><td>bad</td><td>bad</td><td>bad</td><td>QAM</td><td>0</td><td>bad</td><td>bad</td></tr></table>"), _split(ds30=[{"channelID": 0, "frequency": "bad", "powerLevel": 0.0, "mse": -0.0, "mer": 0.0, "modulation": "QAM", "corrErrors": 0, "nonCorrErrors": 0}]))

    surf_ds = "1^Locked^256QAM^43^705000000^0.0^40.9^31^0^|+|2^Locked^OFDM PLC^193^957000000^0.1^43.0^9^1^"
    surf_us = "1^Locked^SC-QAM^3^6400000^29200000^46.5^|+|2^Locked^OFDMA^41^44400000^36200000^43.8^"
    surf_expected = _split(
        [{"channelID": 43, "frequency": "705 MHz", "powerLevel": 0.0, "mer": 40.9, "mse": -40.9, "modulation": "256QAM", "corrErrors": 31, "nonCorrErrors": 0}],
        [{"channelID": 193, "type": "OFDM", "frequency": "957 MHz", "powerLevel": 0.1, "mer": 43.0, "mse": None, "corrErrors": 9, "nonCorrErrors": 1}],
        [{"channelID": 3, "frequency": "29.2 MHz", "powerLevel": 46.5, "modulation": "SC-QAM", "multiplex": "SC-QAM"}],
        [{"channelID": 41, "type": "OFDMA", "frequency": "36.2 MHz", "powerLevel": 43.8, "modulation": "OFDMA", "multiplex": ""}],
    )
    add("surfboard_hnap.success_all_lanes", "surfboard", "surfboard_hnap", "captured-subset", lambda: _surfboard(surf_ds, surf_us), surf_expected)
    add("surfboard_hnap.empty_strings", "surfboard", "surfboard_hnap", "minimal-empty", lambda: _surfboard("", ""), EMPTY_SPLIT)
    add("surfboard_hnap.malformed_numeric", "surfboard", "surfboard_hnap", "minimal-synthetic-malformed", lambda: _surfboard("1^Locked^256QAM^bad^bad^bad^bad^bad^bad^", "1^Locked^SC-QAM^bad^0^bad^bad^"), EMPTY_SPLIT)

    arris_expected = _split(
        [{"channelID": 7, "frequency": "591 MHz", "powerLevel": 0.0, "modulation": "256QAM", "corrErrors": 3, "nonCorrErrors": 0, "mer": 40.0, "mse": -40.0}],
        [{"channelID": 193, "frequency": "690 MHz", "powerLevel": None, "modulation": "Other", "corrErrors": 9, "nonCorrErrors": 1, "type": "OFDM", "mer": 41.8, "mse": None}],
        [{"channelID": 3, "frequency": "29.2 MHz", "powerLevel": 43.5, "modulation": "SC-QAM Upstream", "multiplex": "SC-QAM"}],
        [{"channelID": 41, "frequency": "36.2 MHz", "powerLevel": 36.5, "modulation": "OFDM Upstream", "type": "OFDMA", "multiplex": ""}],
    )
    add("arris_html.success_scqam_ofdm_ofdma", "surfboard,cm8200", "arris_html", "captured-subset", lambda: parse_arris_channel_tables(ARRIS_SUCCESS), arris_expected)
    add("arris_html.empty_document", "surfboard,cm8200", "arris_html", "minimal-empty", lambda: parse_arris_channel_tables("<html></html>"), EMPTY_SPLIT)
    arris_bad = ARRIS_SUCCESS.replace("<td>7</td><td>Locked</td>", "<td>bad</td><td>Locked</td>").replace("<td>3</td><td>Locked</td>", "<td>bad</td><td>Locked</td>")
    add("arris_html.malformed_channel_ids", "surfboard,cm8200", "arris_html", "minimal-synthetic-malformed", lambda: parse_arris_channel_tables(arris_bad), _split(ds31=arris_expected["channelDs"]["docsis31"], us31=arris_expected["channelUs"]["docsis31"]))

    sb6141_expected = _split(
        [{"channelID": 7, "frequency": "591 MHz", "powerLevel": 0.0, "mer": 40.0, "mse": -40.0, "modulation": "256QAM", "corrErrors": 3, "nonCorrErrors": 1}], [],
        [{"channelID": 3, "frequency": "29.2 MHz", "powerLevel": 43.5, "modulation": "64QAM", "multiplex": "SC-QAM"}], [],
    )
    add("sb6141_transposed_html.success", "sb6141", "sb6141_transposed_html", "captured-subset", lambda: _sb6141(SB6141_SUCCESS), sb6141_expected)
    add("sb6141_transposed_html.empty_document", "sb6141", "sb6141_transposed_html", "minimal-empty", lambda: _sb6141("<html></html>"), EMPTY_SPLIT)
    add("sb6141_transposed_html.malformed_channel_id", "sb6141", "sb6141_transposed_html", "minimal-synthetic-malformed", lambda: _sb6141(SB6141_SUCCESS.replace("<td>7</td>", "<td>bad</td>", 1).replace("<td>3</td>", "<td>bad</td>", 1)), EMPTY_SPLIT)

    from tests.test_sb6183_driver import SAMPLE_STATUS_HTML as SB6183_HTML
    from tests.test_sb6190_driver import SAMPLE_STATUS_HTML as SB6190_HTML
    sb6183_success = _split(
        ds30=[{"channelID": 6, "frequency": "315 MHz", "powerLevel": 0.7, "mer": 40.2, "mse": -40.2, "modulation": "QAM256", "corrErrors": 29, "nonCorrErrors": 0}],
        us30=[{"channelID": 67, "frequency": "30.4 MHz", "powerLevel": 48.3, "modulation": "ATDMA", "multiplex": "ATDMA"}],
    )
    sb6190_success = _split(
        ds30=[{"channelID": 13, "frequency": "807 MHz", "powerLevel": 10.5, "mer": 40.95, "mse": -40.95, "modulation": "256QAM", "corrErrors": 33, "nonCorrErrors": 0}],
        us30=[{"channelID": 1, "frequency": "17.6 MHz", "powerLevel": 35.0, "modulation": "ATDMA", "multiplex": "ATDMA"}],
    )
    add("sb6183_html.success_captured_first_rows", "sb6183", "sb6183_html", "captured-disk", lambda: _row_html_driver(SB6183Driver, SB6183_HTML), sb6183_success)
    add("sb6183_html.empty_document", "sb6183", "sb6183_html", "minimal-empty", lambda: _row_html_driver(SB6183Driver, "<html></html>"), EMPTY_SPLIT)
    add("sb6183_html.malformed_rows", "sb6183", "sb6183_html", "minimal-synthetic-malformed", lambda: _row_html_driver(SB6183Driver, "<table><tr><th>Downstream Bonded</th></tr><tr><td>1</td><td>Locked</td><td>QAM</td><td>bad</td><td>bad</td><td>bad</td><td>bad</td><td>bad</td><td>bad</td></tr></table>"), EMPTY_SPLIT)
    add("sb6190_html.success_captured_first_rows", "sb6190", "sb6190_html", "captured-inline", lambda: _row_html_driver(SB6190Driver, SB6190_HTML), sb6190_success)
    add("sb6190_html.empty_document", "sb6190", "sb6190_html", "minimal-empty", lambda: _row_html_driver(SB6190Driver, "<html></html>"), EMPTY_SPLIT)
    add("sb6190_html.malformed_rows", "sb6190", "sb6190_html", "minimal-synthetic-malformed", lambda: _row_html_driver(SB6190Driver, "<table><tr><th>Downstream Bonded</th></tr><tr><td>1</td><td>Locked</td><td>QAM</td><td>bad</td><td>bad</td><td>bad</td><td>bad</td><td>bad</td><td>bad</td></tr></table>"), EMPTY_SPLIT)

    from tests.test_hitron_driver import DS_OFDM_DATA, DS_SCQAM_DATA, US_OFDMA_DATA, US_SCQAM_DATA
    hitron_payload = {"/data/dsinfo.asp": DS_SCQAM_DATA[:1], "/data/usinfo.asp": US_SCQAM_DATA[:1], "/data/dsofdminfo.asp": DS_OFDM_DATA[:1], "/data/usofdminfo.asp": US_OFDMA_DATA[:1]}
    hitron_expected = _split(
        ds30=[{"channelID": 7, "frequency": "591 MHz", "powerLevel": 4.6, "modulation": "256QAM", "mer": 36.387, "mse": -36.387, "corrErrors": 3, "nonCorrErrors": 30}],
        ds31=[{"channelID": 0, "type": "OFDM", "frequency": "275.6 MHz", "powerLevel": 3.200001, "modulation": "OFDM", "mer": 38.0, "mse": None, "corrErrors": 652068075, "nonCorrErrors": 19}],
        us30=[{"channelID": 6, "frequency": "25.9 MHz", "powerLevel": 35.0, "modulation": "64QAM", "multiplex": "ATDMA"}],
        us31=[{"channelID": 0, "type": "OFDMA", "frequency": "42 MHz", "powerLevel": 37.75, "modulation": "OFDMA", "multiplex": ""}],
    )
    add("hitron_coda56_json.success_captured_first_rows", "hitron", "hitron_coda56_json", "captured-inline", lambda: _hitron(hitron_payload), hitron_expected)
    add("hitron_coda56_json.empty_arrays", "hitron", "hitron_coda56_json", "minimal-empty", lambda: _hitron({path: [] for path in hitron_payload}), EMPTY_SPLIT)
    add("hitron_coda56_json.malformed_missing_required_fields", "hitron", "hitron_coda56_json", "minimal-synthetic-malformed", lambda: _hitron({path: [{}] for path in hitron_payload}), EMPTY_SPLIT)

    from tests.test_hitron_coda_4680_driver import DS_INFO, DS_OFDM, US_INFO, US_OFDMA
    h4680_payload = {"/1/Device/CM/DsInfo": {"Freq_List": DS_INFO["Freq_List"][:1]}, "/1/Device/CM/UsInfo": {"Freq_List": US_INFO["Freq_List"][:1]}, "/1/Device/CM/DsOfdm": {"OFDMs_List": DS_OFDM["OFDMs_List"][:1]}, "/1/Device/CM/UsOfdm": {"OFDMAs_List": US_OFDMA["OFDMAs_List"][:1]}}
    h4680_expected = _split(
        ds30=[{"channelID": 18, "frequency": "663 MHz", "powerLevel": 5.099, "modulation": "256QAM", "mer": 40.946, "mse": -40.946, "corrErrors": 5, "nonCorrErrors": 33}],
        ds31=[{"channelID": 0, "type": "OFDM", "frequency": "275.6 MHz", "powerLevel": 3.0, "modulation": "OFDM", "mer": None, "mse": None, "corrErrors": None, "nonCorrErrors": None}],
        us30=[{"channelID": 3, "frequency": "32.3 MHz", "powerLevel": 42.77, "modulation": "64QAM", "multiplex": "ATDMA", "symbolRate": 5120}],
        us31=[{"channelID": 0, "type": "OFDMA", "frequency": "", "powerLevel": 38.75, "modulation": "OFDMA", "multiplex": "OFDMA"}],
    )
    add("hitron_coda4680_json.success_captured_first_rows", "hitron_coda_4680", "hitron_coda4680_json", "captured-inline", lambda: _hitron_4680(h4680_payload), h4680_expected)
    add("hitron_coda4680_json.empty_arrays", "hitron_coda_4680", "hitron_coda4680_json", "minimal-empty", lambda: _hitron_4680({"/1/Device/CM/DsInfo": {}, "/1/Device/CM/UsInfo": {}, "/1/Device/CM/DsOfdm": {}, "/1/Device/CM/UsOfdm": {}}), EMPTY_SPLIT)
    add("hitron_coda4680_json.malformed_missing_required_fields", "hitron_coda_4680", "hitron_coda4680_json", "minimal-synthetic-malformed", lambda: _hitron_4680({"/1/Device/CM/DsInfo": {"Freq_List": [{}]}, "/1/Device/CM/UsInfo": {"Freq_List": [{}]}, "/1/Device/CM/DsOfdm": {"OFDMs_List": [{"plclock": "YES"}]}, "/1/Device/CM/UsOfdm": {"OFDMAs_List": [{"state": "OPERATE"}]}}), EMPTY_SPLIT)

    sagem_ds = [{"ChannelID": 13, "LockStatus": True, "Frequency": 546000000.0, "SNR": 44.0, "PowerLevel": 0, "Modulation": "Qam256", "BandWidth": 8000000, "CorrectableCodewords": 10, "UncorrectableCodewords": 2}, {"ChannelID": 193, "LockStatus": True, "Frequency": 666000000.0, "SNR": 44.0, "PowerLevel": 7.9, "Modulation": "256-QAM1K-QAM2K-QA", "BandWidth": 128000000, "CorrectableCodewords": 100, "UncorrectableCodewords": 0}]
    sagem_us = [{"ChannelID": 1, "LockStatus": True, "Frequency": 38000000.0, "PowerLevel": 41.8, "Modulation": "atdma"}, {"ChannelID": 41, "LockStatus": True, "Frequency": 104800000.0, "PowerLevel": 88.0, "Modulation": "ofdma"}]
    sagem_expected = _split(
        ds30=[{"channelID": 13, "frequency": "546 MHz", "powerLevel": 0, "mer": 44.0, "mse": -44.0, "modulation": "256QAM", "corrErrors": 10, "nonCorrErrors": 2}],
        ds31=[{"channelID": 193, "type": "OFDM", "frequency": "666 MHz", "powerLevel": 7.9, "mer": 44.0, "mse": None, "corrErrors": 100, "nonCorrErrors": 0}],
        us30=[{"channelID": 1, "frequency": "38 MHz", "powerLevel": 41.8, "modulation": "ATDMA", "multiplex": "ATDMA"}],
        us31=[{"channelID": 41, "type": "OFDMA", "frequency": "104.8 MHz", "powerLevel": 88.0, "modulation": "OFDMA", "multiplex": ""}],
    )
    add("sagemcom_xmo_json.success_all_lanes", "sagemcom", "sagemcom_xmo_json", "captured-inline", lambda: _sagemcom(sagem_ds, sagem_us), sagem_expected)
    add("sagemcom_xmo_json.empty_arrays", "sagemcom", "sagemcom_xmo_json", "minimal-empty", lambda: _sagemcom([], []), EMPTY_SPLIT)
    add("sagemcom_xmo_json.malformed_values", "sagemcom", "sagemcom_xmo_json", "minimal-synthetic-malformed", lambda: _sagemcom([{"LockStatus": True, "BandWidth": "bad"}], [{"LockStatus": True, "Modulation": None}]), None)

    from tests.drivers.f3896lg._data import DOWNSTREAM, UPSTREAM
    f_ds = [DOWNSTREAM["downstream"]["channels"][0], DOWNSTREAM["downstream"]["channels"][-1]]
    f_us = [UPSTREAM["upstream"]["channels"][0], UPSTREAM["upstream"]["channels"][-1]]
    f_expected = _split(
        ds30=[{"channelID": 1, "frequency": "411 MHz", "powerLevel": -4.3, "mer": 39, "mse": -39, "modulation": "256QAM", "corrErrors": 26, "nonCorrErrors": 0}],
        ds31=[{"channelID": 41, "type": "OFDM", "frequency": "", "powerLevel": -11.8, "mer": None, "mse": None, "modulation": "OFDM", "corrErrors": 1361678039, "nonCorrErrors": 483483438, "profile_modulation": "4096QAM"}],
        us30=[{"channelID": 6, "frequency": "49.6 MHz", "powerLevel": 42.5, "modulation": "64QAM", "multiplex": "ATDMA", "symbolRate": 5120}],
        us31=[{"channelID": 12, "type": "OFDMA", "frequency": "", "powerLevel": 38.0, "modulation": "OFDMA", "multiplex": "", "profile_modulation": "256QAM"}],
    )
    add("f3896lg_rest_json.success_captured_all_lanes", "f3896lg", "f3896lg_rest_json", "captured-inline", lambda: _f3896(f_ds, f_us), f_expected)
    add("f3896lg_rest_json.empty_arrays", "f3896lg", "f3896lg_rest_json", "minimal-empty", lambda: _f3896([], []), EMPTY_SPLIT)
    add("f3896lg_rest_json.malformed_values", "f3896lg", "f3896lg_rest_json", "minimal-synthetic-malformed", lambda: _f3896([{"lockStatus": True, "channelType": "sc_qam", "frequency": "bad", "snr": 0}], [{"lockStatus": True, "channelType": "ofdma", "power": "bad"}]), _split(us31=[{"channelID": 0, "type": "OFDMA", "frequency": "", "powerLevel": None, "modulation": "OFDMA", "multiplex": ""}]))

    from tests.test_sercom_dm1000_driver import DS_INFO as SER_DS, DS_OFDM as SER_OFDM, US_INFO as SER_US, US_OFDMA as SER_OFDMA
    ser_expected = _split(
        ds30=[{"channelID": 7, "frequency": "591 MHz", "powerLevel": 8.800003, "modulation": "256QAM", "mer": 38.983261, "mse": -38.983261, "corrErrors": 41, "nonCorrErrors": 2}],
        ds31=[{"channelID": 0, "type": "OFDM", "frequency": "275.6 MHz", "powerLevel": 10.300003, "modulation": "OFDM", "mer": 39.0, "mse": None, "corrErrors": None, "nonCorrErrors": None}],
        us30=[{"channelID": 5, "frequency": "21.1 MHz", "powerLevel": 35.2603, "modulation": "64QAM", "multiplex": "ATDMA", "symbolRate": 2560}],
        us31=[{"channelID": 0, "type": "OFDMA", "frequency": "42 MHz", "powerLevel": 37.25, "modulation": "OFDMA", "multiplex": "OFDMA", "profile_modulation": "256QAM"}],
    )
    add("sercom_dm1000_json.success_captured_all_lanes", "sercom_dm1000", "sercom_dm1000_json", "captured-inline", lambda: _sercom(SER_DS["nodes"][:1], SER_OFDM["nodes"][:1], SER_US["nodes"][:1], SER_OFDMA["nodes"]), ser_expected)
    add("sercom_dm1000_json.empty_arrays", "sercom_dm1000", "sercom_dm1000_json", "minimal-empty", lambda: _sercom([], [], [], []), EMPTY_SPLIT)
    add("sercom_dm1000_json.malformed_missing_required_fields", "sercom_dm1000", "sercom_dm1000_json", "minimal-synthetic-malformed", lambda: _sercom([{"qamD": "256QAM"}], [{"PLC": "YES", "MDC1": "YES", "AV_Data": "40"}], [{"modulation": "64QAM", "upstream": "1", "rate": "2.56"}], [{"name": "CH", "index1": "bad"}, {"name": "Power", "index1": "ON"}, {"name": "STATE", "index1": "RNG3"}, {"name": "Center Freq SC0", "index1": "42"}]), EMPTY_SPLIT)

    cgm_ds = {"Channel ID": ["7", "193"], "Lock Status": ["Locked", "Locked"], "Frequency": ["591 MHz", "690000000"], "SNR": ["40 dB", "41.8 dB"], "Power Level": ["0 dBmV", ""], "Modulation": ["256 QAM", "OFDM"]}
    cgm_us = {"Channel ID": ["3", "41"], "Lock Status": ["Locked", "Locked"], "Frequency": ["29 MHz", "42 MHz"], "Power Level": ["43.5 dBmV", "37.75 dBmV"], "Modulation": ["QAM", "OFDMA"], "Channel Type": ["ATDMA", "OFDMA"]}
    cgm_err = {"Channel ID": ["7", "193"], "Correctable Codewords": ["3", "9"], "Uncorrectable Codewords": ["0", "1"]}
    cgm_expected = _split(
        ds30=[{"channelID": 7, "frequency": "591 MHz", "powerLevel": 0.0, "mer": 40.0, "mse": -40.0, "modulation": "256QAM", "corrErrors": 3, "nonCorrErrors": 0}],
        ds31=[{"channelID": 193, "frequency": "690 MHz", "powerLevel": None, "mer": 41.8, "mse": -41.8, "modulation": "OFDM", "corrErrors": 9, "nonCorrErrors": 1, "type": "OFDM"}],
        us30=[{"channelID": 3, "frequency": "29 MHz", "powerLevel": 43.5, "modulation": "QAM", "multiplex": "ATDMA"}],
        us31=[{"channelID": 41, "frequency": "42 MHz", "powerLevel": 37.75, "modulation": "OFDMA", "multiplex": "OFDMA", "type": "OFDMA"}],
    )
    add("cgm4981_columnar_html.success_all_lanes", "cgm4981", "cgm4981_columnar_html", "minimal-synthetic-existing-fields", lambda: _cgm(cgm_ds, cgm_us, cgm_err), cgm_expected)
    add("cgm4981_columnar_html.empty_rows", "cgm4981", "cgm4981_columnar_html", "minimal-empty", lambda: _cgm({}, {}, {}), EMPTY_SPLIT)
    add("cgm4981_columnar_html.malformed_channel_ids", "cgm4981", "cgm4981_columnar_html", "minimal-synthetic-malformed", lambda: _cgm({"Channel ID": ["bad"], "Lock Status": ["Locked"]}, {"Channel ID": ["bad"], "Lock Status": ["Locked"]}, {}), EMPTY_SPLIT)

    generic = GenericDriver("", "", "")
    add("generic_no_docsis.success_boundary", "generic", "generic_no_docsis", "no-input-boundary", generic.get_docsis_data, EMPTY_SPLIT)
    add("generic_no_docsis.missing_input_not_applicable", "generic", "generic_no_docsis", "no-input-boundary", GenericDriver("", "", "").get_docsis_data, EMPTY_SPLIT)
    add("generic_no_docsis.malformed_input_not_applicable", "generic", "generic_no_docsis", "no-input-boundary", GenericDriver("", "", "").get_docsis_data, EMPTY_SPLIT)

    return cases


CASES = tuple(sorted(_cases(), key=lambda case: case.case_id))
CASE_BY_ID = {case.case_id: case for case in CASES}

if len(CASE_BY_ID) != len(CASES):
    raise AssertionError("driver format case IDs must be unique")
