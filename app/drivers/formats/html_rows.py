"""Explicit parsers for compatible row-oriented modem HTML profiles."""

from __future__ import annotations

import re
from collections.abc import Callable
from types import MappingProxyType
from typing import Any, Literal

from bs4 import BeautifulSoup, Tag

from ...types import DocsisDataFritz, RawChannel
from .contract import ParseDiagnostic, ParseResult, diagnostic, docsis_result, docsis_split, number_reader
from .primitives import (
    ANNEX_B_DOWNSTREAM_SYMBOL_RATES,
    hz_to_mhz,
    normalize_mhz,
    normalize_modulation,
    parse_first_number,
    parse_mhz_value,
    parse_number,
)


_HEADER_RE = re.compile(r"[^a-z0-9]+")
_CM1000_ALIASES = MappingProxyType({
    "channel": frozenset({"channel", "channelnumber", "channelno"}),
    "lock": frozenset({"lockstatus", "status"}),
    "modulation": frozenset({
        "modulation", "channeltype", "uschanneltype", "profile", "profiles",
        "profileid", "profileids", "profilemodulation",
    }),
    "channel_id": frozenset({"channelid", "id"}),
    "frequency": frozenset({"frequency", "frequencyhz"}),
    "power": frozenset({"power", "powerlevel", "powerdbmv"}),
    "snr": frozenset({"snr", "mer", "snrmer"}),
    "symbol_rate": frozenset({"symbolrate", "symbolrateksymsec"}),
    "corr": frozenset({
        "correctables", "correctable", "correctablecodewords", "corrected",
        "correctedcodewords",
    }),
    "uncorr": frozenset({
        "uncorrectables", "uncorrectable", "uncorrectablecodewords", "uncorrected",
        "uncorrectedcodewords",
    }),
})


# Arris bonded 8/7-column profile -----------------------------------------

def _arris_tables(soup: BeautifulSoup) -> tuple[Tag | None, Tag | None]:
    ds_table = us_table = None
    for table in soup.find_all("table"):
        header = table.find("tr")
        if not header:
            continue
        text = header.get_text(strip=True).lower()
        if "downstream bonded" in text:
            ds_table = table
        elif "upstream bonded" in text:
            us_table = table
    return ds_table, us_table


def _data_rows(table: Tag | None):
    if not table:
        return
    for row in table.find_all("tr"):
        if row.find("th") or row.find("strong"):
            continue
        yield row


def parse_arris_downstream(table: Tag | None) -> ParseResult[tuple[list[RawChannel], list[RawChannel]]]:
    ds30: list[RawChannel] = []
    ds31: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for row_index, row in enumerate(_data_rows(table) or ()):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 8 or cells[1] != "Locked":
            continue
        num = number_reader(diagnostics, "arris_html", family="html_rows", direction="downstream", row=row_index)
        try:
            channel: RawChannel = {
                "channelID": int(cells[0]),
                "frequency": hz_to_mhz(cells[3]),
                "powerLevel": num(cells[4], "power"),
                "modulation": cells[2],
                "corrErrors": num(cells[6], "corrected", int),
                "nonCorrErrors": num(cells[7], "uncorrected", int),
            }
            snr = num(cells[5], "snr")
            if cells[2] == "Other":
                channel.update({"type": "OFDM", "mer": snr, "mse": None})
                ds31.append(channel)
            else:
                channel.update({"mer": snr, "mse": -snr if snr is not None else None})
                ds30.append(channel)
        except (ValueError, TypeError, IndexError):
            diagnostics.append(diagnostic(
                "arris_html", "invalid_row", family="html_rows",
                direction="downstream", row=row_index,
            ))
    return ParseResult((ds30, ds31), tuple(diagnostics))


