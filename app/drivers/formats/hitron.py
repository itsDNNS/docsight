"""Pure structured-payload profiles for incompatible Hitron CODA APIs."""

from __future__ import annotations

from collections.abc import Callable
from types import MappingProxyType
from typing import Any

from ...types import DocsisDataFritz, RawChannel
from .contract import ParseDiagnostic, ParseResult, diagnostic, docsis_result
from .primitives import hz_to_mhz, normalize_modulation, parse_optional_finite_float


_CODA56_MODULATION = MappingProxyType({
    0: "16QAM", 1: "64QAM", 2: "256QAM", 3: "1024QAM",
    4: "32QAM", 5: "128QAM", 6: "QPSK",
})


def _invalid(profile: str, direction: str, index: int, field: str | None = None) -> ParseDiagnostic:
    return diagnostic(
        profile, "invalid_row", family="hitron", direction=direction,
        index=index, field=field,
    )


def _parse_rows(
    rows: list[Any],
    profile: str,
    direction: str,
    build: Callable[[dict[str, Any]], RawChannel],
    active: Callable[[dict[str, Any]], bool] | None = None,
) -> ParseResult[list[RawChannel]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            diagnostics.append(_invalid(profile, direction, index))
            continue
        if active is not None and not active(row):
            continue
        try:
            channels.append(build(row))
        except (ValueError, KeyError, TypeError):
            diagnostics.append(_invalid(profile, direction, index))
    return ParseResult(channels, tuple(diagnostics))


def _is_plc_locked(row: dict[str, Any]) -> bool:
    return str(row.get("plclock", "")).strip().upper() == "YES"


def _coda56_ds_scqam(row: dict[str, Any]) -> RawChannel:
    code = int(row.get("modulation", -1))
    snr = float(row["snr"])
    return {
        "channelID": int(row["channelId"]), "frequency": hz_to_mhz(row["frequency"]),
        "powerLevel": float(row["signalStrength"]),
        "modulation": _CODA56_MODULATION.get(code, f"Unknown({code})"),
        "mer": snr, "mse": -snr,
        "corrErrors": int(row["correcteds"]), "nonCorrErrors": int(row["uncorrect"]),
    }


def _coda56_us_scqam(row: dict[str, Any]) -> RawChannel:
    return {
        "channelID": int(row["channelId"]), "frequency": hz_to_mhz(row["frequency"]),
        "powerLevel": float(row["signalStrength"]),
        "modulation": row.get("modtype", ""), "multiplex": row.get("scdmaMode", ""),
    }


def _coda56_ds_ofdm(row: dict[str, Any]) -> RawChannel:
    return {
        "channelID": int(row["receive"]), "type": "OFDM",
        "frequency": hz_to_mhz(row.get("Subcarr0freqFreq", "0")),
        "powerLevel": float(row["plcpower"]), "modulation": "OFDM",
        "mer": float(row["SNR"]), "mse": None,
        "corrErrors": int(row["correcteds"]), "nonCorrErrors": int(row["uncorrect"]),
    }


def parse_coda56_ds_scqam(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    return _parse_rows(rows, "hitron_coda56_json", "downstream", _coda56_ds_scqam)


def parse_coda56_us_scqam(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    return _parse_rows(rows, "hitron_coda56_json", "upstream", _coda56_us_scqam)


def parse_coda56_ds_ofdm(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    return _parse_rows(
        rows,
        "hitron_coda56_json",
        "downstream",
        _coda56_ds_ofdm,
        _is_plc_locked,
    )


def _ofdma_power(row: dict[str, Any], profile: str, index: int) -> tuple[float | None, ParseDiagnostic | None]:
    if "repPower1_6" not in row:
        return None, diagnostic(
            profile, "missing_field", family="hitron", direction="upstream",
            index=index, field="repPower1_6",
        )
    return parse_optional_finite_float(row.get("repPower1_6")), None


def parse_hitron_ofdma_power(row: dict[str, Any]) -> float | None:
    return parse_optional_finite_float(row.get("repPower1_6")) if "repPower1_6" in row else None


def parse_coda56_us_ofdma(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        if str(row.get("state", "")).strip().upper() != "OPERATE":
            continue
        try:
            power, issue = _ofdma_power(row, "hitron_coda56_json", index)
            if issue:
                diagnostics.append(issue)
            channels.append({
                "channelID": int(row["uschindex"]), "type": "OFDMA",
                "frequency": hz_to_mhz(row.get("frequency", "0")),
                "powerLevel": power, "modulation": "OFDMA", "multiplex": "",
            })
        except (ValueError, KeyError, TypeError):
            diagnostics.append(_invalid("hitron_coda56_json", "upstream", index))
    return ParseResult(channels, tuple(diagnostics))


def parse_hitron_coda56_json(
    payloads: dict[str, list[dict[str, Any]]] | None,
) -> ParseResult[DocsisDataFritz]:
    data = payloads if isinstance(payloads, dict) else {}
    return docsis_result(
        parse_coda56_ds_scqam(data.get("downstream", [])),
        parse_coda56_ds_ofdm(data.get("downstream_ofdm", [])),
        parse_coda56_us_scqam(data.get("upstream", [])),
        parse_coda56_us_ofdma(data.get("upstream_ofdma", [])),
    )


def _coda4680_ds_scqam(row: dict[str, Any]) -> RawChannel:
    snr = float(row["snr"])
    return {
        "channelID": int(row["channelId"]), "frequency": hz_to_mhz(row["frequency"]),
        "powerLevel": float(row["signalStrength"]),
        "modulation": normalize_modulation(row.get("modulation", "")),
        "mer": snr, "mse": -snr,
        "corrErrors": int(row["correcteds"]), "nonCorrErrors": int(row["uncorrect"]),
    }


def _coda4680_us_scqam(row: dict[str, Any]) -> RawChannel:
    modulation = normalize_modulation(row.get("modulationType") or row.get("modtype") or "")
    channel: RawChannel = {
        "channelID": int(row["channelId"]), "frequency": hz_to_mhz(row["frequency"]),
        "powerLevel": float(row["signalStrength"]), "modulation": modulation,
        "multiplex": "ATDMA",
    }
    if row.get("symbolrate") is not None:
        channel["symbolRate"] = int(row["symbolrate"])
    return channel


def _coda4680_ds_ofdm(row: dict[str, Any]) -> RawChannel:
    return {
        "channelID": int(row["receive"]), "type": "OFDM",
        "frequency": hz_to_mhz(row.get("Subcarr0freqFreq", "")),
        "powerLevel": float(row["plcpower"]), "modulation": "OFDM",
        "mer": None, "mse": None, "corrErrors": None, "nonCorrErrors": None,
    }


def parse_coda4680_ds_scqam(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    return _parse_rows(rows, "hitron_coda4680_json", "downstream", _coda4680_ds_scqam)


def parse_coda4680_us_scqam(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    return _parse_rows(rows, "hitron_coda4680_json", "upstream", _coda4680_us_scqam)


def parse_coda4680_ds_ofdm(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    return _parse_rows(
        rows,
        "hitron_coda4680_json",
        "downstream",
        _coda4680_ds_ofdm,
        _is_plc_locked,
    )


def parse_coda4680_us_ofdma(rows: list[dict[str, Any]]) -> ParseResult[list[RawChannel]]:
    channels: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        if str(row.get("state", "")).strip().upper() != "OPERATE":
            continue
        try:
            power, issue = _ofdma_power(row, "hitron_coda4680_json", index)
            if issue:
                diagnostics.append(issue)
            channels.append({
                "channelID": int(row["uschindex"]), "type": "OFDMA",
                # This API does not expose OFDMA center frequency.
                "frequency": "", "powerLevel": power,
                "modulation": "OFDMA", "multiplex": "OFDMA",
            })
        except (KeyError, TypeError, ValueError):
            diagnostics.append(_invalid("hitron_coda4680_json", "upstream", index))
    return ParseResult(channels, tuple(diagnostics))


def parse_hitron_coda4680_json(
    payloads: dict[str, dict[str, Any]] | None,
) -> ParseResult[DocsisDataFritz]:
    data = payloads if isinstance(payloads, dict) else {}
    return docsis_result(
        parse_coda4680_ds_scqam(data.get("downstream", {}).get("Freq_List", [])),
        parse_coda4680_ds_ofdm(data.get("downstream_ofdm", {}).get("OFDMs_List", [])),
        parse_coda4680_us_scqam(data.get("upstream", {}).get("Freq_List", [])),
        parse_coda4680_us_ofdma(data.get("upstream_ofdma", {}).get("OFDMAs_List", [])),
    )
