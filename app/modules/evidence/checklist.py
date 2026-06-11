"""Evidence checklist assembly for the guided evidence journey."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

PRESENT = "present"
STALE = "stale"
MISSING = "missing"
OPTIONAL = "optional"
NOT_APPLICABLE = "not_applicable"

# Generous thresholds. The checklist is guidance, not an SLA monitor.
_STALE_HOURS = {
    "signal": 2,
    "speedtest": 4,
    "latency": 4,
}


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        normalized = value.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def _latest_ts(rows: Iterable[dict[str, Any]], timestamp_key: str = "timestamp") -> str | None:
    latest: datetime | None = None
    latest_raw: str | None = None
    for row in rows:
        raw = row.get(timestamp_key)
        parsed = _parse_ts(raw)
        if parsed is not None and (latest is None or parsed > latest):
            latest = parsed
            latest_raw = raw
    return latest_raw


def _is_stale(last_ts: str | None, window_end: str | None, hours: int) -> bool:
    last = _parse_ts(last_ts)
    end = _parse_ts(window_end)
    if last is None or end is None:
        return False
    return (end - last).total_seconds() > hours * 3600


def _item(
    key: str,
    status: str,
    count: int = 0,
    last_ts: str | None = None,
    action: dict[str, str] | None = None,
    hint_key: str | None = None,
    demo: bool = False,
) -> dict[str, Any]:
    return {
        "key": key,
        "status": status,
        "count": count,
        "last_ts": last_ts,
        "action": action or {},
        "label_key": f"docsight.evidence.item.{key}.label",
        "hint_key": hint_key or f"docsight.evidence.item.{key}.{status}",
        "demo": bool(demo),
    }


def _source_rows(timeline: Iterable[dict[str, Any]], *sources: str) -> list[dict[str, Any]]:
    wanted = set(sources)
    return [row for row in timeline if row.get("source") in wanted]


def _evidence_status(
    rows: list[dict[str, Any]],
    *,
    configured: bool = True,
    applicable: bool = True,
    optional_when_unconfigured: bool = True,
    window_end: str | None,
    stale_key: str | None = None,
) -> tuple[str, str | None]:
    if not applicable:
        return NOT_APPLICABLE, None
    if not configured and not rows:
        return (OPTIONAL if optional_when_unconfigured else MISSING), None
    if not rows:
        return MISSING, None
    last_ts = _latest_ts(rows)
    if stale_key and _is_stale(last_ts, window_end, _STALE_HOURS[stale_key]):
        return STALE, last_ts
    return PRESENT, last_ts


def build_checklist(
    window: dict[str, Any],
    *,
    timeline: list[dict[str, Any]],
    journal_entries: list[dict[str, Any]],
    bqm_rows: list[dict[str, Any]],
    capabilities: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build the stateless evidence checklist for an incident or selected window."""
    capabilities = capabilities or {}
    demo = bool(capabilities.get("demo_mode"))
    docsis_supported = bool(capabilities.get("docsis_supported", True))
    speedtest_configured = bool(capabilities.get("speedtest_configured", True))
    bqm_configured = bool(capabilities.get("bqm_configured", True))
    window_end = window.get("to")

    signal_rows = _source_rows(timeline, "modem")
    speedtest_rows = _source_rows(timeline, "speedtest")
    event_rows = _source_rows(timeline, "event", "events")
    bnetz_rows = _source_rows(timeline, "bnetz")

    signal_status, signal_last = _evidence_status(
        signal_rows,
        applicable=docsis_supported,
        window_end=window_end,
        stale_key="signal",
    )
    speed_status, speed_last = _evidence_status(
        speedtest_rows,
        configured=speedtest_configured,
        optional_when_unconfigured=True,
        window_end=window_end,
        stale_key="speedtest",
    )
    latency_status, latency_last = _evidence_status(
        bqm_rows,
        configured=bqm_configured,
        optional_when_unconfigured=True,
        window_end=window_end,
        stale_key="latency",
    )
    event_status, event_last = _evidence_status(
        event_rows,
        applicable=docsis_supported,
        optional_when_unconfigured=False,
        window_end=window_end,
    )
    journal_status = PRESENT if journal_entries else MISSING
    journal_last = _latest_ts(journal_entries, "date") or _latest_ts(journal_entries, "created_at")
    bnetz_status = PRESENT if bnetz_rows else OPTIONAL
    bnetz_last = _latest_ts(bnetz_rows)

    items = [
        _item("signal", signal_status, len(signal_rows), signal_last, {"view": "correlation"}, demo=demo),
        _item("speedtest", speed_status, len(speedtest_rows), speed_last, {"view": "speedtest"}, demo=demo),
        _item("latency", latency_status, len(bqm_rows), latency_last, {"view": "bqm"}, demo=demo),
        _item("events", event_status, len(event_rows), event_last, {"view": "events"}, demo=demo),
        _item("journal", journal_status, len(journal_entries), journal_last, {"view": "journal", "action": "add_note"}, demo=demo),
        _item("bnetz", bnetz_status, len(bnetz_rows), bnetz_last, {"view": "bnetz"}, demo=demo),
    ]
    evidence_ready = any(item["status"] in {PRESENT, STALE} for item in items)
    items.append(_item(
        "comparison",
        OPTIONAL,
        action={"view": "comparison"},
        hint_key="docsight.evidence.item.comparison.optional",
        demo=demo,
    ))
    items.append(_item(
        "review",
        OPTIONAL,
        action={"view": "correlation"},
        hint_key="docsight.evidence.item.review.optional",
        demo=demo,
    ))
    items.append(_item(
        "report",
        PRESENT if evidence_ready else MISSING,
        action={"action": "report"},
        hint_key="docsight.evidence.item.report.present" if evidence_ready else "docsight.evidence.item.report.missing",
        demo=demo,
    ))
    return items


def summarize_checklist(items: Iterable[dict[str, Any]]) -> dict[str, int]:
    """Return status counts for the checklist payload."""
    summary = {PRESENT: 0, STALE: 0, MISSING: 0, OPTIONAL: 0, NOT_APPLICABLE: 0}
    for item in items:
        status = item.get("status")
        if status in summary:
            summary[status] += 1
    return summary