def parse_arris_upstream(table: Tag | None) -> ParseResult[tuple[list[RawChannel], list[RawChannel]]]:
    us30: list[RawChannel] = []
    us31: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for row_index, row in enumerate(_data_rows(table) or ()):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 7 or cells[2] != "Locked":
            continue
        num = number_reader(diagnostics, "arris_html", family="html_rows", direction="upstream", row=row_index)
        try:
            channel_type = cells[3]
            channel: RawChannel = {
                "channelID": int(cells[1]),
                "frequency": hz_to_mhz(cells[4]),
                "powerLevel": num(cells[6], "power"),
                "modulation": channel_type,
            }
            if "OFDM" in channel_type and "SC-QAM" not in channel_type:
                channel.update({"type": "OFDMA", "multiplex": ""})
                us31.append(channel)
            else:
                channel["multiplex"] = "SC-QAM"
                us30.append(channel)
        except (ValueError, TypeError, IndexError):
            diagnostics.append(diagnostic(
                "arris_html", "invalid_row", family="html_rows",
                direction="upstream", row=row_index,
            ))
    return ParseResult((us30, us31), tuple(diagnostics))


def parse_arris_html(html: str) -> ParseResult[DocsisDataFritz]:
    soup = BeautifulSoup(html or "", "html.parser")
    ds_table, us_table = _arris_tables(soup)
    downstream = parse_arris_downstream(ds_table)
    upstream = parse_arris_upstream(us_table)
    ds30, ds31 = downstream.value
    us30, us31 = upstream.value
    return ParseResult(
        docsis_split(ds30, ds31, us30, us31),
        downstream.diagnostics + upstream.diagnostics,
    )


# SB6183 / SB6190 row profiles --------------------------------------------


def _parse_sb_table(
    table: Tag | None,
    profile: str,
    frequency_parser: Callable[[str], str],
    direction: Literal["downstream", "upstream"],
) -> ParseResult[list[RawChannel]]:
    result: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    if not table:
        return ParseResult(result)
    for row_index, tr in enumerate(table.find_all("tr")):
        cells = [td.get_text(" ", strip=True) for td in tr.find_all("td")]
        required = 9 if direction == "downstream" else 7
        if (
            len(cells) < required
            or not cells[3].isdigit()
            or cells[1].strip().lower() != "locked"
        ):
            continue
        num = number_reader(diagnostics, profile, family="html_rows", direction=direction, row=row_index)
        try:
            if direction == "downstream":
                snr = num(cells[6], "snr")
                channel: RawChannel = {
                    "channelID": int(cells[3]), "frequency": frequency_parser(cells[4]),
                    "powerLevel": num(cells[5], "power"), "mer": snr,
                    "mse": None if snr is None else -snr, "modulation": cells[2],
                    "corrErrors": num(cells[7], "corrected", int),
                    "nonCorrErrors": num(cells[8], "uncorrected", int),
                }
            else:
                channel = {
                    "channelID": int(cells[3]), "frequency": frequency_parser(cells[5]),
                    "powerLevel": num(cells[6], "power"), "modulation": cells[2],
                    "multiplex": cells[2],
                }
            result.append(channel)
        except (ValueError, TypeError, IndexError):
            diagnostics.append(diagnostic(
                profile, "invalid_row", family="html_rows",
                direction=direction, row=row_index,
            ))
    return ParseResult(result, tuple(diagnostics))


def parse_sb6183_downstream(table: Tag | None) -> ParseResult[list[RawChannel]]:
    return _parse_sb_table(table, "sb6183_html", hz_to_mhz, "downstream")


def parse_sb6183_upstream(table: Tag | None) -> ParseResult[list[RawChannel]]:
    return _parse_sb_table(table, "sb6183_html", hz_to_mhz, "upstream")


def parse_sb6190_downstream(table: Tag | None) -> ParseResult[list[RawChannel]]:
    return _parse_sb_table(table, "sb6190_html", normalize_mhz, "downstream")


def parse_sb6190_upstream(table: Tag | None) -> ParseResult[list[RawChannel]]:
    return _parse_sb_table(table, "sb6190_html", normalize_mhz, "upstream")


def _bonded_tables(html: str, separator: str) -> tuple[Tag | None, Tag | None]:
    soup = BeautifulSoup(html or "", "html.parser")
    ds_table = us_table = None
    for table in soup.find_all("table"):
        heading = table.find("th")
        text = heading.get_text(separator, strip=True).lower() if heading else ""
        if "downstream bonded" in text:
            ds_table = table
        elif "upstream bonded" in text:
            us_table = table
    return ds_table, us_table


