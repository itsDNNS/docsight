"""Pure normalization boundary for pre-normalized FritzBox data.lua payloads."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, cast

from ...types import DocsisData
from .contract import ParseDiagnostic, ParseResult, number_reader


_UPSTREAM_31_POWER_OFFSET = 6.0


def parse_fritzbox_data_lua(payload: dict[str, Any] | None) -> ParseResult[DocsisData]:
    """Copy the pre-normalized boundary and apply the existing US 3.1 correction."""
    value = cast(DocsisData, deepcopy(payload) if isinstance(payload, dict) else {})
    diagnostics: list[ParseDiagnostic] = []
    upstream = value.get("channelUs", {}).get("docsis31", [])
    for index, channel in enumerate(upstream):
        power = number_reader(
            diagnostics, "fritzbox_data_lua", family="fritzbox", direction="upstream", index=index,
        )(channel.get("powerLevel"), "powerLevel")
        if power is None:
            channel["powerLevel"] = None
            continue
        channel["powerLevel"] = str(round(power + _UPSTREAM_31_POWER_OFFSET, 1))
        # Kept with the channel so the UI can say why it differs from the modem's page.
        channel["powerDisplayOffset"] = _UPSTREAM_31_POWER_OFFSET
    return ParseResult(value, tuple(diagnostics))
