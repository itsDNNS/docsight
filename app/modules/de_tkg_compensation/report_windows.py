"""Evidence report windows, independent of the legal claim duration."""

from datetime import datetime, timedelta, timezone


def chunk_report_windows(window_from: str, window_to: str) -> list[dict[str, str | int]]:
    """Split an evidence range into report-compatible windows of at most 90 days."""
    start = datetime.fromisoformat(window_from.replace("Z", "+00:00"))
    end = datetime.fromisoformat(window_to.replace("Z", "+00:00"))
    if start.tzinfo is None or end.tzinfo is None or end < start:
        raise ValueError("invalid report window")
    chunks = []
    cursor = start
    while cursor <= end:
        chunk_end = min(cursor + timedelta(days=90), end)
        chunks.append({
            "index": len(chunks) + 1,
            "from": cursor.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "to": chunk_end.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
        if chunk_end == end:
            break
        cursor = chunk_end + timedelta(seconds=1)
    return chunks
