from app.storage.error_counters import unwrap_uint32_counter_series


def test_unwrap_uint32_counter_series_preserves_null_gap_for_wrap_detection():
    rows = [
        {"errors": 4_294_495_351},
        {"errors": None},
        {"errors": 692_254},
    ]

    unwrap_uint32_counter_series(rows, ["errors"])

    assert [row["errors"] for row in rows] == [
        4_294_495_351,
        None,
        4_295_659_550,
    ]


def test_unwrap_uint32_counter_series_treats_low_drop_as_reset_after_wrap():
    rows = [
        {"errors": 4_294_495_351},
        {"errors": 692_254},
        {"errors": 10_000},
    ]

    unwrap_uint32_counter_series(rows, ["errors"])

    assert [row["errors"] for row in rows] == [
        4_294_495_351,
        4_295_659_550,
        10_000,
    ]
