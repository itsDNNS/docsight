"""View model for the Channels status matrix.

Every current channel gets one row of fixed time cells. A cell carries the worst
rating any snapshot in that interval had. Channels that deviated at any point in
the window are listed on their own; all others share one aggregated row.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .channel_selector import attach_channel_selectors, channel_selector
from .line_status import FAMILY_LABELS, SEVERITY, _family, _number, channel_callout

CELL_COUNT = 48


def _parse(ts: str) -> datetime | None:
    try:
        return datetime.strptime(ts, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _stamp(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _health(channel: dict) -> str | None:
    health = channel.get("health")
    return health if health in SEVERITY else None


def _worse(current: str | None, health: str | None) -> str | None:
    if health is None:
        return current
    if current is None or SEVERITY[health] > SEVERITY[current]:
        return health
    return current


def _sort_id(channel: dict) -> tuple[int, str]:
    value = _number(channel.get("channel_id"))
    return (int(value) if value is not None else 0, str(channel.get("channel_id")))


def _row(direction: str, channel: dict, history: list[tuple[datetime, str | None]],
         start: datetime, span: float) -> dict:
    cells: list[str | None] = [None] * CELL_COUNT
    for when, health in history:
        index = min(CELL_COUNT - 1, max(0, int((when - start).total_seconds() / span * CELL_COUNT)))
        cells[index] = _worse(cells[index], health)

    current = _health(channel) or "good"
    since = None
    since_pct = None
    if current != "good":
        run_start = None
        for when, health in reversed(history):
            if health is None or health == "good":
                break
            run_start = when
        if run_start is not None:
            since = _stamp(run_start)
            since_pct = round(max(0.0, (run_start - start).total_seconds() / span * 100), 2)

    callout = channel_callout(direction, channel)
    measurement = callout["measurement"]
    value = measurement["value"] if measurement else _number(channel.get("power"))
    return {
        "channel_id": channel.get("channel_id"),
        "legacy_channel_id": channel.get("legacy_channel_id"),
        "selector": channel.get("selector") or channel_selector(channel),
        "selector_required": bool(channel.get("selector_required")),
        "family": FAMILY_LABELS.get(_family(direction, channel), ""),
        "modulation": callout["modulation"],
        "health": current,
        "cells": cells,
        "deviating_cells": sum(1 for cell in cells if cell not in (None, "good")),
        "since": since,
        "since_pct": since_pct,
        "value": value,
        "unit": measurement["unit"] if measurement else ("dBmV" if value is not None else None),
        "measurement": measurement,
    }


def _direction(direction: str, channels: list[dict], snapshots: list[tuple[datetime, list[dict]]],
               start: datetime, span: float) -> dict | None:
    if not channels:
        return None
    current = attach_channel_selectors(channels)
    keys = {row["selector"] for row in current}
    history: dict[str, list[tuple[datetime, str | None]]] = {key: [] for key in keys}
    # Long windows hold thousands of snapshots of the same few channels; hash each identity once.
    selectors: dict[tuple, str] = {}
    for when, rows in snapshots:
        for channel in rows:
            identity = (repr(channel.get("channel_id")), repr(channel.get("frequency")))
            key = selectors.get(identity)
            if key is None:
                key = selectors[identity] = channel_selector(channel)
            if key in history:
                history[key].append((when, _health(channel)))

    rows = [_row(direction, ch, history[ch["selector"]], start, span)
            for ch in sorted(current, key=_sort_id)]
    deviating = sorted(
        (row for row in rows if row["health"] != "good" or row["deviating_cells"]),
        key=lambda row: (-SEVERITY[row["health"]], -row["deviating_cells"]),
    )
    others = [row for row in rows if row["health"] == "good" and not row["deviating_cells"]]
    combined: list[str | None] = [None] * CELL_COUNT
    for row in others:
        for index, cell in enumerate(row["cells"]):
            combined[index] = _worse(combined[index], cell)
    return {
        "key": direction,
        "total": len(rows),
        "deviating": deviating,
        "others": others,
        "others_cells": combined,
    }


def build_channel_matrix(snapshots: list[tuple[str, list[dict], list[dict]]],
                         start: str, end: str) -> dict:
    """Return the matrix for snapshots (timestamp, ds, us) inside [start, end].

    The current channel set is the newest snapshot; channels that only appear in
    older snapshots are not listed.
    """
    start_dt, end_dt = _parse(start), _parse(end)
    if start_dt is None or end_dt is None or end_dt <= start_dt:
        raise ValueError("start must be before end")
    span = (end_dt - start_dt).total_seconds()
    parsed = [(when, ds or [], us or []) for ts, ds, us in snapshots
              if (when := _parse(ts)) is not None and start_dt <= when <= end_dt]
    parsed.sort(key=lambda item: item[0])
    directions = []
    if parsed:
        _latest, latest_ds, latest_us = parsed[-1]
        for key, channels, index in (("ds", latest_ds, 1), ("us", latest_us, 2)):
            block = _direction(key, channels, [(item[0], item[index]) for item in parsed], start_dt, span)
            if block:
                directions.append(block)
    return {
        "start": start,
        "end": end,
        "cells": CELL_COUNT,
        "cell_minutes": round(span / 60 / CELL_COUNT, 2),
        "snapshots": len(parsed),
        "directions": directions,
    }


def localize_matrix(matrix: dict[str, Any], tz_name: str | None) -> dict[str, Any]:
    """Convert the matrix timestamps to local time for API responses."""
    from .tz import to_local

    if not tz_name:
        return matrix
    matrix["start"] = to_local(matrix["start"], tz_name)
    matrix["end"] = to_local(matrix["end"], tz_name)
    for block in matrix["directions"]:
        for row in block["deviating"] + block["others"]:
            if row["since"]:
                row["since"] = to_local(row["since"], tz_name)
    return matrix
