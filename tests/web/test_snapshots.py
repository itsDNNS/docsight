"""Tests for snapshot endpoints."""

import pytest

from app.web import init_storage
from app.storage import SnapshotStorage

class TestSnapshotsAPI:
    @pytest.fixture
    def storage_with_data(self, tmp_path, sample_analysis):
        storage = SnapshotStorage(str(tmp_path / "snap_test.db"), max_days=7)
        storage.save_snapshot(sample_analysis)
        return storage

    def test_snapshots_list(self, client, storage_with_data):
        init_storage(storage_with_data)
        resp = client.get("/api/snapshots")
        assert resp.status_code == 200
        data = resp.get_json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_snapshots_list_no_storage(self, client):
        init_storage(None)
        resp = client.get("/api/snapshots")
        assert resp.status_code == 200
        assert resp.get_json() == []

    def test_snapshot_by_timestamp(self, client, storage_with_data):
        init_storage(storage_with_data)
        timestamps = storage_with_data.get_snapshot_list()
        resp = client.get(f"/api/snapshots/{timestamps[0]}")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "summary" in data
        assert "ds_channels" in data

    def test_snapshot_not_found(self, client, storage_with_data):
        init_storage(storage_with_data)
        resp = client.get("/api/snapshots/1999-01-01T00:00:00Z")
        assert resp.status_code == 404

