from app.aggregation import Window, canonical_utc_timestamp, report_bounds
from app.tz import local_date_to_utc_range


def test_canonicalization_is_identity_on_stored_format():
    assert canonical_utc_timestamp("2026-05-01T01:02:03Z") == "2026-05-01T01:02:03Z"


def test_canonicalization_normalizes_offsets_naive_values_and_microseconds():
    assert canonical_utc_timestamp("2026-05-01T03:02:03+02:00") == "2026-05-01T01:02:03Z"
    assert canonical_utc_timestamp("2026-05-01T01:02:03") == "2026-05-01T01:02:03Z"
    assert canonical_utc_timestamp("2026-05-01T01:02:03.999Z") == "2026-05-01T01:02:03Z"
    assert canonical_utc_timestamp("not-a-timestamp") == "not-a-timestamp"


def test_report_bounds_use_requested_inclusive_window_or_observed_extremes():
    snapshots = [
        {"timestamp": "2026-05-02T00:00:00Z"},
        {"timestamp": "2026-05-01T00:00:00Z"},
    ]
    assert report_bounds(snapshots) == (
        "2026-05-01T00:00:00Z",
        "2026-05-02T00:00:00Z",
    )
    window = Window("2026-04-30T00:00:00Z", "2026-05-03T00:00:00Z")
    assert report_bounds(snapshots, window=window) == (window.start, window.end)
    assert report_bounds([]) == ("-", "-")


def test_existing_berlin_dst_day_windows_remain_inclusive():
    assert local_date_to_utc_range("2026-03-29", "Europe/Berlin") == (
        "2026-03-28T23:00:00Z",
        "2026-03-29T21:59:59Z",
    )
    assert local_date_to_utc_range("2026-10-25", "Europe/Berlin") == (
        "2026-10-24T22:00:00Z",
        "2026-10-25T22:59:59Z",
    )
