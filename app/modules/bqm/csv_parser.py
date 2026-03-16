"""CSV parsing for ThinkBroadband BQM exports."""

import csv
import io
import logging

log = logging.getLogger("docsis.bqm.csv")

EXPECTED_COLUMNS = [
    "Timestamp",
    "Sent Polls",
    "Lost Polls",
    "Min Latency (ns)",
    "Ave Latency (ns)",
    "Max Latency (ns)",
    "Score",
]


def _ns_to_ms(value: str) -> float:
    return round(int(value) / 1_000_000, 2)


def parse_bqm_csv(content: str) -> list[dict]:
    """Parse ThinkBroadband BQM CSV into normalized dicts."""
    reader = csv.DictReader(io.StringIO(content))
    if reader.fieldnames != EXPECTED_COLUMNS:
        raise ValueError(
            "Invalid BQM CSV header: expected "
            + ", ".join(EXPECTED_COLUMNS)
        )

    rows = []
    for row in reader:
        try:
            timestamp = row["Timestamp"]
            rows.append({
                "timestamp": timestamp,
                "date": timestamp[:10],
                "sent_polls": int(row["Sent Polls"]),
                "lost_polls": int(row["Lost Polls"] or 0),
                "latency_min_ms": _ns_to_ms(row["Min Latency (ns)"]),
                "latency_avg_ms": _ns_to_ms(row["Ave Latency (ns)"]),
                "latency_max_ms": _ns_to_ms(row["Max Latency (ns)"]),
                "score": int(row["Score"]),
            })
        except (TypeError, ValueError) as exc:
            log.warning("Skipping invalid BQM CSV row at %s: %s", row.get("Timestamp", "?"), exc)
    return rows
