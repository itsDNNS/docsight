"""Explicit JavaScript tag-list profiles for Netgear modem payloads."""

from __future__ import annotations

import re
from types import MappingProxyType
from typing import Literal

from ...types import DocsisDataFritz, RawChannel
from .contract import ParseDiagnostic, ParseResult, diagnostic, docsis_result, docsis_split
from .primitives import hz_to_mhz, normalize_modulation, parse_number


_FUNCTION_START = re.compile(r"function\s+(?P<name>\w+)\s*\(\)\s*\{")
_CM1000_ASSIGNMENT = re.compile(r"\bvar\s+tagValueList\s*=\s*(?P<value>.*?);", re.DOTALL)
_STRING_LITERAL = re.compile(
    r"'(?P<single>(?:\\.|[^'\\])*)'|\"(?P<double>(?:\\.|[^\"\\])*)\"",
    re.DOTALL,
)
_CM3000_SINGLE = re.compile(r"'([^'\\]*(?:\\.[^'\\]*)*)'", re.DOTALL)
_CM3000_DOUBLE = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"', re.DOTALL)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_NUMBER = re.compile(r"[-+]?\d+(?:\.\d+)?")
_CM1000_FIELDS = 7
_CM3000_FIELDS = MappingProxyType({
    "InitDsTableTagValue": 9,
    "InitUsTableTagValue": 7,
    "InitDsOfdmTableTagValue": 11,
    "InitUsOfdmaTableTagValue": 6,
})
_ANNEX_B_DOWNSTREAM_SYMBOL_RATES = MappingProxyType({"64QAM": 5057, "256QAM": 5361})


def extract_function_body(source: str, function_name: str) -> str | None:
    """Extract one named function body with balanced braces."""
    for match in _FUNCTION_START.finditer(source or ""):
        if match.group("name") != function_name:
            continue
        start = match.end()
        depth = 1
        index = start
        while index < len(source) and depth:
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
            index += 1
        return source[start:index - 1] if depth == 0 else None
    return None


def strip_javascript_comments(source: str) -> str:
    """Remove comments while preserving quoted content for the CM1000 grammar."""
    result: list[str] = []
    index = 0
    quote: str | None = None
    while index < len(source):
        char = source[index]
        if quote is not None:
            result.append(char)
            if char == "\\" and index + 1 < len(source):
                index += 1
                result.append(source[index])
            elif char == quote:
                quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
            result.append(char)
            index += 1
            continue
        if source.startswith("//", index):
            newline = source.find("\n", index + 2)
            if newline == -1:
                break
            result.append("\n")
            index = newline + 1
            continue
        if source.startswith("/*", index):
            end = source.find("*/", index + 2)
            if end == -1:
                break
            result.append(" ")
            index = end + 2
            continue
        result.append(char)
        index += 1
    return "".join(result)


def split_cm1000_rows(raw: str) -> list[list[str]] | None:
    parts = raw.split("|")
    if not parts[0].strip().isdecimal():
        return None
    row_count = int(parts[0].strip())
    values = parts[1:]
    if values and not values[-1]:
        values.pop()
    if len(values) != row_count * _CM1000_FIELDS:
        return None
    return [values[index:index + _CM1000_FIELDS] for index in range(0, len(values), _CM1000_FIELDS)]


def extract_cm1000_tag_value_list(html: str, function_name: str) -> str | None:
    body = extract_function_body(html, function_name)
    if body is None:
        return None
    assignment = _CM1000_ASSIGNMENT.search(strip_javascript_comments(body))
    if assignment is None:
        return None
    literals: list[str] = []
    for match in _STRING_LITERAL.finditer(assignment.group("value")):
        value = match.group("single")
        if value is None:
            value = match.group("double")
        literals.append(value.replace(r"\'", "'").replace(r'\"', '"').replace(r"\\", "\\"))
    if not literals:
        return None
    payload = "".join(literals)
    return payload if split_cm1000_rows(payload) is not None else None


def _optional_number(value: str) -> float | None:
    if not value:
        return None
    match = _NUMBER.search(value.replace(",", ""))
    return float(match.group(0)) if match else None


def _parse_cm1000_tag_values(
    raw: str,
    direction: Literal["downstream", "upstream"],
) -> ParseResult[list[RawChannel]]:
    rows = split_cm1000_rows(raw)
    if rows is None:
        return ParseResult([], (diagnostic(
            "cm1000_javascript", "invalid_framing", family="javascript",
            direction=direction,
        ),))
    result: list[RawChannel] = []
    for row in rows:
        if row[1].strip().lower() != "locked":
            continue
        channel_id = _optional_number(row[3])
        if channel_id is None:
            continue
        modulation = normalize_modulation(row[2])
        if direction == "downstream":
            snr = _optional_number(row[6])
            channel: RawChannel = {
                "channelID": int(channel_id), "frequency": hz_to_mhz(row[4]),
                "powerLevel": _optional_number(row[5]), "mer": snr,
                "mse": -snr if snr is not None else None, "modulation": modulation,
                "corrErrors": None, "nonCorrErrors": None,
            }
            symbol_rate = _ANNEX_B_DOWNSTREAM_SYMBOL_RATES.get(modulation)
        else:
            channel = {
                "channelID": int(channel_id), "frequency": hz_to_mhz(row[5]),
                "powerLevel": _optional_number(row[6]), "modulation": modulation,
                "multiplex": modulation,
            }
            number = _optional_number(row[4])
            symbol_rate = int(number) if number is not None else None
        if symbol_rate is not None:
            channel["symbolRate"] = symbol_rate
        result.append(channel)
    return ParseResult(result)


