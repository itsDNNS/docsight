"""Ordered, shape-aware SQLite migration contracts."""

from __future__ import annotations

import importlib
import logging
import sqlite3

import pytest

from tests.sqlite_helpers import data_digest, schema_digest


def _migrations_module():
    return importlib.import_module("app.storage.migrations")


def _registry_ids(db_path):
    with sqlite3.connect(db_path) as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT id FROM _docsight_migrations ORDER BY applied_at, id"
            )
        ]


def test_generic_migrations_run_in_order_and_second_run_is_noop(tmp_path):
    migrations = _migrations_module()
    db_path = tmp_path / "ordered.db"
    observed = []

    def apply_first(conn):
        observed.append("first")
        conn.execute("CREATE TABLE first_table (value TEXT)")

    def apply_second(conn):
        observed.append("second")
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='first_table'"
        ).fetchone()
        conn.execute("CREATE TABLE second_table (value TEXT)")

    sequence = (
        migrations.Migration("test-0001", apply_first, lambda conn: False),
        migrations.Migration("test-0002", apply_second, lambda conn: False),
    )

    assert migrations.run_migrations(str(db_path), sequence) == ["test-0001", "test-0002"]
    first_digest = schema_digest(db_path)
    assert migrations.run_migrations(str(db_path), sequence) == []
    assert schema_digest(db_path) == first_digest
    assert observed == ["first", "second"]
    assert _registry_ids(db_path) == ["test-0001", "test-0002"]


def test_completed_migration_set_does_not_open_an_empty_write_transaction(
    tmp_path, monkeypatch
):
    migrations = _migrations_module()
    db_path = tmp_path / "complete.db"
    sequence = (
        migrations.Migration(
            "test-0001-complete",
            lambda conn: conn.execute("CREATE TABLE completed (value TEXT)"),
            lambda conn: False,
        ),
    )
    migrations.run_migrations(str(db_path), sequence)

    monkeypatch.setattr(
        migrations,
        "write_transaction",
        lambda *args, **kwargs: pytest.fail("completed migrations must not take a write lock"),
    )
    assert migrations.run_migrations(str(db_path), sequence) == []


def test_shape_probe_stamps_without_applying(tmp_path):
    migrations = _migrations_module()
    db_path = tmp_path / "adopt.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE already_current (value TEXT)")
    called = False

    def forbidden(conn):
        nonlocal called
        called = True

    migration = migrations.Migration(
        "test-0001-adopt", forbidden,
        lambda conn: conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='already_current'"
        ).fetchone() is not None,
    )

    assert migrations.run_migrations(str(db_path), [migration]) == ["test-0001-adopt"]
    assert called is False
    assert _registry_ids(db_path) == ["test-0001-adopt"]


def test_failed_migration_rolls_back_shape_and_registry_then_retries(tmp_path):
    migrations = _migrations_module()
    db_path = tmp_path / "retry.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE retained (value TEXT)")
        conn.execute("INSERT INTO retained VALUES ('kept')")
    before_data = data_digest(db_path)

    def fail(conn):
        conn.execute("CREATE TABLE partial (value TEXT)")
        conn.execute("INSERT INTO retained VALUES ('discarded')")
        raise RuntimeError("injected migration failure")

    failed = migrations.Migration("test-0001-retry", fail, lambda conn: False)
    with pytest.raises(RuntimeError, match="injected migration failure"):
        migrations.run_migrations(str(db_path), [failed])

    assert data_digest(db_path) == before_data
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE name='partial'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM _docsight_migrations WHERE id='test-0001-retry'"
        ).fetchone() is None

    successful = migrations.Migration(
        "test-0001-retry",
        lambda conn: conn.execute("CREATE TABLE completed (value TEXT)"),
        lambda conn: False,
    )
    assert migrations.run_migrations(str(db_path), [successful]) == ["test-0001-retry"]


def test_fresh_core_reaches_head_and_preserves_schema_version(tmp_path):
    migrations = _migrations_module()
    db_path = tmp_path / "fresh.db"

    applied = migrations.run_migrations(str(db_path), migrations.CORE_MIGRATIONS)
    assert applied == [migration.migration_id for migration in migrations.CORE_MIGRATIONS]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT value FROM _docsight_meta WHERE key='schema_version'"
        ).fetchone() == ("2",)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)")}
        assert {"is_demo", "raw_json", "analysis_meta_json"} <= columns
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert migrations.run_migrations(str(db_path), migrations.CORE_MIGRATIONS) == []


