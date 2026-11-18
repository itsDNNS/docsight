"""Unexpected failures answer with a fixed message; details stay in the log."""

import io
import threading
from types import SimpleNamespace

import pytest

from app.config import ConfigManager
from app.runtime import get_runtime
from app.storage import SnapshotStorage
from tests.test_bqm_csv_parser import VALID_CSV

DETAIL = "internal detail /data/.config_key"
SEE_LOG = "See the DOCSight log for details."


def _fail(*_args, **_kwargs):
    raise RuntimeError(DETAIL)


def _fail_with_value_error(*_args, **_kwargs):
    raise ValueError(DETAIL)


@pytest.fixture
def app(make_app, builtin_module_loader_factory, tmp_path):
    config = ConfigManager(str(tmp_path / "data"))
    config.save({
        "modem_type": "fritzbox",
        "speedtest_tracker_url": "http://speedtest.local:8999",
        **{"speedtest_tracker_token": "[REDACTED]"},
    })
    storage = SnapshotStorage(str(tmp_path / "data" / "docsis_history.db"), max_days=7)
    return make_app(config_manager=config, storage=storage, module_loader_factory=builtin_module_loader_factory(config))


def _patch_demo_purge(monkeypatch, runtime):
    runtime.config_manager.save({"demo_mode": True})
    monkeypatch.setattr(runtime.storage, "purge_demo_data", _fail)


def _patch_poll(monkeypatch, runtime):
    runtime.modem_collector = SimpleNamespace(collect=_fail, _collect_lock=threading.Lock())


def _patch(target):
    return lambda monkeypatch, _runtime: monkeypatch.setattr(target, _fail)


def _upload(field, content, name, **form):
    return {"data": {field: (io.BytesIO(content), name), **form}, "content_type": "multipart/form-data"}


@pytest.mark.parametrize(("path", "arrange", "kwargs", "status", "body"), [
    ("/api/config", lambda mp, rt: mp.setattr(rt.config_manager, "save", _fail), {"json": {"language": "en"}},
     500, {"success": False, "error": f"Saving failed. {SEE_LOG}"}),
    ("/api/config", lambda mp, rt: mp.setattr(rt.config_manager, "save", _fail_with_value_error),
     {"json": {"language": "en"}}, 500, {"success": False, "error": f"Saving failed. {SEE_LOG}"}),
    ("/api/demo/migrate", _patch_demo_purge, {}, 500, {"success": False, "error": f"Demo migration failed. {SEE_LOG}"}),
    ("/api/poll", _patch_poll, {}, 500, {"success": False, "error": "Modem reading failed, see the DOCSight log"}),
    ("/api/backup/scheduled", _patch("app.modules.backup.routes.create_backup_to_file"), {},
     500, {"error": f"Backup failed. {SEE_LOG}"}),
    ("/api/speedtest/run", _patch("app.modules.speedtest.routes.requests.post"), {},
     500, {"success": False, "error": f"Speedtest start failed. {SEE_LOG}"}),
    ("/api/bqm/import", _patch("app.modules.bqm.storage.BqmStorage.import_bqm_graph"),
     _upload("files[]", b"\x89PNG graph", "graph.png", dates="2026-01-01"), 200, None),
    ("/api/bqm/import-csv", _patch("app.modules.bqm.storage.BqmStorage.store_csv_data"),
     _upload("file", VALID_CSV.encode(), "bqm.csv"), 500, {"error": f"Import failed. {SEE_LOG}"}),
], ids=["config", "config-value-error", "demo-migrate", "poll", "scheduled-backup", "speedtest-run", "bqm-import", "bqm-import-csv"])
def test_unexpected_failure_is_logged_but_not_returned(app, monkeypatch, caplog, path, arrange, kwargs, status, body):
    arrange(monkeypatch, get_runtime(app))

    response = app.test_client().post(path, **kwargs)

    assert response.status_code == status
    data = response.get_json()
    if body is None:
        assert data["errors"] == [{"filename": "graph.png", "error": "Import failed"}]
    else:
        assert data == body
    assert DETAIL not in response.get_data(as_text=True)
    assert DETAIL in caplog.text


@pytest.mark.parametrize("payload", [["a", "list"], "text", 42])
def test_settings_save_needs_a_json_object(app, payload):
    response = app.test_client().post("/api/config", json=payload)
    assert (response.status_code, response.get_json()) == (400, {"success": False, "error": "No data"})
