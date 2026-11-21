"""Driver-side logging of payload-safe parser diagnostics."""

from __future__ import annotations

from collections import Counter
import logging

from .formats.contract import ParseResult

# Unreported readings and channel types DOCSight does not parse recur on every poll of a healthy
# modem; they stay None or are skipped and are not malformed data.
_EXPECTED_CODES = frozenset({
    "unavailable_counters", "unavailable_field", "unknown_channel_type", "unsupported_counters",
})


def unwrap(result: ParseResult, logger, messages: dict[tuple[str, str], str] | None = None):
    """Log each distinct diagnostic once per parse and return the parsed value."""
    counts = Counter((issue.profile, issue.code, issue.direction, issue.field) for issue in result.diagnostics)
    for (profile, code, direction, field), count in counts.items():
        if messages and (code, field) in messages:
            logger.warning(messages[code, field])
        else:
            logger.log(
                logging.DEBUG if code in _EXPECTED_CODES else logging.WARNING,
                "%s parser reported %s (direction=%s, field=%s, rows=%d)",
                profile, code, direction, field, count,
            )
    return result.value


def unwrap_hitron(result: ParseResult, logger, model: str = "CODA-56"):
    return unwrap(result, logger, {
        ("missing_field", "repPower1_6"): f"Hitron {model} OFDMA row missing repPower1_6; leaving power unsupported",
    })


def unwrap_sercom(result: ParseResult, logger):
    return unwrap(result, logger, {
        ("missing_field", "rep power1_6"): "Sercom DM1000 OFDMA row missing rep power1_6; leaving power unsupported",
    })
