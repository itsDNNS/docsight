"""Pure profiles for Vodafone CGA, TG embedded JSON, and Ultra Hub payloads."""

from __future__ import annotations

import json
import math
import re
from typing import Any

from ...types import DocsisDataFritz, RawChannel
from .contract import ParseDiagnostic, ParseResult, diagnostic, docsis_split
from .primitives import normalize_modulation, parse_number


def _reading(value: Any) -> float | None:
    """Leading finite number of a reading; missing or unreadable is None, numeric zero is 0.0."""
    return None if isinstance(value, bool) else parse_number("0" if value == 0 else str(value or ""))


def _number_or_zero(value: str) -> float:
    """Leading number of an ID or frequency; missing or unreadable text keeps the 0 its channel history uses."""
    try:
        return float(value.split()[0])
    except (IndexError, ValueError):
        return 0.0


def parse_ultrahub7_downstream(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        try:
            channel_id = int(row.get("ChannelID", "0"))
            frequency = _number_or_zero(str(row.get("Frequency") or ""))
            modulation = str(row.get("Modulation", "") or "").upper().replace("-", "")
            power = _reading(row.get("PowerLevel"))
            snr = _reading(row.get("SNRLevel")) or 0
            channels.append({
                "channelID": str(channel_id), "type": modulation,
                "frequency": f"{int(frequency)} MHz", "powerLevel": power,
                "mer": snr if snr > 0 else None, "mse": None, "latency": 0,
                "corrErrors": None, "nonCorrErrors": None,
            })
        except (ValueError, TypeError, OverflowError):
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
            frequency = _number_or_zero(str(row.get("Frequency") or ""))
            modulation = str(row.get("Modulation", "") or "").upper().replace("-", "")
            channels.append({
                "channelID": str(channel_id), "type": modulation,
                "frequency": f"{int(frequency)} MHz",
                "powerLevel": _reading(row.get("PowerLevel")),
                "multiplex": "",
            })
        except (ValueError, TypeError, OverflowError):
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


def _frequency_mhz(value: Any) -> float:
    """Hz or MHz reading as MHz; missing or unreadable is 0, a malformed or non-finite value raises."""
    number = _number_or_zero(value) if isinstance(value, str) else float(value or 0)
    if not math.isfinite(number):
        raise ValueError("non-finite frequency")
    return number / 1_000_000 if number > 1_000_000 else number


def _cga_channel_id(value: Any) -> int:
    # null reads like a missing ID (channel 0); other non-numeric types are invalid
    if isinstance(value, bool) or not isinstance(value, (int, float, str, type(None))):
        raise TypeError("unsupported channel ID")
    return int(_number_or_zero(str(value)))


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
                snr = abs(_reading(row.get("SNR")) or 0)
                modulation = normalize_modulation(row.get("FFT", ""))
                frequency = _frequency_mhz(row.get("CentralFrequency", "0"))
                result.append({
                    "channelID": _cga_channel_id(row.get("channelid", "0")),
                    "type": modulation, "frequency": f"{int(frequency)} MHz" if frequency else "",
                    "powerLevel": _reading(row.get("power")),
                    "mse": -snr if snr else None, "mer": snr if snr else None,
                    "latency": 0, "corrError": 0, "nonCorrError": 0,
                })
            elif lane == "ds31":
                snr = abs(_reading(row.get("SNR_ofdm")) or 0)
                frequency = _frequency_mhz(row.get("CentralFrequency_ofdm", "0"))
                result.append({
                    "channelID": _cga_channel_id(row.get("channelid_ofdm", "0")),
                    "type": "OFDM", "frequency": f"{int(frequency)} MHz" if frequency else "",
                    "powerLevel": _reading(row.get("power_ofdm")),
                    "mse": -snr if snr else None, "mer": snr if snr else None,
                    "latency": 0, "corrError": 0, "nonCorrError": 0,
                })
            else:
                frequency = _frequency_mhz(row.get("CentralFrequency", "0"))
                modulation = normalize_modulation(row.get("FFT", ""))
                channel: RawChannel = {
                    "channelID": _cga_channel_id(row.get("channelidup", "0")),
                    "type": "OFDMA" if lane == "us31" else modulation,
                    "frequency": f"{int(frequency)} MHz" if frequency else "",
                    "powerLevel": _reading(row.get("power")),
                    "multiplex": "",
                }
                if lane == "us31":
                    channel["modulation"] = modulation or "OFDMA"
                result.append(channel)
        except (ValueError, TypeError, OverflowError):
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


def parse_tg_power(value: Any) -> float | None:
    if isinstance(value, str):
        value = value.split("/")[0].replace("dBmV", "").replace("dBuV", "")
    return _reading(value)


def parse_tg_frequency(value: Any) -> float:
    if not isinstance(value, (str, int, float)):
        return 0.0
    if isinstance(value, str) and "~" in value:
        start, end = value.split("~", 1)
        try:
            value = (float(start) + float(end)) / 2
        except ValueError:
            return 0.0
    return _frequency_mhz(value)


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
            snr = abs(_reading(row.get("SNRLevel")) or 0)
            modulation = normalize_modulation(row.get("Modulation", ""))
            ofdm = "OFDM" in channel_type.upper()
            if ofdm:
                modulation = modulation or "OFDM"
            channel: RawChannel = {
                "channelID": int(float(row.get("ChannelID", 0))), "type": modulation,
                "frequency": f"{frequency:.3f} MHz" if frequency else "",
                "powerLevel": parse_tg_power(row.get("PowerLevel")),
                "mse": -snr if snr else None, "mer": snr if snr else None,
                "latency": 0, "corrError": 0, "nonCorrError": 0,
            }
            (ds31 if ofdm else ds30).append(channel)
        except (ValueError, TypeError, AttributeError, OverflowError):
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
                "powerLevel": parse_tg_power(row.get("PowerLevel")),
                "multiplex": "",
            }
            (us31 if ofdma else us30).append(channel)
        except (ValueError, TypeError, AttributeError, OverflowError):
            diagnostics.append(diagnostic(
                "vodafone_station_tg_embedded_json", "invalid_channel", family="vodafone",
                direction="upstream", index=index,
            ))
    return ParseResult(docsis_split(ds30, ds31, us30, us31), tuple(diagnostics))
