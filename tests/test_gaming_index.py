"""Gaming ratings describe complete measurements, without compensating for loss."""

import pytest

from app.gaming_index import compute_gaming_index


GOOD = {"ping_ms": 15, "jitter_ms": 3, "packet_loss_pct": 0}


def test_complete_measurement_preserves_values_and_scores():
    result = compute_gaming_index(GOOD)
    assert result["score"] == 100
    assert result["grade"] == "A"
    assert result["components"] == {
        "latency": {"score": 100, "value": 15, "unit": "ms"},
        "jitter": {"score": 100, "value": 3, "unit": "ms"},
        "packet_loss": {"score": 100, "value": 0, "unit": "%"},
    }


@pytest.mark.parametrize("field,value", [
    ("ping_ms", 150), ("jitter_ms", 60), ("packet_loss_pct", 100),
])
def test_good_metrics_cannot_mask_a_failed_component(field, value):
    result = compute_gaming_index({**GOOD, field: value})
    assert result["score"] == 0
    assert result["grade"] == "F"


@pytest.mark.parametrize("field", GOOD)
def test_every_measurement_is_required(field):
    partial = GOOD.copy()
    del partial[field]
    assert compute_gaming_index(partial) is None


@pytest.mark.parametrize("value", [None, True, "bad", float("nan"), float("inf"), -1, 101])
def test_invalid_measurements_are_unavailable(value):
    assert compute_gaming_index({**GOOD, "packet_loss_pct": value}) is None


def test_no_speedtest_is_unavailable():
    assert compute_gaming_index(None) is None
