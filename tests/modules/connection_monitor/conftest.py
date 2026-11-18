import os
import time
from unittest.mock import MagicMock, patch

import pytest

from app.app_factory import create_app
from app.config import ConfigManager
from app.modules.connection_monitor.routes import bp
from app.modules.connection_monitor.storage import ConnectionMonitorStorage
from app.runtime import get_runtime
from tests.conftest import OPEN_INSTANCE_ENVIRON


@pytest.fixture
def storage(tmp_path):
    return ConnectionMonitorStorage(str(tmp_path / "test_cm.db"))


@pytest.fixture
def cm_app(tmp_path, storage):
    """App with the connection monitor routes on a real storage; yields (app, storage, traceroute probe)."""
    app = create_app(config_manager=ConfigManager(str(tmp_path / "config")), environ=dict(OPEN_INSTANCE_ENVIRON), testing=True)
    app.register_blueprint(bp)

    mock_probe = MagicMock()
    mock_probe.capability_info.return_value = {"method": "tcp", "reason": "no ICMP permission"}
    mock_tr_probe = MagicMock()

    with patch("app.modules.connection_monitor.routes._get_cm_storage", return_value=storage), \
         patch("app.modules.connection_monitor.routes._get_traceroute_probe", return_value=mock_tr_probe), \
         patch("app.modules.connection_monitor.routes._get_probe_engine", return_value=mock_probe), \
         patch("app.modules.connection_monitor.routes._get_tz", return_value="UTC"):
        yield app, storage, mock_tr_probe


@pytest.fixture
def auth_client(cm_app):
    """Client with auth enforcement enabled via a mock config manager."""
    flask_app, storage, _ = cm_app
    mock_cfg = MagicMock()
    mock_cfg.get.side_effect = lambda key, default=None: {
        "admin_password": "hashed_pw",
    }.get(key, default)
    mock_cfg.data_dir = os.path.dirname(storage.db_path)
    get_runtime(flask_app).config_manager = mock_cfg
    with flask_app.app_context():
        from app.web_auth import _init_auth_state
        _init_auth_state()
        yield flask_app.test_client(), storage


@pytest.fixture
def range_samples(storage):
    """Target with latencies of 10, 20 and 30 ms plus one timeout in the last 40 s; returns (tid, now)."""
    tid = storage.create_target("Test", "1.1.1.1")
    now = time.time()
    storage.save_samples([
        {"target_id": tid, "timestamp": now - 40, "latency_ms": 10.0, "timeout": False, "probe_method": "tcp"},
        {"target_id": tid, "timestamp": now - 30, "latency_ms": 20.0, "timeout": False, "probe_method": "tcp"},
        {"target_id": tid, "timestamp": now - 20, "latency_ms": 30.0, "timeout": False, "probe_method": "tcp"},
        {"target_id": tid, "timestamp": now - 10, "latency_ms": None, "timeout": True, "probe_method": "tcp"},
    ])
    return tid, now
