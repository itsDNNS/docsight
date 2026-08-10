"""Tests for modulation trend summaries."""

from app.modules.modulation.engine import compute_trend
from tests.modulation.factories import (
    make_channels as _make_channels,
    make_snapshot as _make_snapshot,
)


class TestComputeTrend:
    def test_returns_per_day_data(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["64QAM", "4QAM"])),
            _make_snapshot("2026-03-02T10:00:00Z", us_channels=_make_channels(["256QAM"])),
        ]
        trend = compute_trend(snaps, "us", "UTC")
        assert len(trend) == 2
        assert trend[0]["date"] == "2026-03-01"
        assert trend[0]["health_index"] is not None
        assert trend[0]["dominant_modulation"] is not None

    def test_empty(self):
        trend = compute_trend([], "us", "UTC")
        assert trend == []

    def test_trend_fields_present(self):
        snaps = [
            _make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["64QAM"])),
        ]
        trend = compute_trend(snaps, "us", "UTC")
        assert len(trend) == 1
        entry = trend[0]
        assert "date" in entry
        assert "health_index" in entry
        assert "low_qam_pct" in entry
        assert "dominant_modulation" in entry
        assert "sample_count" in entry

    def test_trend_multi_day_order(self):
        snaps = [
            _make_snapshot("2026-03-03T10:00:00Z", us_channels=_make_channels(["64QAM"])),
            _make_snapshot("2026-03-01T10:00:00Z", us_channels=_make_channels(["4QAM"])),
            _make_snapshot("2026-03-02T10:00:00Z", us_channels=_make_channels(["256QAM"])),
        ]
        trend = compute_trend(snaps, "us", "UTC")
        dates = [t["date"] for t in trend]
        assert dates == sorted(dates)
