"""Compatibility shim for the established shared Arris bonded-table parser."""

from __future__ import annotations

from .formats.html_rows import (
    _arris_tables as _find_channel_tables,
    _optional_value as _parse_value,
    parse_arris_downstream,
    parse_arris_html,
    parse_arris_upstream,
)
from .formats.primitives import hz_to_mhz as _parse_freq_hz


def parse_arris_channel_tables(html: str):
    return parse_arris_html(html).value


def _parse_downstream(table):
    return parse_arris_downstream(table).value


def _parse_upstream(table):
    return parse_arris_upstream(table).value


def _is_header_row(row):
    return bool(row.find("th") or row.find("strong"))


__all__ = [
    "parse_arris_channel_tables",
    "_find_channel_tables",
    "_is_header_row",
    "_parse_downstream",
    "_parse_freq_hz",
    "_parse_upstream",
    "_parse_value",
]
