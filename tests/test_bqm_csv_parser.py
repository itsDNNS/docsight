"""Tests for ThinkBroadband BQM CSV parsing."""

import pytest

from app.modules.bqm.csv_parser import parse_bqm_csv


VALID_CSV = (
    '"Timestamp","Sent Polls","Lost Polls","Min Latency (ns)","Ave Latency (ns)","Max Latency (ns)","Score"\n'
    '"2026-03-15T19:00:00+00:00","100","","30430000","33850000","52690000","1"\n'
    '"2026-03-15T19:01:40+00:00","100","2","30620000","34380000","54410000","201"\n'
)


class TestBqmCsvParser:
    def test_parse_valid_csv(self):
        rows = parse_bqm_csv(VALID_CSV)
        assert len(rows) == 2
        assert rows[0] == {
            "timestamp": "2026-03-15T19:00:00+00:00",
            "date": "2026-03-15",
            "sent_polls": 100,
            "lost_polls": 0,
            "latency_min_ms": 30.43,
            "latency_avg_ms": 33.85,
            "latency_max_ms": 52.69,
            "score": 1,
        }
        assert rows[1]["lost_polls"] == 2
        assert rows[1]["latency_avg_ms"] == 34.38

    def test_invalid_header_raises(self):
        with pytest.raises(ValueError, match="Invalid BQM CSV header"):
            parse_bqm_csv("bad,header\n1,2\n")

    def test_invalid_numeric_row_is_skipped(self):
        content = VALID_CSV + '"2026-03-15T19:03:20+00:00","100","","oops","1","2","1"\n'
        rows = parse_bqm_csv(content)
        assert len(rows) == 2
