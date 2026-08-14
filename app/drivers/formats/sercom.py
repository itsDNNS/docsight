"""Pure indexed-node parser for the Sercom DM1000 payload grammar."""

from __future__ import annotations

import math
from typing import Any

from ...types import DocsisDataFritz, RawChannel
from .contract import ParseDiagnostic, ParseResult, diagnostic, docsis_result
from .primitives import hz_to_mhz, normalize_modulation, parse_optional_finite_float


def _issue(direction: str, index: int, field: str | None = None, code: str = "invalid_row") -> ParseDiagnostic:
    return diagnostic(
        "sercom_dm1000_json", code, family="sercom",
        direction=direction, index=index, field=field,
    )


def parse_sercom_ds_scqam(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        try:
            modulation = normalize_modulation(row.get("qamD", ""))
            if not modulation or modulation in {"QAM_NONE", "NONE"}:
                continue
            snr = float(row["SNRD"])
            channels.append({
                "channelID": int(row["DCIDD"]), "frequency": hz_to_mhz(row.get("FreqD", "")),
                "powerLevel": float(row["PowerD"]), "modulation": modulation,
                "mer": snr, "mse": -snr,
                "corrErrors": int(row["correctedsD"]),
                "nonCorrErrors": int(row["uncorrectedsD"]),
            })
        except (KeyError, TypeError, ValueError):
            diagnostics.append(_issue("downstream", index))
    return ParseResult(channels, tuple(diagnostics))


def parse_sercom_ds_ofdm(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        if str(row.get("PLC", "")).strip().upper() != "YES":
            continue
        if str(row.get("MDC1", "")).strip().upper() != "YES":
            continue
        try:
            mer = parse_optional_finite_float(row.get("AV_Data"))
            if mer is None:
                mer = parse_optional_finite_float(row.get("AV_PLC"))
            if mer is None:
                continue
            channels.append({
                "channelID": int(row["num"]), "type": "OFDM",
                "frequency": hz_to_mhz(row.get("OFDMFreq", "")),
                "powerLevel": float(row["PLC_power"]), "modulation": "OFDM",
                "mer": mer, "mse": None, "corrErrors": None, "nonCorrErrors": None,
            })
        except (KeyError, TypeError, ValueError):
            diagnostics.append(_issue("downstream", index))
    return ParseResult(channels, tuple(diagnostics))


def _symbol_rate(value: Any) -> int | None:
    number = parse_optional_finite_float(value)
    return int(round(number * 1000)) if number is not None else None


def parse_sercom_us_scqam(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        try:
            modulation = normalize_modulation(row.get("modulation", ""))
            upstream = str(row.get("upstream", "")).strip()
            rate = str(row.get("rate", "")).strip()
            power = float(row["rep_power"])
            if (
                not modulation or modulation in {"QAM_NONE", "NONE"}
                or upstream in {"", "---"} or not math.isfinite(power)
                or rate.lower() == "invalid"
            ):
                continue
            channel: RawChannel = {
                "channelID": int(upstream), "frequency": hz_to_mhz(row.get("Freq", "")),
                "powerLevel": power, "modulation": modulation, "multiplex": "ATDMA",
            }
            symbol_rate = _symbol_rate(rate)
            if symbol_rate is not None:
                channel["symbolRate"] = symbol_rate
            channels.append(channel)
        except (KeyError, TypeError, ValueError):
            diagnostics.append(_issue("upstream", index))
    return ParseResult(channels, tuple(diagnostics))


def _index_sort_key(name: str) -> int:
    try:
        return int(name.removeprefix("index"))
    except ValueError:
        return 0


def pivot_sercom_indexed_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    pivot: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = str(row.get("name") or "").strip()
        if not name:
            continue
        for key, value in row.items():
            if key.startswith("index"):
                pivot.setdefault(key, {})[name] = value
    return [pivot[key] for key in sorted(pivot, key=_index_sort_key)]


def _profile_modulation(value: Any) -> str | None:
    try:
        bits = int(float(str(value).strip()))
    except (TypeError, ValueError):
        return None
    if bits == 2:
        return "QPSK"
    if bits <= 0 or bits > 12:
        return None
    return f"{2 ** bits}QAM"


def parse_sercom_us_ofdma(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, column in enumerate(pivot_sercom_indexed_rows(rows)):
        state = str(column.get("STATE", "")).strip().upper()
        power_state = str(column.get("Power", "")).strip().upper()
        if power_state != "ON" or state in {"", "DISABLED", "OFF"}:
            continue
        frequency_value = column.get("Center Freq SC0")
        frequency = parse_optional_finite_float(frequency_value)
        if frequency is None or frequency <= 0:
            continue
        try:
            if "rep power1_6" in column:
                power = parse_optional_finite_float(column.get("rep power1_6"))
            else:
                power = None
                diagnostics.append(_issue("upstream", index, "rep power1_6", "missing_field"))
            channel: RawChannel = {
                "channelID": int(str(column.get("CH", "")).strip()), "type": "OFDMA",
                "frequency": hz_to_mhz(frequency_value), "powerLevel": power,
                "modulation": "OFDMA", "multiplex": "OFDMA",
            }
            profile = _profile_modulation(column.get("bit Loading"))
            if profile:
                channel["profile_modulation"] = profile
            channels.append(channel)
        except (KeyError, TypeError, ValueError):
            diagnostics.append(_issue("upstream", index))
    return ParseResult(channels, tuple(diagnostics))


def parse_sercom_dm1000_json(
    payload: dict[str, list[dict[str, Any]]] | None,
) -> ParseResult[DocsisDataFritz]:
    data = payload if isinstance(payload, dict) else {}
    return docsis_result(
        parse_sercom_ds_scqam(data.get("downstream", [])),
        parse_sercom_ds_ofdm(data.get("downstream_ofdm", [])),
        parse_sercom_us_scqam(data.get("upstream", [])),
        parse_sercom_us_ofdma(data.get("upstream_ofdma", [])),
    )
