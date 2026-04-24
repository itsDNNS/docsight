"""Tests for fritzbox_cable segment utilization storage."""

import pytest
from app.storage.segment_utilization import SegmentUtilizationStorage


@pytest.fixture
def storage(tmp_path):
    db_path = str(tmp_path / "test.db")
    return SegmentUtilizationStorage(db_path)


class TestSave:
    def test_save_stores_record(self, storage):
        storage.save(6.2, 11.4, 0.05, 0.17)
        rows = storage.get_latest(1)
        assert len(rows) == 1
        assert rows[0]["ds_total"] == pytest.approx(6.2)
        assert rows[0]["us_total"] == pytest.approx(11.4)
        assert rows[0]["ds_own"] == pytest.approx(0.05)
        assert rows[0]["us_own"] == pytest.approx(0.17)
        assert "timestamp" in rows[0]

    def test_save_allows_nulls(self, storage):
        storage.save(None, None, None, None)
        rows = storage.get_latest(1)
        assert len(rows) == 1
        assert rows[0]["ds_total"] is None


class TestGetRange:
    def test_get_range_filters_by_time(self, storage):
        storage.save_at("2026-03-09T10:00:00Z", 1.0, 2.0, 0.1, 0.2)
        storage.save_at("2026-03-09T10:01:00Z", 3.0, 4.0, 0.3, 0.4)
        rows = storage.get_latest(10)
        assert len(rows) == 2
        start = "2000-01-01T00:00:00Z"
        end = "2099-01-01T00:00:00Z"
        ranged = storage.get_range(start, end)
        assert len(ranged) == 2

    def test_get_range_accepts_legacy_space_separated_query_timestamps(self, storage):
        storage.save_at("2026-03-09T10:00:00Z", 1.0, 2.0, 0.1, 0.2)
        storage.save_at("2026-03-09T10:01:00Z", 3.0, 4.0, 0.3, 0.4)
        ranged = storage.get_range("2026-03-09 09:59:00Z", "2026-03-09 10:00:30Z")
        assert len(ranged) == 1
        assert ranged[0]["ds_total"] == pytest.approx(1.0)

    def test_get_range_empty(self, storage):
        assert storage.get_range("2000-01-01T00:00:00Z", "2000-01-02T00:00:00Z") == []


class TestGetLatest:
    def test_get_latest_returns_most_recent_first(self, storage):
        storage.save_at("2026-03-09T10:00:00Z", 1.0, 2.0, 0.1, 0.2)
        storage.save_at("2026-03-09T10:01:00Z", 3.0, 4.0, 0.3, 0.4)
        rows = storage.get_latest(1)
        assert rows[0]["ds_total"] == pytest.approx(3.0)

    def test_get_latest_default_one(self, storage):
        storage.save(1.0, 2.0, 0.1, 0.2)
        rows = storage.get_latest()
        assert len(rows) == 1


class TestGetStats:
    def test_get_stats_computes_aggregates(self, storage):
        storage.save_at("2026-03-09T10:00:00Z", 5.0, 10.0, 0.1, 0.5)
        storage.save_at("2026-03-09T10:01:00Z", 15.0, 30.0, 0.3, 1.5)
        stats = storage.get_stats("2000-01-01T00:00:00Z", "2099-01-01T00:00:00Z")
        assert stats["ds_total_avg"] == pytest.approx(10.0)
        assert stats["ds_total_min"] == pytest.approx(5.0)
        assert stats["ds_total_max"] == pytest.approx(15.0)
        assert stats["us_total_avg"] == pytest.approx(20.0)
        assert stats["count"] == 2

    def test_get_stats_empty(self, storage):
        stats = storage.get_stats("2000-01-01T00:00:00Z", "2000-01-02T00:00:00Z")
        assert stats["count"] == 0


