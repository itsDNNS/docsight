"""Helpers for presenting DOCSIS hardware error counters as time series."""

from __future__ import annotations

from collections.abc import Iterable, MutableMapping
from typing import Any

UINT32_COUNTER_SIZE = 2**32
_UINT32_WRAP_PREVIOUS_MIN = int(UINT32_COUNTER_SIZE * 0.75)
_UINT32_WRAP_CURRENT_MAX = int(UINT32_COUNTER_SIZE * 0.25)


def _coerce_counter(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _looks_like_uint32_wrap(previous_raw: int, current_raw: int) -> bool:
    """Return True when a raw counter drop matches an unsigned 32-bit rollover."""
    if current_raw >= previous_raw:
        return False
    previous_mod = previous_raw % UINT32_COUNTER_SIZE
    current_mod = current_raw % UINT32_COUNTER_SIZE
    return (
        previous_mod >= _UINT32_WRAP_PREVIOUS_MIN
        and current_mod <= _UINT32_WRAP_CURRENT_MAX
    )


def unwrap_uint32_counter_series(
    rows: Iterable[MutableMapping[str, Any]],
    keys: Iterable[str],
) -> None:
    """Unwrap unsigned 32-bit counter rollovers in-place for presentation rows.

    DOCSIS drivers can expose hardware counters as raw uint32 values. Persisting
    those raw values is useful, but charts should not show a sawtooth when a
    counter rolls from 4,294,967,295 back to 0. This helper only adjusts returned
    API/storage series rows; it does not mutate stored snapshots.

    Rows must be ordered oldest-to-newest. Missing/null counters remain
    missing/null, and ordinary low-value decreases are treated as resets rather
    than wraps. A real hardware reset from a value near uint32 max to a low value
    is indistinguishable from a rollover in this presentation-layer heuristic.
    """
    state = {
        key: {"offset": 0, "previous_raw": None, "previous_unwrapped": None}
        for key in keys
    }
    for row in rows:
        for key, key_state in state.items():
            if key not in row:
                continue
            raw = _coerce_counter(row.get(key))
            if raw is None:
                continue

            previous_raw = key_state["previous_raw"]
            previous_unwrapped = key_state["previous_unwrapped"]
            if isinstance(previous_raw, int) and isinstance(previous_unwrapped, int):
                if _looks_like_uint32_wrap(previous_raw, raw):
                    key_state["offset"] += UINT32_COUNTER_SIZE
                    while raw + key_state["offset"] <= previous_unwrapped:
                        key_state["offset"] += UINT32_COUNTER_SIZE
                elif raw < previous_raw:
                    key_state["offset"] = 0

            unwrapped = raw + key_state["offset"]
            row[key] = unwrapped
            key_state["previous_raw"] = raw
            key_state["previous_unwrapped"] = unwrapped