def test_unversioned_current_tables_replay_idempotent_schema_to_restore_indexes(tmp_path):
    migrations = _migrations_module()
    db_path = tmp_path / "missing-indexes.db"

    with sqlite3.connect(db_path) as conn:
        for statement in migrations.CORE_SCHEMA:
            if not statement.lstrip().upper().startswith("CREATE INDEX"):
                conn.execute(statement)
        for statement in migrations.SEGMENT_SCHEMA:
            if not statement.lstrip().upper().startswith("CREATE UNIQUE INDEX"):
                conn.execute(statement)

    migrations.run_migrations(str(db_path), migrations.CORE_MIGRATIONS)
    migrations.run_migrations(str(db_path), migrations.SEGMENT_MIGRATIONS)

    with sqlite3.connect(db_path) as conn:
        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name NOT LIKE 'sqlite_%'"
            )
        }
    assert {
        "idx_snapshots_ts",
        "idx_events_ts",
        "idx_events_ack",
        "idx_events_type_ts",
        "idx_snapshots_ts_id",
        "idx_weather_ts",
        "idx_pwa_push_subscriptions_updated",
        "idx_sc_exec_status",
        "idx_sc_exec_created",
        "idx_segment_util_ts",
        "idx_segment_util_events_key",
    } <= indexes


def test_legacy_snapshot_shape_is_upgraded_without_data_change(tmp_path):
    migrations = _migrations_module()
    db_path = tmp_path / "legacy-snapshot.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL, "
            "summary_json TEXT NOT NULL, ds_channels_json TEXT NOT NULL, us_channels_json TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO snapshots VALUES (1, '2026-01-01T00:00:00Z', '{}', '[]', '[]')"
        )

    migrations.run_migrations(str(db_path), migrations.CORE_MIGRATIONS)
    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT id, timestamp, summary_json, ds_channels_json, us_channels_json FROM snapshots"
        ).fetchall() == [(1, "2026-01-01T00:00:00Z", "{}", "[]", "[]")]
        columns = {row[1] for row in conn.execute("PRAGMA table_info(snapshots)")}
        assert {"is_demo", "raw_json", "analysis_meta_json"} <= columns


def test_exact_legacy_incidents_shape_is_copied_transactionally(tmp_path):
    migrations = _migrations_module()
    db_path = tmp_path / "legacy-journal.db"
    attachment = b"\x00legacy\xff"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE incidents (id INTEGER PRIMARY KEY, date TEXT NOT NULL, title TEXT NOT NULL, "
            "description TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE incident_attachments (id INTEGER PRIMARY KEY, incident_id INTEGER NOT NULL, "
            "filename TEXT NOT NULL, mime_type TEXT NOT NULL, data BLOB NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO incidents VALUES (7, '2026-01-01', 'Legacy', NULL, 'created', 'updated')"
        )
        conn.execute(
            "INSERT INTO incident_attachments VALUES (9, 7, 'proof.bin', 'application/octet-stream', ?, 'created')",
            (attachment,),
        )

    migrations.run_migrations(str(db_path), migrations.CORE_MIGRATIONS)
    with sqlite3.connect(db_path) as conn:
        entry = conn.execute(
            "SELECT id, date, title, description, created_at, updated_at FROM journal_entries"
        ).fetchone()
        copied = conn.execute(
            "SELECT id, entry_id, filename, mime_type, data, created_at FROM journal_attachments"
        ).fetchone()
        assert entry == (7, "2026-01-01", "Legacy", None, "created", "updated")
        assert copied == (9, 7, "proof.bin", "application/octet-stream", attachment, "created")
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='incident_attachments'"
        ).fetchone() is None


def test_legacy_incident_orphans_do_not_block_startup_or_lose_attachment_data(
    tmp_path, caplog
):
    migrations = _migrations_module()
    db_path = tmp_path / "legacy-journal-orphan.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE incidents (id INTEGER PRIMARY KEY, date TEXT NOT NULL, title TEXT NOT NULL, "
            "description TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE incident_attachments (id INTEGER PRIMARY KEY, incident_id INTEGER NOT NULL, "
            "filename TEXT NOT NULL, mime_type TEXT NOT NULL, data BLOB NOT NULL, created_at TEXT NOT NULL)"
        )
        conn.execute(
            "INSERT INTO incidents VALUES (7, '2026-01-01', 'Legacy', NULL, 'created', 'updated')"
        )
        conn.executemany(
            "INSERT INTO incident_attachments VALUES (?, ?, ?, ?, ?, ?)",
            [
                (9, 7, "valid.bin", "application/octet-stream", b"valid", "created"),
                (10, 999, "orphan.bin", "application/octet-stream", b"orphan", "created"),
            ],
        )

    with caplog.at_level(logging.WARNING):
        migrations.run_migrations(str(db_path), migrations.CORE_MIGRATIONS)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT id, entry_id, data FROM journal_attachments"
        ).fetchall() == [(9, 7, b"valid")]
        assert conn.execute(
            "SELECT id, incident_id, data FROM incident_attachments ORDER BY id"
        ).fetchall() == [(9, 7, b"valid"), (10, 999, b"orphan")]
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert "orphaned row" in caplog.text.lower()
    assert migrations.run_migrations(str(db_path), migrations.CORE_MIGRATIONS) == []


