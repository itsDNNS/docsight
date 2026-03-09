"""Test that segment utilization data appears in correlation timeline."""

from unittest.mock import patch, MagicMock
import pytest


class TestCorrelationSegmentSource:
    @patch("app.storage.segment_utilization.SegmentUtilizationStorage")
    def test_segment_source_included(self, MockStorage, tmp_path):
        from app.storage import SnapshotStorage
        db_path = str(tmp_path / "test.db")
        storage = SnapshotStorage(db_path)

        mock_seg = MagicMock()
        mock_seg.get_range.return_value = [
            {"timestamp": "2026-03-09T14:30:00Z", "ds_total": 6.2, "us_total": 11.4, "ds_own": 0.05, "us_own": 0.17},
        ]
        MockStorage.return_value = mock_seg

        entries = storage.get_correlation_timeline(
            "2026-03-09T00:00:00Z", "2026-03-09T23:59:59Z", sources={"segment"}
        )
        segment_entries = [e for e in entries if e["source"] == "segment"]
        assert len(segment_entries) == 1
        assert segment_entries[0]["ds_total"] == pytest.approx(6.2)
        assert segment_entries[0]["us_total"] == pytest.approx(11.4)
