"""Pure profiles for Vodafone CGA, TG embedded JSON, and Ultra Hub payloads."""

from __future__ import annotations

import json
import re
from typing import Any

from ...types import DocsisDataFritz, RawChannel
from .contract import ParseDiagnostic, ParseResult, diagnostic, docsis_split
from .primitives import normalize_modulation, parse_number


def _ultra_value(value: Any) -> float:
    if not value:
        return 0.0
    try:
        return float(str(value).strip().split()[0])
    except (IndexError, ValueError):
        return 0.0


def parse_ultrahub7_downstream(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        try:
            channel_id = int(row.get("ChannelID", "0"))
            frequency = _ultra_value(row.get("Frequency", "0"))
            modulation = str(row.get("Modulation", "") or "").upper().replace("-", "")
            power = _ultra_value(row.get("PowerLevel", "0"))
            snr = _ultra_value(row.get("SNRLevel", ""))
            channels.append({
                "channelID": str(channel_id), "type": modulation,
                "frequency": f"{int(frequency)} MHz", "powerLevel": power,
                "mer": snr if snr > 0 else None, "mse": None, "latency": 0,
                "corrErrors": None, "nonCorrErrors": None,
            })
        except (ValueError, TypeError):
            diagnostics.append(diagnostic(
                "ultrahub7_json", "invalid_channel", family="vodafone",
                direction="downstream", index=index,
            ))
    return ParseResult(channels, tuple(diagnostics))


def parse_ultrahub7_upstream(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        try:
            channel_id = int(row.get("ChannelID", "0"))
            frequency = _ultra_value(row.get("Frequency", "0"))
            modulation = str(row.get("Modulation", "") or "").upper().replace("-", "")
            channels.append({
                "channelID": str(channel_id), "type": modulation,
                "frequency": f"{int(frequency)} MHz",
                "powerLevel": _ultra_value(row.get("PowerLevel", "0")),
                "multiplex": "",
            })
        except (ValueError, TypeError):
            diagnostics.append(diagnostic(
                "ultrahub7_json", "invalid_channel", family="vodafone",
                direction="upstream", index=index,
            ))
    return ParseResult(channels, tuple(diagnostics))


def parse_ultrahub7_json(
    payload: dict[str, list[dict[str, Any]]] | None,
) -> ParseResult[dict[str, Any]]:
    data = payload if isinstance(payload, dict) else {}
    downstream = parse_ultrahub7_downstream(data.get("downstream", []))
    upstream = parse_ultrahub7_upstream(data.get("upstream", []))
    return ParseResult({
        "docsis": "3.1", "downstream": downstream.value, "upstream": upstream.value,
    }, downstream.diagnostics + upstream.diagnostics)


def _cga_frequency(value: Any) -> float:
    number = parse_number(value) if isinstance(value, str) else float(value or 0)
    return number / 1_000_000 if number > 1_000_000 else number


def parse_vodafone_number(value: Any) -> float:
    return parse_number(value) if isinstance(value, str) else float(value or 0)


def _parse_cga_lane(rows: Any, lane: str) -> ParseResult[list[RawChannel] | None]:
    if not isinstance(rows, list):
        return ParseResult([])
    result: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            diagnostics.append(diagnostic(
                "vodafone_station_cga_json", "invalid_channel", family="vodafone",
                direction="downstream" if lane.startswith("ds") else "upstream", index=index,
            ))
            return ParseResult(None, tuple(diagnostics))
        try:
            if lane == "ds30":
                snr = abs(parse_number(row.get("SNR", "0")))
                modulation = normalize_modulation(row.get("FFT", ""))
                frequency = _cga_frequency(row.get("CentralFrequency", "0"))
                result.append({
                    "channelID": int(parse_number(row.get("channelid", "0"))),
                    "type": modulation, "frequency": f"{int(frequency)} MHz" if frequency else "",
                    "powerLevel": parse_number(row.get("power", "0")),
                    "mse": -snr if snr else None, "mer": snr if snr else None,
                    "latency": 0, "corrError": 0, "nonCorrError": 0,
                })
            elif lane == "ds31":
                snr = abs(parse_number(row.get("SNR_ofdm", "0")))
                frequency = _cga_frequency(row.get("CentralFrequency_ofdm", "0"))
                result.append({
                    "channelID": int(parse_number(row.get("channelid_ofdm", "0"))),
                    "type": "OFDM", "frequency": f"{int(frequency)} MHz" if frequency else "",
                    "powerLevel": parse_number(row.get("power_ofdm", "0")),
                    "mse": -snr if snr else None, "mer": snr if snr else None,
                    "latency": 0, "corrError": 0, "nonCorrError": 0,
                })
            else:
                frequency = _cga_frequency(row.get("CentralFrequency", "0"))
                modulation = normalize_modulation(row.get("FFT", ""))
                channel: RawChannel = {
                    "channelID": int(parse_number(row.get("channelidup", "0"))),
                    "type": "OFDMA" if lane == "us31" else modulation,
                    "frequency": f"{int(frequency)} MHz" if frequency else "",
                    "powerLevel": parse_number(row.get("power", "0")),
                    "multiplex": "",
                }
                if lane == "us31":
                    channel["modulation"] = modulation or "OFDMA"
                result.append(channel)
        except (ValueError, TypeError):
            diagnostics.append(diagnostic(
                "vodafone_station_cga_json", "invalid_channel", family="vodafone",
                direction="downstream" if lane.startswith("ds") else "upstream", index=index,
            ))
    return ParseResult(result, tuple(diagnostics))


def parse_vodafone_station_cga_json(payload: Any) -> ParseResult[DocsisDataFritz | None]:
    data = payload if isinstance(payload, dict) else {}
    parsed = (
        _parse_cga_lane(data.get("downstream", []) or [], "ds30"),
        _parse_cga_lane(data.get("ofdm_downstream", []) or [], "ds31"),
        _parse_cga_lane(data.get("upstream", []) or [], "us30"),
        _parse_cga_lane(data.get("ofdma_upstream", []) or [], "us31"),
    )
    diagnostics = tuple(item for result in parsed for item in result.diagnostics)
    if any(result.value is None for result in parsed):
        return ParseResult(None, diagnostics)
    return ParseResult(
        docsis_split(
            parsed[0].value,
            parsed[1].value,
            parsed[2].value,
            parsed[3].value,
        ),
        diagnostics,
    )


def parse_tg_power(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if not value or not isinstance(value, str):
        return 0.0
    return parse_number(value.split("/")[0].replace("dBmV", "").replace("dBuV", "").strip())


def parse_tg_frequency(value: Any) -> float:
    if isinstance(value, (int, float)):
        number = float(value)
        return number / 1_000_000 if number > 1_000_000 else number
    if not value or not isinstance(value, str):
        return 0.0
    if "~" in value:
        try:
            start, end = value.split("~", 1)
            number = (float(start.strip()) + float(end.strip())) / 2
            return number / 1_000_000 if number > 1_000_000 else number
        except (ValueError, IndexError):
            return 0.0
    number = parse_number(value)
    return number / 1_000_000 if number > 1_000_000 else number


def parse_vodafone_station_tg_embedded_json(html: str) -> ParseResult[DocsisDataFritz | None]:
    downstream_match = re.search(r"json_dsData\s*=\s*(\[.+?\])\s*;", html or "", re.DOTALL)
    upstream_match = re.search(r"json_usData\s*=\s*(\[.+?\])\s*;", html or "", re.DOTALL)
    if not downstream_match and not upstream_match:
        return ParseResult(None, (diagnostic(
            "vodafone_station_tg_embedded_json", "missing_data", family="vodafone",
        ),))
    try:
        downstream_rows = json.loads(downstream_match.group(1)) if downstream_match else []
        upstream_rows = json.loads(upstream_match.group(1)) if upstream_match else []
    except (json.JSONDecodeError, TypeError):
        return ParseResult(None, (diagnostic(
            "vodafone_station_tg_embedded_json", "invalid_json", family="vodafone",
        ),))

    ds30: list[RawChannel] = []
    ds31: list[RawChannel] = []
    us30: list[RawChannel] = []
    us31: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(downstream_rows):
        try:
            channel_type = row.get("ChannelType", "SC-QAM")
            frequency = parse_tg_frequency(row.get("Frequency", "0"))
            snr = abs(parse_number(row.get("SNRLevel", "0")))
            modulation = normalize_modulation(row.get("Modulation", ""))
            ofdm = "OFDM" in channel_type.upper()
            if ofdm:
                modulation = modulation or "OFDM"
            channel: RawChannel = {
                "channelID": int(float(row.get("ChannelID", 0))), "type": modulation,
                "frequency": f"{frequency:.3f} MHz" if frequency else "",
                "powerLevel": parse_tg_power(row.get("PowerLevel", "0")),
                "mse": -snr if snr else None, "mer": snr if snr else None,
                "latency": 0, "corrError": 0, "nonCorrError": 0,
            }
            (ds31 if ofdm else ds30).append(channel)
        except (ValueError, TypeError, AttributeError):
            diagnostics.append(diagnostic(
                "vodafone_station_tg_embedded_json", "invalid_channel", family="vodafone",
                direction="downstream", index=index,
            ))
    for index, row in enumerate(upstream_rows):
        try:
            channel_type = row.get("ChannelType", "SC-QAM")
            frequency = parse_tg_frequency(row.get("Frequency", "0"))
            modulation = normalize_modulation(row.get("Modulation", ""))
            ofdma = "OFDMA" in channel_type.upper()
            if ofdma:
                modulation = modulation or "OFDMA"
            channel = {
                "channelID": int(float(row.get("ChannelID", 0))), "type": modulation,
                "frequency": f"{frequency:.3f} MHz" if frequency else "",
                "powerLevel": parse_tg_power(row.get("PowerLevel", "0")),
                "multiplex": "",
            }
            (us31 if ofdma else us30).append(channel)
        except (ValueError, TypeError, AttributeError):
            diagnostics.append(diagnostic(
                "vodafone_station_tg_embedded_json", "invalid_channel", family="vodafone",
                direction="upstream", index=index,
            ))
    return ParseResult(docsis_split(ds30, ds31, us30, us31), tuple(diagnostics))
