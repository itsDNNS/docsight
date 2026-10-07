"""The snapshot panel asks for the snapshot at a chart point and steps to its neighbours."""

import copy
from unittest.mock import patch

import pytest

from app.runtime import current_runtime
from app.storage import SnapshotStorage

# UTC; Berlin is two hours ahead in October.
TIMES = ["2026-10-06T08:00:00Z", "2026-10-06T08:15:00Z", "2026-10-06T08:30:00Z"]


@pytest.fixture
def storage(tmp_path, sample_analysis, config_mgr):
    config_mgr.save({"timezone": "Europe/Berlin"})
    storage = SnapshotStorage(str(tmp_path / "snap_at.db"), max_days=36500)
    for index, ts in enumerate(TIMES):
        analysis = copy.deepcopy(sample_analysis)
        analysis["summary"]["ds_uncorrectable_errors"] = 100 + index * 40
        with patch("app.storage.snapshot.utc_now", return_value=ts):
            storage.save_snapshot(analysis)
    current_runtime().storage = storage
    return storage


def test_nearest_snapshot_to_a_local_chart_time(client, storage):
    data = client.get("/api/snapshots/at?time=2026-10-06T10:20:00").get_json()
    assert data["snapshot"]["timestamp"] == "2026-10-06T10:15:00"
    assert data["previous_uncorrectable"] == 100
    assert data["snapshot"]["summary"]["ds_uncorrectable_errors"] == 140
    assert data["has_previous"] is True and data["has_next"] is True
    assert "raw_data" not in data["snapshot"]

    # Ties and points past either end resolve to the closest snapshot there is.
    assert client.get("/api/snapshots/at?time=2026-10-06T10:22:30").get_json()["snapshot"]["timestamp"] == "2026-10-06T10:15:00"
    assert client.get("/api/snapshots/at?time=2026-10-06T09:00:00").get_json()["snapshot"]["timestamp"] == "2026-10-06T10:00:00"
    assert client.get("/api/snapshots/at?time=2026-10-06T23:00:00").get_json()["snapshot"]["timestamp"] == "2026-10-06T10:30:00"


def test_stepping_to_the_previous_and_next_snapshot(client, storage):
    first = client.get("/api/snapshots/at?time=2026-10-06T10:15:00&step=-1").get_json()
    assert first["snapshot"]["timestamp"] == "2026-10-06T10:00:00"
    assert first["has_previous"] is False and first["previous_uncorrectable"] is None

    last = client.get("/api/snapshots/at?time=2026-10-06T10:15:00&step=1").get_json()
    assert last["snapshot"]["timestamp"] == "2026-10-06T10:30:00"
    assert last["has_next"] is False

    assert client.get("/api/snapshots/at?time=2026-10-06T10:30:00&step=1").status_code == 404


@pytest.mark.parametrize("query", ["", "?time=yesterday", "?time=2026-10-06T10:15:00&step=2"])
def test_invalid_requests_are_rejected(client, storage, query):
    assert client.get("/api/snapshots/at" + query).status_code == 400


def test_the_route_does_not_shadow_a_snapshot_lookup(client, storage):
    stored = storage.get_snapshot_list()[0]
    assert client.get(f"/api/snapshots/{stored}").status_code == 200
