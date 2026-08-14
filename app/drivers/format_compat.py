"""Finite legacy logging adapters for driver-private parser seams."""

from __future__ import annotations

from typing import Any

from .formats.contract import ParseResult


def unwrap_f3896lg(result: ParseResult, rows: list[dict[str, Any]], direction: str, logger):
    for issue in result.diagnostics:
        row = rows[issue.index] if issue.index is not None and issue.index < len(rows) else {}
        if issue.code == "unknown_channel_type":
            logger.debug("Skipping unknown %s channel type %r", direction, row.get("channelType"))
        elif issue.field == "rxMer":
            logger.warning("Invalid F3896LG OFDM rxMer %r; using no MER", row.get("rxMer"))
        elif issue.field == "power":
            lane = "OFDM" if direction == "downstream" else "OFDMA"
            logger.warning("Invalid F3896LG %s power %r; using no power", lane, row.get("power"))
    return result.value


def unwrap_hitron(result: ParseResult, logger):
    if any(issue.code == "missing_field" and issue.field == "repPower1_6" for issue in result.diagnostics):
        logger.warning("Hitron CODA-56 OFDMA row missing repPower1_6; leaving power unsupported")
    return result.value


def unwrap_sercom(result: ParseResult, logger):
    if any(issue.code == "missing_field" and issue.field == "rep power1_6" for issue in result.diagnostics):
        logger.warning("Sercom DM1000 OFDMA row missing rep power1_6; leaving power unsupported")
    return result.value