def _parse_sb_html(html: str, profile: str) -> ParseResult[DocsisDataFritz]:
    # SB6183 headings join their text nodes with spaces, SB6190 headings without.
    ds_table, us_table = _bonded_tables(html, " " if profile == "sb6183_html" else "")
    if profile == "sb6183_html":
        downstream = parse_sb6183_downstream(ds_table)
        upstream = parse_sb6183_upstream(us_table)
    else:
        downstream = parse_sb6190_downstream(ds_table)
        upstream = parse_sb6190_upstream(us_table)
    return ParseResult(
        docsis_split(downstream.value, [], upstream.value, []),
        downstream.diagnostics + upstream.diagnostics,
    )


def parse_sb6183_html(html: str) -> ParseResult[DocsisDataFritz]:
    return _parse_sb_html(html, "sb6183_html")


def parse_sb6190_html(html: str) -> ParseResult[DocsisDataFritz]:
    return _parse_sb_html(html, "sb6190_html")


# CM3500 heading-separated tables -----------------------------------------

def find_cm3500_sections(soup: BeautifulSoup) -> dict[str, Tag]:
    sections: dict[str, Tag] = {}
    for heading in soup.find_all("h4"):
        table = heading.find_next_sibling("table")
        if table:
            sections[heading.get_text(strip=True).lower()] = table
    return sections


def format_cm3500_frequency(value: str) -> str:
    number = parse_number(value)
    return value if number is None else f"{int(number)} MHz"


def _cm3500_rows(table: Tag | None, lane: str) -> ParseResult[list[RawChannel]]:
    result: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    if not table:
        return ParseResult(result)
    if lane in {"ds_ofdm", "us_ofdm"}:
        body = table.find("tbody")
        rows = body.find_all("tr") if body else []
    else:
        rows = table.find_all("tr")[1:]
    # OFDM rows are numbered in page order; a skipped row keeps its number so later channels keep theirs.
    channel_id = 199
    direction = "downstream" if lane.startswith("ds") else "upstream"
    for row_index, row in enumerate(rows):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        num = number_reader(diagnostics, "cm3500_html", family="html_rows", direction=direction, row=row_index)
        try:
            if lane == "ds_qam":
                if len(cells) < 9:
                    continue
                qam_id = int(parse_number(cells[1]))
                mer = num(cells[4], "snr")
                result.append({
                    "channelID": qam_id,
                    "frequency": format_cm3500_frequency(cells[2]),
                    "powerLevel": num(cells[3], "power"),
                    "mse": None if mer is None else -mer,
                    "mer": mer,
                    "modulation": cells[5],
                    "corrErrors": num(cells[7], "corrected", int),
                    "nonCorrErrors": num(cells[8], "uncorrected", int),
                })
            elif lane == "ds_ofdm":
                # A labelled row keeps its number even when it is too short to read (IndexError below).
                if not cells or "downstream" not in cells[0].lower():
                    continue
                channel_id += 1
                frequency = f"{int(parse_number(cells[4]))}-{int(parse_number(cells[5]))} MHz"
                result.append({
                    "channelID": channel_id, "type": "OFDM", "frequency": frequency,
                    "powerLevel": None, "mer": num(cells[8] if len(cells) > 8 else cells[7], "snr"), "mse": None,
                    "corrErrors": None, "nonCorrErrors": None,
                })
            elif lane == "us_qam":
                if len(cells) < 7:
                    continue
                kind = cells[4].upper()
                multiplex = "ATDMA" if "ATDMA" in kind else "TDMA" if "TDMA" in kind else ""
                result.append({
                    "channelID": int(parse_number(cells[1])),
                    "frequency": format_cm3500_frequency(cells[2]),
                    "powerLevel": num(cells[3], "power"),
                    "modulation": cells[6], "multiplex": multiplex,
                })
            else:
                if not cells or "upstream" not in cells[0].lower():
                    continue
                channel_id += 1
                frequency = f"{int(parse_number(cells[6]))}-{int(parse_number(cells[7]))} MHz"
                result.append({
                    "channelID": channel_id, "type": "OFDMA", "frequency": frequency,
                    "powerLevel": num(cells[8], "power"),
                    "modulation": "OFDMA", "multiplex": "",
                })
        except (ValueError, TypeError, IndexError):
            diagnostics.append(diagnostic(
                "cm3500_html", "invalid_row", family="html_rows", direction=direction, row=row_index,
            ))
    return ParseResult(result, tuple(diagnostics))


