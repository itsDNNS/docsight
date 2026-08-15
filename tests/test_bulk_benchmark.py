"""Structural bulk-write benchmark; timing is evidence, not a gate."""

from __future__ import annotations

import time
import tracemalloc

from app.storage import SnapshotStorage
from app.storage import sqlite as sqlite_owner
from tests.sqlite_helpers import install_counting_connect


def test_five_thousand_rows_use_one_transaction_and_one_executemany(tmp_path, monkeypatch):
    db_path = tmp_path / "benchmark.db"
    storage = SnapshotStorage(str(db_path), max_days=7)
    instances = install_counting_connect(monkeypatch, sqlite_owner)
    rows = [
        {
            "timestamp": f"2026-01-01T00:{index % 60:02d}:{index % 60:02d}Z",
            "severity": "info",
            "event_type": "benchmark",
            "message": f"event-{index}",
            "details": None,
        }
        for index in range(5_000)
    ]

    tracemalloc.start()
    started = time.perf_counter()
    count = storage.save_events(rows)
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"bulk_5000 wall_s={elapsed:.6f} peak_kb={peak // 1024}")
    assert count == 5_000
    assert len(instances) == 1
    assert instances[0].commit_calls == 1
    assert instances[0].executemany_calls == 1
    assert storage.get_event_count() == 5_000