def test_hybrid_incidents_shape_is_warned_stamped_and_untouched(tmp_path, caplog):
    migrations = _migrations_module()
    db_path = tmp_path / "hybrid.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE incidents (id INTEGER PRIMARY KEY, title TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute(
            "CREATE TABLE journal_entries (id INTEGER PRIMARY KEY, title TEXT NOT NULL, is_demo INTEGER NOT NULL DEFAULT 0)"
        )
        conn.execute("INSERT INTO incidents VALUES (1, 'old', 0)")
        conn.execute("INSERT INTO journal_entries VALUES (2, 'new', 0)")
    before = data_digest(db_path)

    with caplog.at_level(logging.WARNING):
        migrations.run_migrations(str(db_path), migrations.CORE_MIGRATIONS)

    after = data_digest(db_path, exclude={"_docsight_meta", "snapshots", "device_state", "events", "weather_data", "api_tokens", "pwa_push_subscriptions", "smart_capture_executions"})
    before_counts, before_hash = before
    after_counts, after_hash = after
    assert after_counts["incidents"] == before_counts["incidents"]
    assert after_counts["journal_entries"] == before_counts["journal_entries"]
    with sqlite3.connect(db_path) as conn:
        assert conn.execute("SELECT * FROM incidents").fetchall() == [(1, "old", 0)]
        assert conn.execute("SELECT * FROM journal_entries").fetchall() == [(2, "new", 0)]
    assert "hybrid" in caplog.text.lower()
    assert "core-0002-incidents-to-journal" in _registry_ids(db_path)


def test_unknown_incidents_shape_is_warned_stamped_and_not_renamed(tmp_path, caplog):
    migrations = _migrations_module()
    db_path = tmp_path / "unknown-incidents.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "CREATE TABLE incidents (id INTEGER PRIMARY KEY, title TEXT NOT NULL, payload BLOB)"
        )
        conn.execute("INSERT INTO incidents VALUES (1, 'unknown', ?)", (b"kept",))

    with caplog.at_level(logging.WARNING):
        migrations.run_migrations(str(db_path), migrations.CORE_MIGRATIONS)

    with sqlite3.connect(db_path) as conn:
        assert conn.execute(
            "SELECT id, title, payload FROM incidents"
        ).fetchall() == [(1, "unknown", b"kept")]
        assert conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='journal_entries'"
        ).fetchone() is None
    assert "unknown incidents schema" in caplog.text.lower()
    assert "core-0002-incidents-to-journal" in _registry_ids(db_path)


@pytest.mark.parametrize(
    ("module_name", "legacy_sql", "table", "required_columns"),
    [
        (
            "weather",
            "CREATE TABLE weather_data (timestamp TEXT PRIMARY KEY, temperature REAL NOT NULL)",
            "weather_data",
            {"is_demo"},
        ),
        (
            "journal",
            "CREATE TABLE journal_entries (id INTEGER PRIMARY KEY, is_demo INTEGER DEFAULT 0);"
            "CREATE TABLE journal_attachments (id INTEGER PRIMARY KEY);"
            "CREATE TABLE incidents (id INTEGER PRIMARY KEY, name TEXT)",
            "incidents",
            {"is_demo"},
        ),
        (
            "speedtest",
            "CREATE TABLE speedtest_results (id INTEGER PRIMARY KEY, timestamp TEXT NOT NULL);"
            "CREATE TABLE speedtest_meta (key TEXT PRIMARY KEY, value TEXT)",
            "speedtest_results",
            {"server_id", "server_name", "is_demo", "result_url", "external_ip"},
        ),
        (
            "bqm",
            "CREATE TABLE bqm_graphs (id INTEGER PRIMARY KEY, date TEXT, timestamp TEXT, image_blob BLOB)",
            "bqm_graphs",
            {"is_demo"},
        ),
        (
            "bnetz",
            "CREATE TABLE bnetz_measurements (id INTEGER PRIMARY KEY, date TEXT, timestamp TEXT)",
            "bnetz_measurements",
            {"source", "is_demo"},
        ),
        (
            "connection_monitor",
            "CREATE TABLE connection_targets (id INTEGER PRIMARY KEY, label TEXT, host TEXT, created_at REAL)",
            "connection_targets",
            {"is_demo"},
        ),
    ],
)
def test_evidenced_module_legacy_shapes_reach_head_idempotently(
    tmp_path, module_name, legacy_sql, table, required_columns
):
    migrations = _migrations_module()
    module_migrations = importlib.import_module(
        f"app.modules.{module_name}.migrations"
    ).MIGRATIONS
    db_path = tmp_path / f"{module_name}.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript(legacy_sql)

    applied = migrations.run_migrations(str(db_path), module_migrations)
    first_digest = schema_digest(db_path)

    assert applied == [migration.migration_id for migration in module_migrations]
    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        assert required_columns <= columns
        assert conn.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    assert migrations.run_migrations(str(db_path), module_migrations) == []
    assert schema_digest(db_path) == first_digest
