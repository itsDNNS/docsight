"""Pure parser for the SB6141 transposed metric-table profile."""

from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from ...types import DocsisDataFritz, RawChannel
from .contract import ParseDiagnostic, ParseResult, diagnostic, docsis_split
from .primitives import hz_to_mhz, parse_number


def extract_transposed_rows(table: Tag | None) -> list[tuple[str, list[str]]]:
    if not table:
        return []
    rows: list[tuple[str, list[str]]] = []
    for row in table.find_all("tr"):
        if row.find("th"):
            continue
        cells = row.find_all("td", recursive=False)
        if len(cells) >= 2:
            rows.append((
                cells[0].get_text(strip=True),
                [cell.get_text(strip=True) for cell in cells[1:]],
            ))
    return rows


def get_row_values(rows: list[tuple[str, list[str]]], keyword: str) -> list[str]:
    keyword = keyword.lower()
    for label, values in rows:
        if keyword in label.lower():
            return values
    return []


def extract_upstream_modulation(raw: str) -> str:
    if not raw:
        return ""
    last = ""
    for part in re.split(r"[\n\r]+", raw.strip()):
        cleaned = re.sub(r"^\[\d+\]\s*", "", part.strip())
        if cleaned:
            last = cleaned
    return last


def parse_sb6141_downstream(
    downstream_table: Tag | None,
    codeword_table: Tag | None,
) -> ParseResult[list[RawChannel]]:
    if not downstream_table:
        return ParseResult([])
    rows = extract_transposed_rows(downstream_table)
    channel_ids = get_row_values(rows, "channel id")
    frequencies = get_row_values(rows, "frequency")
    snrs = get_row_values(rows, "signal to noise")
    modulations = get_row_values(rows, "modulation")
    powers = get_row_values(rows, "power level")
    corrected: list[str] = []
    uncorrected: list[str] = []
    if codeword_table:
        codewords = extract_transposed_rows(codeword_table)
        corrected = get_row_values(codewords, "correctable")
        uncorrected = get_row_values(codewords, "uncorrectable")

    result: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, raw_channel_id in enumerate(channel_ids):
        try:
            snr = parse_number(snrs[index] if index < len(snrs) else "")
            result.append({
                "channelID": int(raw_channel_id),
                "frequency": hz_to_mhz(frequencies[index] if index < len(frequencies) else ""),
                "powerLevel": parse_number(powers[index] if index < len(powers) else ""),
                "mer": snr,
                "mse": -snr if snr else None,
                "modulation": modulations[index].strip() if index < len(modulations) else "",
                # Missing codewords deliberately remain zero for this profile.
                "corrErrors": int(parse_number(corrected[index])) if index < len(corrected) else 0,
                "nonCorrErrors": int(parse_number(uncorrected[index])) if index < len(uncorrected) else 0,
            })
        except (ValueError, TypeError, IndexError):
            diagnostics.append(diagnostic(
                "sb6141_transposed_html", "invalid_channel", family="html_transposed",
                direction="downstream", index=index,
            ))
    return ParseResult(result, tuple(diagnostics))


def parse_sb6141_upstream(upstream_table: Tag | None) -> ParseResult[list[RawChannel]]:
    if not upstream_table:
        return ParseResult([])
    rows = extract_transposed_rows(upstream_table)
    channel_ids = get_row_values(rows, "channel id")
    frequencies = get_row_values(rows, "frequency")
    powers = get_row_values(rows, "power level")
    modulations = get_row_values(rows, "modulation")
    result: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, raw_channel_id in enumerate(channel_ids):
        try:
            result.append({
                "channelID": int(raw_channel_id),
                "frequency": hz_to_mhz(frequencies[index] if index < len(frequencies) else ""),
                "powerLevel": parse_number(powers[index] if index < len(powers) else ""),
                "modulation": extract_upstream_modulation(
                    modulations[index] if index < len(modulations) else ""
                ),
                "multiplex": "SC-QAM",
            })
        except (ValueError, TypeError, IndexError):
            diagnostics.append(diagnostic(
                "sb6141_transposed_html", "invalid_channel", family="html_transposed",
                direction="upstream", index=index,
            ))
    return ParseResult(result, tuple(diagnostics))


def parse_sb6141_transposed_html(html: str) -> ParseResult[DocsisDataFritz]:
    soup = BeautifulSoup(html or "", "html.parser")
    downstream = upstream = codewords = None
    for table in soup.find_all("table"):
        heading = table.find("th")
        text = heading.get_text(" ", strip=True).lower() if heading else ""
        if "downstream" in text and "signal" not in text:
            downstream = table
        elif "upstream" in text:
            upstream = table
        elif "signal status" in text or "codeword" in text:
            codewords = table
    ds = parse_sb6141_downstream(downstream, codewords)
    us = parse_sb6141_upstream(upstream)
    return ParseResult(
        docsis_split(ds.value, [], us.value, []),
        ds.diagnostics + us.diagnostics,
    )
