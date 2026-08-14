"""Focused backend contracts for the demo-first setup path."""

import json
import sqlite3
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.collectors import DemoCollector, discover_collectors
from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.runtime import current_runtime


@pytest.fixture
def fresh_demo_client(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    data_dir = tmp_path / "data"
    manager = ConfigManager(str(data_dir))
    storage = SnapshotStorage(str(tmp_path / "history.db"), max_days=0)
    callbacks = []
    current_runtime().config_manager = manager
    current_runtime().on_config_changed = lambda: callbacks.append("changed")
    current_runtime().storage = storage
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, manager, storage, callbacks, data_dir


def test_demo_start_activates_fresh_instance_with_stable_contract(fresh_demo_client):
    client, manager, _storage, callbacks, data_dir = fresh_demo_client

    response = client.post("/api/demo/start", json={})

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "demo_mode": True,
        "status": "active",
    }
    assert manager.is_demo_mode() is True
    assert callbacks == ["changed"]
    assert json.loads((data_dir / "config.json").read_text(encoding="utf-8")) == {
        "demo_mode": True,
    }


def test_demo_start_rejects_non_json_mutation(fresh_demo_client):
    client, manager, _storage, callbacks, _data_dir = fresh_demo_client

    response = client.post("/api/demo/start", data="")

    assert response.status_code == 415
    assert response.get_json() == {
        "success": False,
        "demo_mode": False,
        "status": "invalid_request",
    }
    assert manager.is_demo_mode() is False
    assert callbacks == []


def test_demo_start_is_idempotent_while_active(fresh_demo_client):
    client, manager, _storage, callbacks, _data_dir = fresh_demo_client

    first = client.post("/api/demo/start", json={})
    second = client.post("/api/demo/start", json={})

    assert first.get_json() == second.get_json()
    assert manager.is_demo_mode() is True
    assert callbacks == ["changed"]


