"""Pure parser for the CGM4981 columnar section-vector profile."""

from __future__ import annotations

import re

from ...docsis_utils import parse_qam_order, to_float
from ...types import DocsisDataFritz, RawChannel
from .contract import ParseDiagnostic, ParseResult, diagnostic, number_reader


_TR = re.compile(r"<tr[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
_TH = re.compile(r"<th[^>]*>(.*?)</(?:th|td)>", re.DOTALL | re.IGNORECASE)
_NETWIDTH = re.compile(r'<div[^>]*class="netWidth"[^>]*>(.*?)</div>', re.DOTALL)
_STRIP = re.compile(r"<[^>]+>")
_NUMBER = re.compile(r"-?\d+\.?\d*")


def _text(html: str) -> str:
    return _STRIP.sub("", html).strip()


def _float(raw: str) -> float | None:
    match = _NUMBER.search(raw.strip())
    return to_float(match.group()) if match else None


def _frequency(raw: str) -> str:
    raw = raw.strip()
    value = _float(raw)
    if value is None:
        return "" if _NUMBER.search(raw) else raw
    if value > 1_000_000 and not re.search(r"[Mm][Hh][Zz]", raw):
        value /= 1_000_000
    return f"{int(value) if value == int(value) else value} MHz"


def _modulation(raw: str) -> str:
    upper = raw.strip().upper()
    if "OFDMA" in upper:
        return "OFDMA"
    if "OFDM" in upper:
        return "OFDM"
    order = parse_qam_order(upper)
    if order is not None:
        return f"{order}QAM"
    if "QAM" in upper:
        return "QAM"
    return raw.strip()


def section_rows(html: str) -> dict[str, list[str]]:
    rows: dict[str, list[str]] = {}
    for row_match in _TR.finditer(html or ""):
        row = row_match.group(1)
        heading = _TH.search(row)
        if not heading:
            continue
        label = _text(heading.group(1))
        values = [_text(value) for value in _NETWIDTH.findall(row)]
        if label and values:
            rows[label] = values
    return rows


def split_sections(html: str) -> tuple[str, str, str]:
    downstream = html.find(">Downstream<")
    upstream = html.find(">Upstream<")
    errors = html.find("CM Error Codewords")
    return (
        html[downstream:upstream] if downstream >= 0 and upstream > downstream else "",
        html[upstream:errors] if upstream >= 0 and errors > upstream else "",
        html[errors:] if errors >= 0 else "",
    )


def build_cgm4981_downstream(
    rows: dict[str, list[str]],
    error_rows: dict[str, list[str]],
) -> ParseResult[list[RawChannel]]:
    channel_ids = rows.get("Channel ID", [])
    locks = rows.get("Lock Status", [])
    frequencies = rows.get("Frequency", [])
    snrs = rows.get("SNR", [])
    powers = rows.get("Power Level", [])
    modulations = rows.get("Modulation", [])
    error_ids = error_rows.get("Channel ID", [])
    corrected = error_rows.get("Correctable Codewords", [])
    uncorrected = error_rows.get("Uncorrectable Codewords", [])
    error_map = {
        channel_id: tuple(values[index] if index < len(values) else "" for values in (corrected, uncorrected))
        for index, channel_id in enumerate(error_ids)
    }

    result: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, channel_id in enumerate(channel_ids):
        if (locks[index] if index < len(locks) else "").lower() != "locked":
            continue
        num = number_reader(
            diagnostics, "cgm4981_columnar_html", family="html_columnar", direction="downstream", index=index,
        )
        try:
            modulation = _modulation(modulations[index] if index < len(modulations) else "")
            snr = _float(snrs[index] if index < len(snrs) else "")
            corr, uncorr = error_map.get(channel_id, ("", ""))
            channel: RawChannel = {
                "channelID": int(channel_id),
                "frequency": _frequency(frequencies[index] if index < len(frequencies) else ""),
                "powerLevel": _float(powers[index] if index < len(powers) else ""),
                "mer": snr,
                "mse": None if snr is None else -snr,
                "modulation": modulation,
                "corrErrors": num(corr, "corrected", int),
                "nonCorrErrors": num(uncorr, "uncorrected", int),
            }
            if modulation == "OFDM":
                channel["type"] = "OFDM"
            result.append(channel)
        except (ValueError, IndexError):
            diagnostics.append(diagnostic(
                "cgm4981_columnar_html", "invalid_channel", family="html_columnar",
                direction="downstream", index=index,
            ))
    return ParseResult(result, tuple(diagnostics))


def build_cgm4981_upstream(rows: dict[str, list[str]]) -> ParseResult[list[RawChannel]]:
    channel_ids = rows.get("Channel ID", [])
    locks = rows.get("Lock Status", [])
    frequencies = rows.get("Frequency", [])
    powers = rows.get("Power Level", [])
    modulations = rows.get("Modulation", [])
    channel_types = rows.get("Channel Type", [])
    result: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, channel_id in enumerate(channel_ids):
        if (locks[index] if index < len(locks) else "").lower() != "locked":
            continue
        try:
            modulation = _modulation(modulations[index] if index < len(modulations) else "")
            raw_type = channel_types[index] if index < len(channel_types) else ""
            channel: RawChannel = {
                "channelID": int(channel_id),
                "frequency": _frequency(frequencies[index] if index < len(frequencies) else ""),
                "powerLevel": _float(powers[index] if index < len(powers) else ""),
                "modulation": modulation,
                "multiplex": raw_type.upper() or modulation,
            }
            if modulation == "OFDMA":
                channel["type"] = "OFDMA"
            result.append(channel)
        except (ValueError, IndexError):
            diagnostics.append(diagnostic(
                "cgm4981_columnar_html", "invalid_channel", family="html_columnar",
                direction="upstream", index=index,
            ))
    return ParseResult(result, tuple(diagnostics))


def parse_cgm4981_columnar_html(html: str) -> ParseResult[DocsisDataFritz]:
    downstream_html, upstream_html, errors_html = split_sections(html or "")
    downstream = build_cgm4981_downstream(section_rows(downstream_html), section_rows(errors_html))
    upstream = build_cgm4981_upstream(section_rows(upstream_html))
    return ParseResult({
        "channelDs": {
            "docsis30": [item for item in downstream.value if item.get("modulation") != "OFDM"],
            "docsis31": [item for item in downstream.value if item.get("modulation") == "OFDM"],
        },
        "channelUs": {
            "docsis30": [item for item in upstream.value if item.get("modulation") != "OFDMA"],
            "docsis31": [item for item in upstream.value if item.get("modulation") == "OFDMA"],
        },
    }, downstream.diagnostics + upstream.diagnostics)
