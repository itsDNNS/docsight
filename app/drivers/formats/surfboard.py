"""Pure parser for Surfboard HNAP channel strings."""

from __future__ import annotations

from ...types import DocsisDataFritz, RawChannel
from .contract import ParseDiagnostic, ParseResult, diagnostic, docsis_split
from .primitives import hz_to_mhz


_DOWNSTREAM_FIELDS = 9
_UPSTREAM_FIELDS = 7


def normalize_surfboard_modulation(value: str) -> str:
    return value.strip() if value else ""


def parse_surfboard_downstream(raw: str) -> ParseResult[tuple[list[RawChannel], list[RawChannel]]]:
    docsis30: list[RawChannel] = []
    docsis31: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, entry in enumerate((raw or "").split("|+|")):
        if not entry.strip():
            continue
        fields = entry.strip().split("^")
        if fields and fields[-1] == "":
            fields.pop()
        if len(fields) < _DOWNSTREAM_FIELDS or fields[1].strip() != "Locked":
            continue
        try:
            modulation = normalize_surfboard_modulation(fields[2])
            channel_id = int(fields[3])
            frequency = hz_to_mhz(int(fields[4]))
            power = float(fields[5].strip())
            snr = float(fields[6].strip())
            corrected = int(fields[7])
            uncorrected = int(fields[8])
            if "OFDM" in modulation.upper():
                docsis31.append({
                    "channelID": channel_id, "type": "OFDM", "frequency": frequency,
                    "powerLevel": power, "mer": snr, "mse": None,
                    "corrErrors": corrected, "nonCorrErrors": uncorrected,
                })
            else:
                docsis30.append({
                    "channelID": channel_id, "frequency": frequency, "powerLevel": power,
                    "mer": snr, "mse": -snr, "modulation": modulation,
                    "corrErrors": corrected, "nonCorrErrors": uncorrected,
                })
        except (ValueError, IndexError):
            diagnostics.append(diagnostic(
                "surfboard_hnap", "invalid_channel", family="surfboard",
                direction="downstream", index=index,
            ))
    return ParseResult((docsis30, docsis31), tuple(diagnostics))


def parse_surfboard_upstream(raw: str) -> ParseResult[tuple[list[RawChannel], list[RawChannel]]]:
    docsis30: list[RawChannel] = []
    docsis31: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, entry in enumerate((raw or "").split("|+|")):
        if not entry.strip():
            continue
        fields = entry.strip().split("^")
        if fields and fields[-1] == "":
            fields.pop()
        if len(fields) < _UPSTREAM_FIELDS or fields[1].strip() != "Locked":
            continue
        try:
            channel_type = normalize_surfboard_modulation(fields[2])
            channel_id = int(fields[3])
            frequency = hz_to_mhz(int(fields[5]))
            power = float(fields[6].strip())
            if "OFDMA" in channel_type.upper():
                docsis31.append({
                    "channelID": channel_id, "type": "OFDMA", "frequency": frequency,
                    "powerLevel": power, "modulation": "OFDMA", "multiplex": "",
                })
            else:
                docsis30.append({
                    "channelID": channel_id, "frequency": frequency, "powerLevel": power,
                    "modulation": channel_type, "multiplex": channel_type,
                })
        except (ValueError, IndexError):
            diagnostics.append(diagnostic(
                "surfboard_hnap", "invalid_channel", family="surfboard",
                direction="upstream", index=index,
            ))
    return ParseResult((docsis30, docsis31), tuple(diagnostics))


def parse_surfboard_hnap(downstream_raw: str, upstream_raw: str) -> ParseResult[DocsisDataFritz]:
    downstream = parse_surfboard_downstream(downstream_raw)
    upstream = parse_surfboard_upstream(upstream_raw)
    return ParseResult(
        docsis_split(*downstream.value, *upstream.value),
        downstream.diagnostics + upstream.diagnostics,
    )
