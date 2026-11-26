import threading

import pytest

from app.storage.error_counters import UINT32_COUNTER_SIZE as PERIOD, unwrap_uint32_counter_series


def test_unwrap_uint32_counter_series_preserves_null_gap_for_wrap_detection():
    rows = [
        {"errors": 4_294_495_351},
        {"errors": None},
        {"errors": "bad"},
        {"errors": 692_254},
    ]

    unwrap_uint32_counter_series(rows, ["errors"])

    assert [row["errors"] for row in rows] == [
        4_294_495_351,
        None,
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


def _wrap_offset_by_loop(offset, raw, previous_unwrapped):
    """The per-period loop the arithmetic replaces, kept as the reference."""
    offset += PERIOD
    while raw + offset <= previous_unwrapped:
        offset += PERIOD
    return offset


@pytest.mark.parametrize(("offset", "raw", "previous_unwrapped"), [
    (0, 692_254, 4_294_495_351),
    (0, 0, PERIOD - 1),
    (PERIOD, 10, 2 * PERIOD - 5),
    (0, 5, 3 * PERIOD + 7),
    *[(0, 100, 100 + k * PERIOD + delta) for k in (0, 1, 2) for delta in (-1, 0, 1)],
    (2 * PERIOD, 0, PERIOD),
])
def test_wrap_offset_matches_the_per_period_loop(offset, raw, previous_unwrapped):
    from app.storage.error_counters import _wrap_offset  # imported here so the time-limit test also runs on older code

    assert _wrap_offset(offset, raw, previous_unwrapped) == _wrap_offset_by_loop(offset, raw, previous_unwrapped)


def test_unwrap_handles_a_maximal_counter_followed_by_zero_without_one_step_per_period():
    rows = [{"errors": 2**63 - 1}, {"errors": 0}]
    worker = threading.Thread(target=unwrap_uint32_counter_series, args=(rows, ["errors"]), daemon=True)
    worker.start()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert [row["errors"] for row in rows] == [2**63 - 1, 2**63]