def parse_cm3500_ds_qam(table: Tag | None) -> ParseResult[list[RawChannel]]:
    return _cm3500_rows(table, "ds_qam")


def parse_cm3500_ds_ofdm(table: Tag | None) -> ParseResult[list[RawChannel]]:
    return _cm3500_rows(table, "ds_ofdm")


def parse_cm3500_us_qam(table: Tag | None) -> ParseResult[list[RawChannel]]:
    return _cm3500_rows(table, "us_qam")


def parse_cm3500_us_ofdm(table: Tag | None) -> ParseResult[list[RawChannel]]:
    return _cm3500_rows(table, "us_ofdm")


def parse_cm3500_html(html: str | BeautifulSoup) -> ParseResult[DocsisDataFritz]:
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html or "", "html.parser")
    sections = find_cm3500_sections(soup)
    return docsis_result(
        parse_cm3500_ds_qam(sections.get("downstream qam")),
        parse_cm3500_ds_ofdm(sections.get("downstream ofdm")),
        parse_cm3500_us_qam(sections.get("upstream qam")),
        parse_cm3500_us_ofdm(sections.get("upstream ofdm")),
    )


# TC4400 dynamic-header tables --------------------------------------------

def _tc_header_row(rows):
    for row in rows:
        cells = row.find_all(["th", "td"])
        if cells and any(cell.get("colspan") for cell in cells):
            continue
        if len(cells) > 3:
            return row
    return None


def _tc_columns(headers: list[str]) -> dict[str, int | None]:
    columns = {key: None for key in (
        "channel_id", "lock_status", "modulation", "channel_type", "frequency",
        "power", "snr", "corrected", "uncorrected",
    )}
    for index, header in enumerate(headers):
        if "channel" in header and "id" in header:
            columns["channel_id"] = index
        elif "channel" in header and "index" in header and columns["channel_id"] is None:
            columns["channel_id"] = index
        elif "lock" in header:
            columns["lock_status"] = index
        elif "channel" in header and "type" in header:
            columns["channel_type"] = index
        elif "modulation" in header or "profile" in header:
            columns["modulation"] = index
        elif "freq" in header:
            columns["frequency"] = index
        elif any(word in header for word in ("power", "receive", "transmit")):
            columns["power"] = index
        elif "snr" in header or "mer" in header:
            columns["snr"] = index
        elif "corrected" in header and "un" not in header:
            columns["corrected"] = index
        elif "uncorrect" in header:
            columns["uncorrected"] = index
    columns["channel_id"] = 0 if columns["channel_id"] is None else columns["channel_id"]
    columns["lock_status"] = 1 if columns["lock_status"] is None else columns["lock_status"]
    if columns["channel_type"] is None and columns["modulation"] is None:
        columns["modulation"] = 2
    columns["frequency"] = 3 if columns["frequency"] is None else columns["frequency"]
    return columns


def _cell(cells: list[str], index: int | None, default: str = "") -> str:
    return default if index is None or index >= len(cells) else cells[index]


def _parse_tc_table(table: Tag | None, direction: str) -> ParseResult[list[RawChannel]]:
    if not table:
        return ParseResult([])
    rows = table.find_all("tr")
    header = _tc_header_row(rows)
    if header is None:
        return ParseResult([])
    columns = _tc_columns([cell.get_text(strip=True).lower() for cell in header.find_all(["th", "td"])])
    result: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for row_index, row in enumerate(item for item in rows if item != header):
        cells = [td.get_text(strip=True) for td in row.find_all("td")]
        if len(cells) < 4 or _cell(cells, columns["lock_status"]).lower() != "locked":
            continue
        num = number_reader(diagnostics, "tc4400_html", family="html_rows", direction=direction, row=row_index)
        try:
            channel_id = _cell(cells, columns["channel_id"], "0")
            modulation = normalize_modulation(_cell(cells, columns["modulation"]))
            frequency = parse_mhz_value(_cell(cells, columns["frequency"]))
            power = num(_cell(cells, columns["power"]), "power")
            if direction == "downstream":
                channel_type = _cell(cells, columns["channel_type"])
                if channel_type.upper() == "OFDM":
                    final_type = "OFDM"
                elif channel_type.upper() == "SC-QAM":
                    final_type = modulation or "QAM"
                else:
                    final_type = modulation or "unknown"
                snr = num(_cell(cells, columns["snr"]), "snr")
                result.append({
                    "channelID": channel_id, "type": final_type,
                    "frequency": f"{int(frequency)} MHz" if frequency else "",
                    "powerLevel": power,
                    "mse": None if final_type == "OFDM" or snr is None else -snr,
                    "mer": snr, "latency": 0,
                    "corrError": num(_cell(cells, columns["corrected"]), "corrected", int),
                    "nonCorrError": num(_cell(cells, columns["uncorrected"]), "uncorrected", int),
                })
            else:
                result.append({
                    "channelID": channel_id, "type": modulation,
                    "frequency": f"{int(frequency)} MHz" if frequency else "",
                    "powerLevel": power, "multiplex": "",
                })
        except (ValueError, TypeError, IndexError):
            diagnostics.append(diagnostic(
                "tc4400_html", "invalid_row", family="html_rows",
                direction=direction, row=row_index,
            ))
    return ParseResult(result, tuple(diagnostics))


