"""Pure profiles for the incompatible Sagemcom XMO and F3896LG REST payloads."""

from __future__ import annotations

from typing import Any

from ...types import DocsisDataFritz, RawChannel
from .contract import ParseDiagnostic, ParseResult, diagnostic, docsis_split
from .primitives import hz_to_mhz


def _sagemcom_frequency(value: object) -> str:
    return hz_to_mhz(value) if value else ""


def _sagemcom_modulation(value: str) -> str:
    if not value:
        return ""
    stripped = value.strip()
    return f"{stripped[3:]}QAM" if stripped.lower().startswith("qam") else stripped


def _sagemcom_is_ofdm(modulation: str, bandwidth: int) -> bool:
    return bool(bandwidth and bandwidth > 8_000_000) or bool(
        modulation and modulation.startswith("256-QAM")
    )


def parse_sagemcom_xmo_downstream(
    rows: list[Any],
) -> ParseResult[tuple[list[RawChannel], list[RawChannel]]]:
    docsis30: list[RawChannel] = []
    docsis31: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            diagnostics.append(diagnostic(
                "sagemcom_xmo_json", "invalid_channel", family="sagemcom",
                direction="downstream", index=index,
            ))
            continue
        if not row.get("LockStatus", False):
            continue
        try:
            channel_id = row.get("ChannelID", 0)
            frequency = _sagemcom_frequency(row.get("Frequency", 0))
            power = row.get("PowerLevel", 0)
            snr = row.get("SNR", 0)
            modulation = row.get("Modulation", "")
            corrected = row.get("CorrectableCodewords", 0)
            uncorrected = row.get("UncorrectableCodewords", 0)
            if _sagemcom_is_ofdm(modulation, row.get("BandWidth", 0)):
                docsis31.append({
                    "channelID": channel_id, "type": "OFDM", "frequency": frequency,
                    "powerLevel": power, "mer": snr, "mse": None,
                    "corrErrors": corrected, "nonCorrErrors": uncorrected,
                })
            else:
                docsis30.append({
                    "channelID": channel_id, "frequency": frequency, "powerLevel": power,
                    "mer": snr, "mse": -snr if snr else None,
                    "modulation": _sagemcom_modulation(modulation),
                    "corrErrors": corrected, "nonCorrErrors": uncorrected,
                })
        except (ValueError, TypeError):
            diagnostics.append(diagnostic(
                "sagemcom_xmo_json", "invalid_channel", family="sagemcom",
                direction="downstream", index=index,
            ))
    return ParseResult((docsis30, docsis31), tuple(diagnostics))


def parse_sagemcom_xmo_upstream(
    rows: list[Any],
) -> ParseResult[tuple[list[RawChannel], list[RawChannel]] | None]:
    docsis30: list[RawChannel] = []
    docsis31: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            diagnostics.append(diagnostic(
                "sagemcom_xmo_json", "invalid_channel", family="sagemcom",
                direction="upstream", index=index,
            ))
            continue
        if not row.get("LockStatus", False):
            continue
        try:
            channel_id = row.get("ChannelID", 0)
            frequency = _sagemcom_frequency(row.get("Frequency", 0))
            power = row.get("PowerLevel", 0)
            modulation = row.get("Modulation", "")
            if not isinstance(modulation, str):
                diagnostics.append(diagnostic(
                    "sagemcom_xmo_json", "invalid_field", family="sagemcom",
                    direction="upstream", index=index, field="Modulation",
                ))
                return ParseResult(None, tuple(diagnostics))
            if modulation.lower() == "ofdma":
                docsis31.append({
                    "channelID": channel_id, "type": "OFDMA", "frequency": frequency,
                    "powerLevel": power, "modulation": "OFDMA", "multiplex": "",
                })
            else:
                docsis30.append({
                    "channelID": channel_id, "frequency": frequency, "powerLevel": power,
                    "modulation": modulation.strip().upper() if modulation else "",
                    "multiplex": modulation.upper() if modulation else "",
                })
        except (ValueError, TypeError):
            diagnostics.append(diagnostic(
                "sagemcom_xmo_json", "invalid_channel", family="sagemcom",
                direction="upstream", index=index,
            ))
    return ParseResult((docsis30, docsis31), tuple(diagnostics))


def parse_sagemcom_xmo_json(
    payload: dict[str, list[dict[str, Any]]] | None,
) -> ParseResult[DocsisDataFritz | None]:
    data = payload if isinstance(payload, dict) else {}
    downstream = parse_sagemcom_xmo_downstream(data.get("downstream", []))
    upstream = parse_sagemcom_xmo_upstream(data.get("upstream", []))
    if upstream.value is None:
        return ParseResult(None, downstream.diagnostics + upstream.diagnostics)
    return ParseResult(
        docsis_split(*downstream.value, *upstream.value),
        downstream.diagnostics + upstream.diagnostics,
    )


def _f3896_frequency(value: object) -> str:
    return "" if not value else f"{float(value) / 1_000_000:g} MHz"


def _f3896_unscale(value: object) -> float | None:
    return None if value is None else float(value) / 10.0