def parse_cm1000_downstream_tag_values(raw: str) -> ParseResult[list[RawChannel]]:
    return _parse_cm1000_tag_values(raw, "downstream")


def parse_cm1000_upstream_tag_values(raw: str) -> ParseResult[list[RawChannel]]:
    return _parse_cm1000_tag_values(raw, "upstream")


def parse_cm1000_javascript(html: str) -> ParseResult[DocsisDataFritz]:
    downstream_raw = extract_cm1000_tag_value_list(html, "InitDsTableTagValue")
    upstream_raw = extract_cm1000_tag_value_list(html, "InitUsTableTagValue")
    downstream = parse_cm1000_downstream_tag_values(downstream_raw) if downstream_raw is not None else ParseResult([])
    upstream = parse_cm1000_upstream_tag_values(upstream_raw) if upstream_raw is not None else ParseResult([])
    return ParseResult(
        docsis_split(downstream.value, [], upstream.value, []),
        downstream.diagnostics + upstream.diagnostics,
    )


def extract_cm3000_tag_value_list(html: str, function_name: str) -> str | None:
    body = extract_function_body(html, function_name)
    if not body:
        return None
    body = _BLOCK_COMMENT.sub("", body)
    assignment_index = body.find("var tagValueList")
    if assignment_index == -1:
        return None
    parts = body[assignment_index:].split("=", 1)
    if len(parts) != 2:
        return None
    expression = parts[1]
    return_index = expression.find("return tagValueList.split")
    if return_index != -1:
        expression = expression[:return_index]
    expression = expression.strip().rstrip(";").strip()
    literals = _CM3000_SINGLE.findall(expression) + _CM3000_DOUBLE.findall(expression)
    if not literals:
        return None
    return "".join(bytes(value, "utf-8").decode("unicode_escape") for value in literals)


def split_cm3000_channels(raw: str, fields_per_channel: int) -> list[list[str]]:
    values = raw.split("|")[1:]
    if values and values[-1] == "":
        values = values[:-1]
    return [
        values[index:index + fields_per_channel]
        for index in range(0, len(values), fields_per_channel)
        if len(values[index:index + fields_per_channel]) == fields_per_channel
    ]


def normalize_cm3000_modulation(value: str) -> str:
    return value.strip() if value else ""


def _parse_cm3000_lane(html: str, function_name: str) -> ParseResult[list[RawChannel]]:
    raw = extract_cm3000_tag_value_list(html, function_name)
    if not raw:
        return ParseResult([])
    result: list[RawChannel] = []
    diagnostics: list[ParseDiagnostic] = []
    direction = "downstream" if function_name.startswith("InitDs") else "upstream"
    for index, channel in enumerate(split_cm3000_channels(raw, _CM3000_FIELDS[function_name])):
        if channel[1] != "Locked":
            continue
        try:
            if function_name == "InitDsTableTagValue":
                result.append({
                    "channelID": int(channel[3]), "frequency": hz_to_mhz(channel[4]),
                    "powerLevel": float(channel[5]), "mer": float(channel[6]),
                    "mse": -float(channel[6]), "modulation": normalize_cm3000_modulation(channel[2]),
                    "corrErrors": int(channel[7]), "nonCorrErrors": int(channel[8]),
                })
            elif function_name == "InitUsTableTagValue":
                result.append({
                    "channelID": int(channel[3]), "frequency": hz_to_mhz(channel[5]),
                    "powerLevel": parse_number(channel[6]), "modulation": normalize_cm3000_modulation(channel[2]),
                    "multiplex": channel[2].upper() if channel[2] else "",
                })
            elif function_name == "InitDsOfdmTableTagValue":
                # number|lock|profiles|channel ID|frequency|power|SNR/MER|
                # active subcarriers|unerrored|correctable|uncorrectable
                result.append({
                    "channelID": int(channel[3]), "type": "OFDM",
                    "frequency": hz_to_mhz(channel[4]), "powerLevel": parse_number(channel[5]),
                    "mer": parse_number(channel[6]), "mse": None,
                    "corrErrors": int(channel[9]), "nonCorrErrors": int(channel[10]),
                })
            else:
                result.append({
                    "channelID": int(channel[3]), "type": "OFDMA",
                    "frequency": hz_to_mhz(channel[4]), "powerLevel": parse_number(channel[5]),
                    "modulation": "OFDMA", "multiplex": "",
                })
        except (ValueError, IndexError):
            diagnostics.append(diagnostic(
                "cm3000_javascript", "invalid_channel", family="javascript",
                direction=direction, index=index,
            ))
    return ParseResult(result, tuple(diagnostics))


def parse_cm3000_ds_qam(html: str) -> ParseResult[list[RawChannel]]:
    return _parse_cm3000_lane(html, "InitDsTableTagValue")


def parse_cm3000_us_atdma(html: str) -> ParseResult[list[RawChannel]]:
    return _parse_cm3000_lane(html, "InitUsTableTagValue")


def parse_cm3000_ds_ofdm(html: str) -> ParseResult[list[RawChannel]]:
    return _parse_cm3000_lane(html, "InitDsOfdmTableTagValue")


def parse_cm3000_us_ofdma(html: str) -> ParseResult[list[RawChannel]]:
    return _parse_cm3000_lane(html, "InitUsOfdmaTableTagValue")


def parse_cm3000_javascript(html: str) -> ParseResult[DocsisDataFritz]:
    return docsis_result(
        parse_cm3000_ds_qam(html), parse_cm3000_ds_ofdm(html),
        parse_cm3000_us_atdma(html), parse_cm3000_us_ofdma(html),
    )