def test_demo_start_rolls_back_when_runtime_activation_fails(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    data_dir = tmp_path / "data"
    manager = ConfigManager(str(data_dir))
    callbacks = []

    def on_config_changed():
        callbacks.append("changed")
        if len(callbacks) == 1:
            raise RuntimeError("activation failed")

    current_runtime().config_manager = manager
    current_runtime().on_config_changed = on_config_changed
    current_runtime().storage = SnapshotStorage(str(tmp_path / "history.db"), max_days=0)
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post("/api/demo/start", json={})

    assert response.status_code == 500
    assert response.get_json() == {
        "success": False,
        "demo_mode": False,
        "status": "error",
    }
    assert manager.is_demo_mode() is False
    assert callbacks == ["changed", "changed"]
    assert json.loads((data_dir / "config.json").read_text(encoding="utf-8")) == {
        "demo_mode": False,
    }


def test_demo_start_rejects_configured_live_instance(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({"modem_type": "generic", "modem_url": "http://192.168.100.1"})
    callbacks = []
    current_runtime().config_manager = manager
    current_runtime().on_config_changed = lambda: callbacks.append("changed")
    current_runtime().storage = SnapshotStorage(str(tmp_path / "history.db"), max_days=0)
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post("/api/demo/start", json={})

    assert response.status_code == 409
    assert response.get_json() == {
        "success": False,
        "demo_mode": False,
        "status": "live_configured",
    }
    assert callbacks == []


def test_demo_start_requires_browser_session_when_auth_is_enabled(tmp_path, monkeypatch):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({"admin_password": "secret"})
    current_runtime().config_manager = manager
    current_runtime().storage = SnapshotStorage(str(tmp_path / "history.db"), max_days=0)
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post(
            "/api/demo/start",
            json={},
            headers={"Authorization": "Bearer not-a-browser-session"},
        )

    assert response.status_code == 403
    assert manager.is_demo_mode() is False


@pytest.mark.parametrize(
    ("next_choice", "next_path"),
    (("connect", "/setup?connect=1"), ("exit", "/setup")),
)
def test_demo_exit_uses_existing_purge_path_and_returns_next_path(
    tmp_path, monkeypatch, next_choice, next_path
):
    monkeypatch.delenv("DEMO_MODE", raising=False)
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({"demo_mode": True})
    storage = SnapshotStorage(str(tmp_path / "history.db"), max_days=0)
    callbacks = []
    current_runtime().config_manager = manager
    current_runtime().on_config_changed = lambda: callbacks.append("changed")
    current_runtime().storage = storage
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post("/api/demo/migrate", json={"next": next_choice})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["success"] is True
    assert payload["next"] == next_path
    assert manager.is_demo_mode() is False
    assert callbacks == ["changed"]


def test_demo_exit_purges_only_demo_connection_monitor_targets(tmp_path, monkeypatch):
    from app.modules.connection_monitor.storage import ConnectionMonitorStorage

    monkeypatch.delenv("DEMO_MODE", raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({"demo_mode": True})
    current_runtime().config_manager = manager
    current_runtime().storage = SnapshotStorage(str(tmp_path / "history.db"), max_days=0)
    app.config["TESTING"] = True

    connection_storage = ConnectionMonitorStorage(
        str(tmp_path / "connection_monitor.db")
    )
    user_id = connection_storage.create_target("User", "192.0.2.1")
    demo_id = connection_storage.create_target(
        "Demo", "198.51.100.1", is_demo=True
    )
    connection_storage.save_samples([
        {"target_id": user_id, "timestamp": 1.0, "latency_ms": 8.0,
         "timeout": False, "probe_method": "tcp"},
        {"target_id": demo_id, "timestamp": 1.0, "latency_ms": 18.0,
         "timeout": False, "probe_method": "tcp"},
    ])

    with app.test_client() as client:
        response = client.post("/api/demo/migrate", json={"next": "exit"})

    assert response.status_code == 200
    assert connection_storage.get_target(user_id) is not None
    assert len(connection_storage.get_samples(user_id)) == 1
    assert connection_storage.get_target(demo_id) is None
    assert connection_storage.get_samples(demo_id) == []


def test_environment_forced_demo_cannot_be_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("DEMO_MODE", "1")
    manager = ConfigManager(str(tmp_path / "data"))
    storage = SnapshotStorage(str(tmp_path / "history.db"), max_days=0)
    storage.purge_demo_data = MagicMock(return_value=0)
    callbacks = []
    current_runtime().config_manager = manager
    current_runtime().on_config_changed = lambda: callbacks.append("changed")
    current_runtime().storage = storage
    app.config["TESTING"] = True

    assert manager.is_demo_mode_forced() is True
    with app.test_client() as client:
        response = client.post("/api/demo/migrate", json={"next": "exit"})

    assert response.status_code == 409
    assert response.get_json() == {
        "success": False,
        "error": "demo_mode_forced",
        "locked": True,
    }
    storage.purge_demo_data.assert_not_called()
    assert callbacks == []
    assert not (tmp_path / "data" / "config.json").exists()


def test_demo_initializes_local_module_tables_on_fresh_database(tmp_path):
    db_path = tmp_path / "fresh.db"
    collector = DemoCollector.__new__(DemoCollector)
    collector._storage = SimpleNamespace(db_path=str(db_path))

    collector._ensure_demo_module_tables()

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
    assert {
        "speedtest_results",
        "bqm_graphs",
        "bnetz_measurements",
        "weather_data",
    } <= tables


def test_demo_discovery_does_not_even_enumerate_module_collectors(tmp_path):
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({"demo_mode": True})
    module_loader = MagicMock()
    web = MagicMock()
    web.get_module_loader.return_value = module_loader
    analyzer = SimpleNamespace(analyze=MagicMock())

    collectors = discover_collectors(
        manager,
        MagicMock(),
        MagicMock(),
        None,
        web,
        analyzer,
    )

    assert len(collectors) == 1
    assert isinstance(collectors[0], DemoCollector)
    module_loader.get_enabled_modules.assert_not_called()


def test_demo_api_is_reserved_from_community_route_shadowing():
    from app.module_loader import _PROTECTED_API_PREFIXES

    assert any("/api/demo/start".startswith(prefix) for prefix in _PROTECTED_API_PREFIXES)
    assert any("/api/demo/migrate".startswith(prefix) for prefix in _PROTECTED_API_PREFIXES)