class TestDownsample:
    def test_downsample_aggregates_old_samples(self, storage):
        """Samples older than fine_after_days get aggregated into buckets."""
        # Insert 5 samples within the same 5-min bucket (14:00-14:04)
        storage.save_at("2020-01-01T14:00:00Z", 10.0, 20.0, 1.0, 2.0)
        storage.save_at("2020-01-01T14:01:00Z", 12.0, 22.0, 1.2, 2.2)
        storage.save_at("2020-01-01T14:02:00Z", 14.0, 24.0, 1.4, 2.4)
        storage.save_at("2020-01-01T14:03:00Z", 16.0, 26.0, 1.6, 2.6)
        storage.save_at("2020-01-01T14:04:00Z", 18.0, 28.0, 1.8, 2.8)
        assert len(storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")) == 5

        removed = storage.downsample(fine_after_days=0, fine_bucket_min=5,
                                     coarse_after_days=9999, coarse_bucket_min=15)
        assert removed == 4  # 5 rows -> 1 averaged row

        rows = storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")
        assert len(rows) == 1
        assert rows[0]["timestamp"] == "2020-01-01T14:00:00Z"
        assert rows[0]["ds_total"] == pytest.approx(14.0)  # avg(10,12,14,16,18)
        assert rows[0]["us_total"] == pytest.approx(24.0)

    def test_downsample_leaves_single_sample_buckets(self, storage):
        """Buckets with only 1 sample are not touched."""
        storage.save_at("2020-01-01T14:00:00Z", 10.0, 20.0, 1.0, 2.0)
        storage.save_at("2020-01-01T14:05:00Z", 12.0, 22.0, 1.2, 2.2)

        removed = storage.downsample(fine_after_days=0, fine_bucket_min=5,
                                     coarse_after_days=9999, coarse_bucket_min=15)
        assert removed == 0
        assert len(storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")) == 2

    def test_downsample_preserves_recent_data(self, storage):
        """Samples newer than fine_after_days are not downsampled."""
        storage.save_at("2020-01-01T14:00:00Z", 10.0, 20.0, 1.0, 2.0)
        storage.save_at("2020-01-01T14:01:00Z", 12.0, 22.0, 1.2, 2.2)
        # Use a cutoff in the past so both samples are "recent"
        removed = storage.downsample(fine_after_days=9999, fine_bucket_min=5,
                                     coarse_after_days=9999, coarse_bucket_min=15)
        assert removed == 0
        assert len(storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")) == 2

    def test_downsample_coarse_tier(self, storage):
        """Coarse tier aggregates into 15-min buckets."""
        for m in range(15):
            storage.save_at(f"2020-01-01T14:{m:02d}:00Z", float(m), float(m * 2), 0.1, 0.2)
        assert len(storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")) == 15

        removed = storage.downsample(fine_after_days=9999, fine_bucket_min=5,
                                     coarse_after_days=0, coarse_bucket_min=15)
        assert removed == 14  # 15 -> 1
        rows = storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")
        assert len(rows) == 1
        assert rows[0]["timestamp"] == "2020-01-01T14:00:00Z"

    def test_downsample_multiple_buckets(self, storage):
        """Multiple buckets are each aggregated independently."""
        # Bucket 14:00
        storage.save_at("2020-01-01T14:00:00Z", 10.0, 20.0, 1.0, 2.0)
        storage.save_at("2020-01-01T14:01:00Z", 20.0, 30.0, 2.0, 3.0)
        # Bucket 14:05
        storage.save_at("2020-01-01T14:05:00Z", 30.0, 40.0, 3.0, 4.0)
        storage.save_at("2020-01-01T14:06:00Z", 40.0, 50.0, 4.0, 5.0)

        removed = storage.downsample(fine_after_days=0, fine_bucket_min=5,
                                     coarse_after_days=9999, coarse_bucket_min=15)
        assert removed == 2  # 2 rows removed (4 -> 2)
        rows = storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")
        assert len(rows) == 2
        assert rows[0]["ds_total"] == pytest.approx(15.0)  # avg(10,20)
        assert rows[1]["ds_total"] == pytest.approx(35.0)  # avg(30,40)

    def test_downsample_empty_db(self, storage):
        assert storage.downsample() == 0

    def test_downsample_idempotent(self, storage):
        """Running downsample twice produces the same result."""
        storage.save_at("2020-01-01T14:00:00Z", 10.0, 20.0, 1.0, 2.0)
        storage.save_at("2020-01-01T14:01:00Z", 20.0, 30.0, 2.0, 3.0)

        storage.downsample(fine_after_days=0, fine_bucket_min=5,
                           coarse_after_days=9999, coarse_bucket_min=15)
        removed = storage.downsample(fine_after_days=0, fine_bucket_min=5,
                                     coarse_after_days=9999, coarse_bucket_min=15)
        assert removed == 0
        rows = storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")
        assert len(rows) == 1


class TestGetEvents:
    """Detect saturation events from raw 1-minute samples.

    Events: windows where ds_total or us_total stays >= threshold for
    at least min_minutes consecutive minute-spaced samples. Downstream
    and upstream are evaluated independently; a gap in the minute stream
    breaks a raw event.
    """

    def test_empty_range_returns_no_events(self, storage):
        events = storage.get_events(
            "2000-01-01T00:00:00Z", "2000-01-02T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert events == []

    def test_single_sample_above_threshold_below_min_duration(self, storage):
        storage.save_at("2026-03-09T10:00:00Z", 50.0, 50.0, 1.0, 1.0)
        storage.save_at("2026-03-09T10:01:00Z", 85.0, 50.0, 1.0, 1.0)
        storage.save_at("2026-03-09T10:02:00Z", 50.0, 50.0, 1.0, 1.0)
        events = storage.get_events(
            "2026-03-09T00:00:00Z", "2026-03-10T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert events == []

    def test_sustained_downstream_event(self, storage):
        storage.save_at("2026-03-09T10:00:00Z", 50.0, 30.0, 1.0, 0.5)
        storage.save_at("2026-03-09T10:01:00Z", 82.0, 30.0, 2.0, 0.5)
        storage.save_at("2026-03-09T10:02:00Z", 90.0, 30.0, 3.0, 0.5)
        storage.save_at("2026-03-09T10:03:00Z", 88.0, 30.0, 4.0, 0.5)
        storage.save_at("2026-03-09T10:04:00Z", 50.0, 30.0, 1.0, 0.5)
        events = storage.get_events(
            "2026-03-09T00:00:00Z", "2026-03-10T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert len(events) == 1
        ev = events[0]
        assert ev["direction"] == "downstream"
        assert ev["start"] == "2026-03-09T10:01:00Z"
        assert ev["end"] == "2026-03-09T10:03:00Z"
        assert ev["duration_minutes"] == 3
        assert ev["peak_total"] == pytest.approx(90.0)
        assert ev["peak_own"] == pytest.approx(3.0)
        assert ev["peak_neighbor_load"] == pytest.approx(87.0)
        assert ev["confidence"] == "high"

    def test_peak_neighbor_load_uses_max_across_run_not_peak_total_sample(self, storage):
        """Regression: peak neighbor must be max(total - own) across the run,
        not (total - own) at the single peak-total sample. If own traffic
        dominates at the peak total minute, the neighbor contribution is
        actually maximized elsewhere in the run."""
        # Run of 3 above-threshold minutes.
        #   t0: total=85, own=5   -> neighbor = 80
        #   t1: total=92, own=60  -> neighbor = 32  (peak total, low neighbor)
        #   t2: total=83, own=2   -> neighbor = 81  (peak neighbor)
        storage.save_at("2026-03-09T10:00:00Z", 85.0, 10.0, 5.0, 0.5)
        storage.save_at("2026-03-09T10:01:00Z", 92.0, 10.0, 60.0, 0.5)
        storage.save_at("2026-03-09T10:02:00Z", 83.0, 10.0, 2.0, 0.5)
        events = storage.get_events(
            "2026-03-09T00:00:00Z", "2026-03-10T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert len(events) == 1
        ev = events[0]
        assert ev["peak_total"] == pytest.approx(92.0)
        assert ev["peak_own"] == pytest.approx(60.0)
        # Must report the highest neighbor contribution seen in the run,
        # which occurs at t2 with neighbor = 83 - 2 = 81.
        assert ev["peak_neighbor_load"] == pytest.approx(81.0)

    def test_sustained_upstream_event(self, storage):
        storage.save_at("2026-03-09T12:00:00Z", 10.0, 40.0, 0.5, 0.5)
        storage.save_at("2026-03-09T12:01:00Z", 10.0, 81.0, 0.5, 2.0)
        storage.save_at("2026-03-09T12:02:00Z", 10.0, 85.0, 0.5, 3.0)
        storage.save_at("2026-03-09T12:03:00Z", 10.0, 92.0, 0.5, 4.0)
        storage.save_at("2026-03-09T12:04:00Z", 10.0, 40.0, 0.5, 0.5)
        events = storage.get_events(
            "2026-03-09T00:00:00Z", "2026-03-10T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert len(events) == 1
        ev = events[0]
        assert ev["direction"] == "upstream"
        assert ev["start"] == "2026-03-09T12:01:00Z"
        assert ev["end"] == "2026-03-09T12:03:00Z"
        assert ev["duration_minutes"] == 3
        assert ev["peak_total"] == pytest.approx(92.0)
        assert ev["peak_own"] == pytest.approx(4.0)
        assert ev["peak_neighbor_load"] == pytest.approx(88.0)
        assert ev["confidence"] == "high"

    def test_two_separate_events(self, storage):
        # Event 1: 10:00 through 10:02 (3 min) downstream
        for i, v in enumerate([85.0, 90.0, 82.0]):
            storage.save_at(f"2026-03-09T10:0{i}:00Z", v, 10.0, 1.0, 0.2)
        # Gap of low samples
        storage.save_at("2026-03-09T10:03:00Z", 30.0, 10.0, 1.0, 0.2)
        storage.save_at("2026-03-09T10:04:00Z", 30.0, 10.0, 1.0, 0.2)
        # Event 2: 10:05 through 10:07 (3 min) downstream
        for i, v in enumerate([81.0, 83.0, 84.0]):
            storage.save_at(f"2026-03-09T10:0{i+5}:00Z", v, 10.0, 1.0, 0.2)
        events = storage.get_events(
            "2026-03-09T00:00:00Z", "2026-03-10T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert len(events) == 2
        assert events[0]["start"] == "2026-03-09T10:00:00Z"
        assert events[0]["end"] == "2026-03-09T10:02:00Z"
        assert events[1]["start"] == "2026-03-09T10:05:00Z"
        assert events[1]["end"] == "2026-03-09T10:07:00Z"

    def test_missing_sample_breaks_raw_event(self, storage):
        # 4 above-threshold samples but with a 2-minute gap in the middle;
        # neither half alone meets the 3-minute requirement.
        storage.save_at("2026-03-09T10:00:00Z", 85.0, 10.0, 1.0, 0.2)
        storage.save_at("2026-03-09T10:01:00Z", 86.0, 10.0, 1.0, 0.2)
        # gap at 10:02 and 10:03
        storage.save_at("2026-03-09T10:04:00Z", 87.0, 10.0, 1.0, 0.2)
        storage.save_at("2026-03-09T10:05:00Z", 88.0, 10.0, 1.0, 0.2)
        events = storage.get_events(
            "2026-03-09T00:00:00Z", "2026-03-10T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert events == []

    def test_ds_and_us_events_are_independent(self, storage):
        # Same 3 minutes: downstream saturates, upstream does not.
        storage.save_at("2026-03-09T10:00:00Z", 85.0, 40.0, 1.0, 0.5)
        storage.save_at("2026-03-09T10:01:00Z", 90.0, 40.0, 1.0, 0.5)
        storage.save_at("2026-03-09T10:02:00Z", 82.0, 40.0, 1.0, 0.5)
        events = storage.get_events(
            "2026-03-09T00:00:00Z", "2026-03-10T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert len(events) == 1
        assert events[0]["direction"] == "downstream"

    def test_respects_time_range_filter(self, storage):
        for i in range(3):
            storage.save_at(f"2026-03-09T10:0{i}:00Z", 90.0, 10.0, 1.0, 0.2)
        events = storage.get_events(
            "2026-03-10T00:00:00Z", "2026-03-11T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert events == []


class TestMaterializedEvents:
    """Events must survive downsampling: peaks are captured into a dedicated
    events table before sample averaging smooths them away."""

    def test_events_survive_downsampling(self, storage):
        """Raw 1-min samples with a 3-minute saturation peak get downsampled
        into 5-min averages that fall below threshold. The event must still
        be returned by get_events() because it was materialized first."""
        # 5 raw samples in a 5-min bucket. Only 3 of them exceed 80%, so the
        # bucket average is ~68 (below threshold) after downsampling.
        storage.save_at("2020-01-01T14:00:00Z", 40.0, 10.0, 1.0, 0.1)
        storage.save_at("2020-01-01T14:01:00Z", 85.0, 10.0, 1.0, 0.1)
        storage.save_at("2020-01-01T14:02:00Z", 90.0, 10.0, 1.0, 0.1)
        storage.save_at("2020-01-01T14:03:00Z", 82.0, 10.0, 1.0, 0.1)
        storage.save_at("2020-01-01T14:04:00Z", 40.0, 10.0, 1.0, 0.1)

        # Sanity: event detectable on raw data.
        raw_events = storage.get_events(
            "2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert len(raw_events) == 1
        assert raw_events[0]["peak_total"] == pytest.approx(90.0)

        # Downsample aggressively — samples older than 0 days get averaged.
        storage.downsample(fine_after_days=0, fine_bucket_min=5,
                           coarse_after_days=9999, coarse_bucket_min=15)

        remaining = storage.get_range("2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z")
        assert len(remaining) == 1
        # The averaged sample falls below the 80% threshold — the event is no
        # longer detectable from raw data.
        assert remaining[0]["ds_total"] < 80

        # But the event survives via the materialized events table.
        preserved = storage.get_events(
            "2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert len(preserved) == 1
        ev = preserved[0]
        assert ev["direction"] == "downstream"
        assert ev["start"] == "2020-01-01T14:01:00Z"
        assert ev["end"] == "2020-01-01T14:03:00Z"
        assert ev["peak_total"] == pytest.approx(90.0)
        assert ev["duration_minutes"] == 3

    def test_materialize_idempotent(self, storage):
        """Running materialize twice must not create duplicate event rows."""
        for i, v in enumerate([85.0, 90.0, 82.0]):
            storage.save_at(f"2020-01-01T14:0{i}:00Z", v, 10.0, 1.0, 0.2)

        first = storage.materialize_events_before("2020-01-02T00:00:00Z")
        second = storage.materialize_events_before("2020-01-02T00:00:00Z")
        assert first == 1
        assert second == 0
        events = storage.get_events(
            "2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert len(events) == 1

    def test_materialize_skips_events_still_in_progress(self, storage):
        """Events whose end is at or past the cutoff may still be extending;
        they should not be stored yet to avoid locking in a truncated run."""
        # Run ends at 14:02, cutoff is 14:02 — end is NOT strictly before cutoff.
        for i, v in enumerate([85.0, 90.0, 82.0]):
            storage.save_at(f"2020-01-01T14:0{i}:00Z", v, 10.0, 1.0, 0.2)
        inserted = storage.materialize_events_before("2020-01-01T14:02:00Z")
        assert inserted == 0

        # With a later cutoff the event is fully historical and gets stored.
        inserted = storage.materialize_events_before("2020-01-01T14:05:00Z")
        assert inserted == 1

    def test_get_events_dedupes_materialized_with_raw(self, storage):
        """If both raw and materialized detection see the same event, it
        must appear only once in the merged output."""
        for i, v in enumerate([85.0, 90.0, 82.0]):
            storage.save_at(f"2020-01-01T14:0{i}:00Z", v, 10.0, 1.0, 0.2)
        storage.materialize_events_before("2020-01-02T00:00:00Z")
        # Raw data is still present (we did not downsample), so on-demand
        # detection would also produce the event. The merged result dedupes.
        events = storage.get_events(
            "2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z",
            threshold=80, min_minutes=3,
        )
        assert len(events) == 1

    def test_non_default_threshold_uses_raw_detection(self, storage):
        """Materialized events are stored with default parameters. Queries
        with non-default thresholds must still work (via raw detection on
        data that has not been downsampled)."""
        storage.save_at("2020-01-01T14:00:00Z", 70.0, 10.0, 1.0, 0.2)
        storage.save_at("2020-01-01T14:01:00Z", 72.0, 10.0, 1.0, 0.2)
        storage.save_at("2020-01-01T14:02:00Z", 71.0, 10.0, 1.0, 0.2)
        events = storage.get_events(
            "2020-01-01T00:00:00Z", "2020-01-02T00:00:00Z",
            threshold=65, min_minutes=3,
        )
        assert len(events) == 1
        assert events[0]["peak_total"] == pytest.approx(72.0)


class TestCleanup:
    def test_cleanup_removes_old_records(self, storage):
        import sqlite3
        conn = sqlite3.connect(storage.db_path)
        conn.execute(
            "INSERT INTO segment_utilization (timestamp, ds_total, us_total, ds_own, us_own) VALUES (?, ?, ?, ?, ?)",
            ("2020-01-01T00:00:00Z", 1.0, 2.0, 0.1, 0.2),
        )
        conn.commit()
        conn.close()
        storage.save(5.0, 10.0, 0.1, 0.5)
        deleted = storage.cleanup(days=365)
        assert deleted >= 1
        assert len(storage.get_latest(10)) == 1