def parse_tc4400_downstream(table: Tag | None) -> ParseResult[list[RawChannel]]:
    return _parse_tc_table(table, "downstream")


def parse_tc4400_upstream(table: Tag | None) -> ParseResult[list[RawChannel]]:
    return _parse_tc_table(table, "upstream")


def parse_tc4400_html(downstream_table: Tag | None, upstream_table: Tag | None) -> ParseResult[dict[str, Any]]:
    downstream = parse_tc4400_downstream(downstream_table)
    upstream = parse_tc4400_upstream(upstream_table)
    return ParseResult(
        {"docsis": "3.1", "downstream": downstream.value, "upstream": upstream.value},
        downstream.diagnostics + upstream.diagnostics,
    )


# CM1000 server-rendered tables -------------------------------------------

def _cm1000_get(row: dict[str, str], field: str, default: str = "") -> str:
    for alias in _CM1000_ALIASES[field]:
        if alias in row:
            return row[alias]
    return default


def normalize_cm1000_header(value: str) -> str:
    return _HEADER_RE.sub("", value.lower())


def cm1000_looks_like_header(values: list[str]) -> bool:
    known = set().union(*_CM1000_ALIASES.values())
    return "channel" in values and any(value in known for value in values[1:])


def _cm1000_locked(values) -> bool:
    return any(value.strip().lower() == "locked" for value in values)


def _cm1000_int(value: str) -> int | None:
    number = parse_first_number(value)
    return int(number) if number is not None else None


def cm1000_table_rows(soup: BeautifulSoup, table_id: str) -> list[dict[str, str] | None]:
    """Rows keyed by header or position; None marks a locked row too short to map."""
    table = soup.find("table", id=table_id)
    if table is None:
        return []
    headers: list[str] = []
    result: list[dict[str, str]] = []
    for row in table.find_all("tr"):
        cells = row.find_all(["th", "td"], recursive=False) or row.find_all(["th", "td"])
        values = [cell.get_text(" ", strip=True) for cell in cells]
        if not values:
            continue
        normalized = [normalize_cm1000_header(value) for value in values]
        if not headers and cm1000_looks_like_header(normalized):
            headers = normalized
            continue
        if headers:
            if len(values) < len(headers):
                if _cm1000_locked(values):
                    result.append(None)
                continue
            result.append(dict(zip(headers, values)))
        else:
            result.append({str(index): value for index, value in enumerate(values)})
    return result


def _cm1000_positional(row: dict[str, str], direction: str) -> dict[str, str]:
    values = [row[str(index)] for index in range(len(row))]
    if direction == "downstream":
        if len(values) < 9:
            return row
        mapped = {
            "channel": values[0], "lockstatus": values[1], "modulation": values[2],
            "channelid": values[3], "frequency": values[4], "power": values[5],
            "snr": values[6],
        }
        mapped["correctables"] = values[-2] if len(values) >= 10 else values[7]
        mapped["uncorrectables"] = values[-1] if len(values) >= 10 else values[8]
        return mapped
    if len(values) < 6:
        return row
    mapped = {
        "channel": values[0], "lockstatus": values[1], "modulation": values[2],
        "channelid": values[3],
    }
    if len(values) >= 7:
        mapped.update({"symbolrate": values[4], "frequency": values[5], "power": values[6]})
    else:
        mapped.update({"frequency": values[4], "power": values[5]})
    return mapped


