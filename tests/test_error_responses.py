"""Unexpected failures answer with a fixed message; details stay in the log."""

import io
import threading
from types import SimpleNamespace

import pytest

from app.config import ConfigManager
from app.runtime import get_runtime
from app.storage import SnapshotStorage

DETAIL = "internal detail /data/.config_key"


def _fail(*_args, **_kwargs):
    raise RuntimeError(DETAIL)


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


@pytest.mark.parametrize(("path", "arrange", "kwargs", "status"), [
    ("/api/config", lambda mp, rt: mp.setattr(rt.config_manager, "save", _fail), {"json": {"language": "en"}}, 500),
    ("/api/demo/migrate", _patch_demo_purge, {}, 500),
    ("/api/poll", _patch_poll, {}, 500),
    ("/api/backup/scheduled", lambda mp, rt: mp.setattr("app.modules.backup.routes.create_backup_to_file", _fail), {}, 500),
    ("/api/speedtest/run", lambda mp, rt: mp.setattr("app.modules.speedtest.routes.requests.post", _fail), {}, 500),
    ("/api/bqm/import", lambda mp, rt: mp.setattr("app.modules.bqm.storage.BqmStorage.import_bqm_graph", _fail), {
        "data": {"files[]": (io.BytesIO(b"\x89PNG graph"), "graph.png"), "dates": "2026-01-01"},
        "content_type": "multipart/form-data",
    }, 200),
], ids=["config", "demo-migrate", "poll", "scheduled-backup", "speedtest-run", "bqm-import"])
def test_unexpected_failure_does_not_reach_the_client(app, monkeypatch, path, arrange, kwargs, status):
    arrange(monkeypatch, get_runtime(app))

    response = app.test_client().post(path, **kwargs)

    assert response.status_code == status
    assert DETAIL not in response.get_data(as_text=True)
