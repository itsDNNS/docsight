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


def test_unwrap_uint32_counter_series_handles_aggregate_drop_near_uint32_wrap():
    other_channels_total = 332_000_000
    rows = [
        {"errors": other_channels_total + 4_294_495_351},
        {"errors": other_channels_total + 692_254},
        {"errors": other_channels_total + 1_958_096},
    ]

    unwrap_uint32_counter_series(rows, ["errors"], allow_aggregate_wrap=True)

    assert [row["errors"] for row in rows] == [
        4_626_495_351,
        4_627_659_550,
        4_628_925_392,
    ]


def test_unwrap_uint32_counter_series_gates_aggregate_detection_by_default():
    other_channels_total = 332_000_000
    rows = [
        {"errors": other_channels_total + 4_294_495_351},
        {"errors": other_channels_total + 692_254},
    ]

    unwrap_uint32_counter_series(rows, ["errors"])

    assert [row["errors"] for row in rows] == [
        4_626_495_351,
        332_692_254,
    ]


def test_unwrap_uint32_counter_series_keeps_non_wrap_aggregate_drop_as_reset():
    rows = [
        {"errors": 2_000_000_000},
        {"errors": 1_500_000_000},
    ]

    unwrap_uint32_counter_series(rows, ["errors"], allow_aggregate_wrap=True)

    assert [row["errors"] for row in rows] == [
        2_000_000_000,
        1_500_000_000,
    ]


def test_unwrap_uint32_counter_series_handles_multiple_aggregate_wraps_between_rows():
    rows = [
        {"errors": 9_000_000_000},
        {"errors": 500_000_000},
    ]

    unwrap_uint32_counter_series(rows, ["errors"], allow_aggregate_wrap=True)

    assert [row["errors"] for row in rows] == [
        9_000_000_000,
        9_089_934_592,
    ]
