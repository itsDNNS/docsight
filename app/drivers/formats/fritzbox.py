"""Pure normalization boundary for pre-normalized FritzBox data.lua payloads."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from ...types import DocsisData
from .contract import ParseDiagnostic, ParseResult, diagnostic


_UPSTREAM_31_POWER_OFFSET = 6.0


def parse_fritzbox_data_lua(payload: dict[str, Any] | None) -> ParseResult[DocsisData]:
    """Copy the pre-normalized boundary and apply the existing US 3.1 correction."""
    value = cast(DocsisData, deepcopy(payload) if isinstance(payload, dict) else {})
    diagnostics: list[ParseDiagnostic] = []
    upstream = value.get("channelUs", {}).get("docsis31", [])
    for index, channel in enumerate(upstream):
        try:
            raw = float(channel.get("powerLevel", 0))
            channel["powerLevel"] = str(round(raw + _UPSTREAM_31_POWER_OFFSET, 1))
        except (TypeError, ValueError):
            diagnostics.append(diagnostic(
                "fritzbox_data_lua", "invalid_field", family="fritzbox",
                direction="upstream", index=index, field="powerLevel",
            ))
    return ParseResult(value, tuple(diagnostics))
