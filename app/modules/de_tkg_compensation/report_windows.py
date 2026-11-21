"""Evidence report windows, independent of the legal claim duration."""

from datetime import datetime, timedelta, timezone

from app.tz import UTC_FMT


def parse_timestamp(value: str) -> datetime:
    """Parse an ISO timestamp with Z read as UTC, never as the date-time separator."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def chunk_report_windows(window_from: str, window_to: str) -> list[dict[str, str | int]]:
    """Split an evidence range into report-compatible windows of at most 90 days."""
    start = parse_timestamp(window_from)
    end = parse_timestamp(window_to)
    if start.tzinfo is None or end.tzinfo is None or end < start:
        raise ValueError("invalid report window")
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=90), end)
        chunks.append({
            "index": len(chunks) + 1,
            "from": cursor.astimezone(timezone.utc).strftime(UTC_FMT),
            "to": chunk_end.astimezone(timezone.utc).strftime(UTC_FMT),
        })
        if chunk_end == end:
            break
        cursor = chunk_end + timedelta(seconds=1)
    return chunks