def _parse_cm1000_table(
    soup: BeautifulSoup, table_id: str, *, direction: str, docsis31: bool,
) -> ParseResult[list[RawChannel]]:
    result: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    for index, row in enumerate(cm1000_table_rows(soup, table_id)):
        locked = row is not None and (_cm1000_get(row, "lock") or row.get("1", "")).strip().lower() == "locked"
        if locked and not any(key.isalpha() for key in row):
            row = _cm1000_positional(row, direction)
        channel_id = _cm1000_int(
            _cm1000_get(row, "channel_id") or _cm1000_get(row, "channel") or row.get("0", "")
        ) if locked else None
        if channel_id is None:
            # A locked row the layout cannot map is malformed; other rows are simply not locked.
            if locked or row is None or _cm1000_locked(row.values()):
                diagnostics.append(diagnostic(
                    "cm1000_html_table", "invalid_row", family="html_rows", direction=direction, row=index,
                ))
            continue
        frequency = hz_to_mhz(_cm1000_get(row, "frequency"))
        power = parse_first_number(_cm1000_get(row, "power"))
        modulation = normalize_modulation(_cm1000_get(row, "modulation"))
        if direction == "downstream":
            snr = parse_first_number(_cm1000_get(row, "snr"))
            if docsis31:
                channel: RawChannel = {
                    "channelID": channel_id, "type": "OFDM", "frequency": frequency,
                    "powerLevel": power, "mer": snr, "mse": None, "modulation": "OFDM",
                    "corrErrors": _cm1000_int(_cm1000_get(row, "corr")),
                    "nonCorrErrors": _cm1000_int(_cm1000_get(row, "uncorr")),
                }
            else:
                channel = {
                    "channelID": channel_id, "frequency": frequency, "powerLevel": power,
                    "mer": snr, "mse": -snr if snr is not None else None,
                    "modulation": modulation,
                    "corrErrors": _cm1000_int(_cm1000_get(row, "corr")),
                    "nonCorrErrors": _cm1000_int(_cm1000_get(row, "uncorr")),
                }
                symbol_rate = ANNEX_B_DOWNSTREAM_SYMBOL_RATES.get(modulation)
                if symbol_rate is not None:
                    channel["symbolRate"] = symbol_rate
        elif docsis31:
            channel = {
                "channelID": channel_id, "type": "OFDMA", "frequency": frequency,
                "powerLevel": power, "modulation": "OFDMA", "multiplex": "",
            }
        else:
            channel = {
                "channelID": channel_id, "frequency": frequency, "powerLevel": power,
                "modulation": modulation, "multiplex": modulation,
            }
            symbol_rate = _cm1000_int(_cm1000_get(row, "symbol_rate"))
            if symbol_rate is not None:
                channel["symbolRate"] = symbol_rate
        result.append(channel)
    return ParseResult(result, tuple(diagnostics))


def parse_cm1000_downstream_table(soup: BeautifulSoup, table_id: str, *, docsis31: bool) -> ParseResult[list[RawChannel]]:
    return _parse_cm1000_table(soup, table_id, direction="downstream", docsis31=docsis31)


def parse_cm1000_upstream_table(soup: BeautifulSoup, table_id: str, *, docsis31: bool) -> ParseResult[list[RawChannel]]:
    return _parse_cm1000_table(soup, table_id, direction="upstream", docsis31=docsis31)


def parse_cm1000_html_table(html: str | BeautifulSoup) -> ParseResult[DocsisDataFritz]:
    soup = html if isinstance(html, BeautifulSoup) else BeautifulSoup(html or "", "html.parser")
    return docsis_result(
        parse_cm1000_downstream_table(soup, "dsTable", docsis31=False),
        parse_cm1000_downstream_table(soup, "d31dsTable", docsis31=True),
        parse_cm1000_upstream_table(soup, "usTable", docsis31=False),
        parse_cm1000_upstream_table(soup, "d31usTable", docsis31=True),
    )