def _f3896_modulation(value: str) -> str:
    raw = (value or "").lower()
    return f"{raw[4:]}QAM" if raw.startswith("qam_") else raw.upper()


def parse_f3896lg_downstream(rows: list[dict[str, Any]]) -> ParseResult[tuple[list[RawChannel], list[RawChannel]]]:
    docsis30: list[RawChannel] = []
    docsis31: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not row.get("lockStatus", False):
            continue
        channel_type = row.get("channelType")
        if channel_type not in {"sc_qam", "ofdm"}:
            diagnostics.append(diagnostic(
                "f3896lg_rest_json", "unknown_channel_type", family="sagemcom",
                direction="downstream", index=index, field="channelType",
            ))
            continue
        try:
            mer = row.get("rxMer")
            if channel_type == "ofdm":
                try:
                    power = _f3896_unscale(row.get("power"))
                except (ValueError, TypeError):
                    power = None
                    diagnostics.append(diagnostic(
                        "f3896lg_rest_json", "invalid_field", family="sagemcom",
                        direction="downstream", index=index, field="power",
                    ))
                try:
                    mer = _f3896_unscale(mer)
                except (ValueError, TypeError):
                    mer = None
                    diagnostics.append(diagnostic(
                        "f3896lg_rest_json", "invalid_field", family="sagemcom",
                        direction="downstream", index=index, field="rxMer",
                    ))
                if mer == 0:
                    mer = None
                channel: RawChannel = {
                    "channelID": row.get("channelId", 0), "type": "OFDM", "frequency": "",
                    "powerLevel": power, "mer": mer, "mse": None, "modulation": "OFDM",
                    "corrErrors": row.get("correctedErrors"),
                    "nonCorrErrors": row.get("uncorrectedErrors"),
                }
                profile = _f3896_modulation(row.get("modulation", ""))
                if profile:
                    channel["profile_modulation"] = profile
                docsis31.append(channel)
            else:
                snr = row.get("snr") or mer
                docsis30.append({
                    "channelID": row.get("channelId", 0),
                    "frequency": _f3896_frequency(row.get("frequency")),
                    "powerLevel": row.get("power"), "mer": snr,
                    "mse": -snr if snr else None,
                    "modulation": _f3896_modulation(row.get("modulation", "")),
                    "corrErrors": row.get("correctedErrors"),
                    "nonCorrErrors": row.get("uncorrectedErrors"),
                })
        except (ValueError, TypeError):
            diagnostics.append(diagnostic(
                "f3896lg_rest_json", "invalid_channel", family="sagemcom",
                direction="downstream", index=index,
            ))
    return ParseResult((docsis30, docsis31), tuple(diagnostics))


def parse_f3896lg_upstream(rows: list[dict[str, Any]]) -> ParseResult[tuple[list[RawChannel], list[RawChannel]]]:
    docsis30: list[RawChannel] = []
    docsis31: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict) or not row.get("lockStatus", False):
            continue
        channel_type = row.get("channelType")
        if channel_type not in {"atdma", "ofdma"}:
            diagnostics.append(diagnostic(
                "f3896lg_rest_json", "unknown_channel_type", family="sagemcom",
                direction="upstream", index=index, field="channelType",
            ))
            continue
        try:
            if channel_type == "ofdma":
                try:
                    power = _f3896_unscale(row.get("power"))
                except (ValueError, TypeError):
                    power = None
                    diagnostics.append(diagnostic(
                        "f3896lg_rest_json", "invalid_field", family="sagemcom",
                        direction="upstream", index=index, field="power",
                    ))
                channel: RawChannel = {
                    "channelID": row.get("channelId", 0), "type": "OFDMA", "frequency": "",
                    "powerLevel": power, "modulation": "OFDMA", "multiplex": "",
                }
                profile = _f3896_modulation(row.get("modulation", ""))
                if profile:
                    channel["profile_modulation"] = profile
                docsis31.append(channel)
            else:
                docsis30.append({
                    "channelID": row.get("channelId", 0),
                    "frequency": _f3896_frequency(row.get("frequency")),
                    "powerLevel": row.get("power"),
                    "modulation": _f3896_modulation(row.get("modulation", "")),
                    "multiplex": str(row.get("channelType", "")).upper(),
                    "symbolRate": row.get("symbolRate"),
                })
        except (ValueError, TypeError):
            diagnostics.append(diagnostic(
                "f3896lg_rest_json", "invalid_channel", family="sagemcom",
                direction="upstream", index=index,
            ))
    return ParseResult((docsis30, docsis31), tuple(diagnostics))


def parse_f3896lg_rest_json(
    payload: dict[str, list[dict[str, Any]]] | None,
) -> ParseResult[DocsisDataFritz]:
    data = payload if isinstance(payload, dict) else {}
    downstream = parse_f3896lg_downstream(data.get("downstream", []))
    upstream = parse_f3896lg_upstream(data.get("upstream", []))
    return ParseResult(
        docsis_split(*downstream.value, *upstream.value),
        downstream.diagnostics + upstream.diagnostics,
    )
