"""First-run Demo Mode route contracts."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from app.config import ConfigManager
from app.modules.connection_monitor.storage import ConnectionMonitorStorage
from app.runtime import RuntimeController
from app.web import app, get_runtime_controller, init_config, init_storage


@pytest.fixture
def demo_route_client(tmp_path):
    config = ConfigManager(str(tmp_path / "data"))
    storage = Mock()
    storage.purge_demo_data.return_value = 17
    callback = Mock()
    runtime = Mock(
        transaction_lock=threading.RLock(),
        stop_timeout=0.1,
    )
    runtime.quiesce.return_value = True
    init_config(
        config,
        on_config_changed=callback,
        runtime_controller=runtime,
    )
    init_storage(storage)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client, config, storage, callback


def test_demo_start_persists_only_demo_mode_and_reconfigures_runtime(demo_route_client):
    client, config, _storage, callback = demo_route_client

    response = client.post("/api/demo/start", json={})

    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert config.is_demo_mode() is True
    assert config.is_configured() is True
    assert config._file_config == {"demo_mode": True}
    assert json.loads(Path(config.config_path).read_text(encoding="utf-8")) == {
        "demo_mode": True,
    }
    callback.assert_called_once_with()


def test_demo_start_retries_runtime_activation_after_partial_failure(demo_route_client):
    client, config, _storage, callback = demo_route_client
    callback.side_effect = [RuntimeError("private runtime detail"), None, None]

    first = client.post("/api/demo/start", json={})

    assert first.status_code == 500
    assert first.get_json() == {"success": False, "error": "Demo start failed"}
    assert "private runtime detail" not in first.get_data(as_text=True)
    assert config.is_demo_mode() is False

    second = client.post("/api/demo/start", json={})

    assert second.status_code == 200
    assert second.get_json() == {"success": True}
    assert callback.call_count == 3


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
def test_config_callback_failure_rolls_back_and_demo_fallback_remains_available(
    demo_route_client,
    error_type,
):
    client, config, _storage, callback = demo_route_client
    internal_marker = "internal-callback-marker"
    callback.side_effect = [error_type(internal_marker), None, None]

    failed = client.post(
        "/api/config",
        json={"modem_type": "fritzbox", "modem_url": "http://192.0.2.1"},
    )

    assert failed.status_code == 500
    assert failed.get_json() == {
        "success": False,
        "error": "Config save failed",
    }
    assert internal_marker not in failed.get_data(as_text=True)
    assert config.is_configured() is False
    assert not Path(config.config_path).exists()

    fallback = client.post("/api/demo/start", json={})

    assert fallback.status_code == 200
    assert config.is_demo_mode() is True
    assert callback.call_count == 3


def test_config_save_failure_rolls_back_persisted_and_runtime_state(
    demo_route_client,
):
    client, config, _storage, callback = demo_route_client
    config.save({"language": "en"})
    before = config.snapshot()
    original_save = config.save

    def save_then_fail(data):
        original_save(data)
        raise RuntimeError("private-save-marker /var/internal")

    with patch.object(config, "save", side_effect=save_then_fail):
        response = client.post(
            "/api/config",
            json={"language": "de", "poll_interval": 120},
        )

    assert response.status_code == 500
    assert response.get_json() == {
        "success": False,
        "error": "Config save failed",
    }
    assert b"private-save-marker" not in response.data
    assert b"/var/internal" not in response.data
    assert config.snapshot() == before
    assert config.get("language") == "en"
    callback.assert_called_once_with()


def test_config_initial_fetch_exception_keeps_committed_config_and_runtime(
    demo_route_client,
):
    client, config, _storage, callback = demo_route_client
    config.save({"language": "de"})
    callback.reset_mock()
    bqm_url = (
        "https://www.thinkbroadband.com/broadband/monitoring/"
        "quality/share/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        "-2-y.csv"
    )

    with patch(
        "app.blueprints.config_bp.run_bqm_initial_fetch",
        side_effect=RuntimeError(
            "private-fetch-marker /srv/docsight/internal"
        ),
    ):
        response = client.post(
            "/api/config",
            json={
                "language": "fr",
                "poll_interval": 120,
                "bqm_url": bqm_url,
            },
        )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "bqm_initial_fetch": {
            "success": False,
            "error": "BQM initial fetch failed; configuration was saved",
        },
    }
    assert b"private-fetch-marker" not in response.data
    assert b"/srv/docsight/internal" not in response.data
    assert config.get("language") == "fr"
    assert config.get("poll_interval") == 120
    assert config.get("bqm_url") == bqm_url
    callback.assert_called_once_with()


def test_config_initial_fetch_error_result_keeps_committed_config_and_runtime(
    demo_route_client,
):
    client, config, _storage, callback = demo_route_client
    config.save({"language": "de"})
    callback.reset_mock()
    bqm_url = (
        "https://www.thinkbroadband.com/broadband/monitoring/"
        "quality/share/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"
        "-2-y.csv"
    )

    with patch(
        "app.blueprints.config_bp.run_bqm_initial_fetch",
        return_value={
            "success": False,
            "error": "private-result-marker /opt/internal",
        },
    ):
        response = client.post(
            "/api/config",
            json={
                "language": "nl",
                "poll_interval": 180,
                "bqm_url": bqm_url,
            },
        )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "bqm_initial_fetch": {
            "success": False,
            "error": "BQM initial fetch failed; configuration was saved",
        },
    }
    assert b"private-result-marker" not in response.data
    assert b"/opt/internal" not in response.data
    assert config.get("language") == "nl"
    assert config.get("poll_interval") == 180
    assert config.get("bqm_url") == bqm_url
    callback.assert_called_once_with()


@pytest.mark.parametrize(
    "payload",
    [
        {"modem_type": "generic"},
        {"modem_url": "http://192.0.2.1"},
        {
            "modem_type": "fritzbox",
            "modem_url": "http://192.0.2.1",
            "language": "de",
        },
    ],
)
def test_demo_mode_rejects_new_modem_settings_without_mutation(
    demo_route_client,
    payload,
):
    client, config, _storage, callback = demo_route_client
    config.save({"demo_mode": True, "language": "en"})
    before = config.snapshot()
    callback.reset_mock()

    response = client.post("/api/config", json=payload)

    assert response.status_code == 409
    assert response.get_json() == {
        "success": False,
        "error": (
            "Modem connection settings cannot be changed "
            "while Demo Mode is active"
        ),
    }
    assert config.snapshot() == before
    callback.assert_not_called()


def test_demo_mode_keeps_non_connection_settings_saveable(demo_route_client):
    client, config, _storage, callback = demo_route_client
    config.save({"demo_mode": True})
    callback.reset_mock()

    response = client.post(
        "/api/config",
        json={"language": "de", "poll_interval": 120},
    )

    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert config.is_demo_mode() is True
    assert config.get("language") == "de"
    assert config.get("poll_interval") == 120
    assert "modem_type" not in config._file_config
    assert "modem_url" not in config._file_config
    callback.assert_called_once_with()


def test_demo_mode_blocks_modem_driver_tests(demo_route_client):
    client, config, _storage, _callback = demo_route_client
    config.save({"demo_mode": True})

    with patch("app.drivers.driver_registry.load_driver") as load_driver:
        response = client.post(
            "/api/test-modem",
            json={
                "modem_type": "fritzbox",
                "modem_url": "http://192.0.2.1",
            },
        )

    assert response.status_code == 409
    assert response.get_json()["success"] is False
    load_driver.assert_not_called()


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_modem_driver_failures_do_not_expose_internal_details(
    demo_route_client,
    error_type,
):
    client, _config, _storage, _callback = demo_route_client
    internal_marker = "internal-modem-test-marker"
    internal_path = "/srv/docsight/private/modem-secrets.json"

    with patch(
        "app.drivers.driver_registry.load_driver",
        side_effect=error_type(f"{internal_marker} {internal_path}"),
    ):
        response = client.post(
            "/api/test-modem",
            json={
                "modem_type": "fritzbox",
                "modem_url": "http://192.0.2.1",
            },
        )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": False,
        "error": "Modem test failed",
    }
    assert internal_marker.encode() not in response.data
    assert internal_path.encode() not in response.data


def test_fresh_setup_page_renders_value_choice_and_desktop_boundary(
    demo_route_client, monkeypatch
):
    client, _config, _storage, _callback = demo_route_client
    monkeypatch.setenv("DOCSIGHT_DESKTOP_MODE", "1")

    response = client.get("/setup")

    assert response.status_code == 200
    assert b'id="start-demo-btn"' in response.data
    assert b'id="connect-modem-btn"' in response.data
    assert b'id="restore-backup-btn"' in response.data
    assert b'class="desktop-preview-first-run"' in response.data


def test_demo_start_fails_closed_without_overwriting_real_modem_config(tmp_path):
    config = ConfigManager(str(tmp_path / "configured"))
    config.save({
        "modem_type": "fritzbox",
        "modem_url": "http://192.168.178.1",
        "modem_password": "keep-me",
    })
    before = Path(config.config_path).read_bytes()
    callback = Mock()
    init_config(config, on_config_changed=callback)
    init_storage(Mock())
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post("/api/demo/start", json={})

    assert response.status_code == 409
    assert response.get_json()["success"] is False
    assert Path(config.config_path).read_bytes() == before
    assert config.get("modem_password") == "keep-me"
    callback.assert_not_called()


def test_demo_start_requires_login_on_password_protected_instance(tmp_path):
    config = ConfigManager(str(tmp_path / "protected"))
    config.save({"admin_password": "secret", "modem_type": "fritzbox"})
    init_config(config)
    init_storage(Mock())
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post("/api/demo/start", json={})

    assert response.status_code == 401
    assert response.get_json() == {"error": "Authentication required"}


@pytest.mark.parametrize(
    ("action", "next_path"),
    [
        ("connect", "/setup?connect=1"),
        ("exit", "/setup"),
    ],
)
def test_demo_exit_purges_only_demo_data_and_returns_explicit_next_path(
    demo_route_client, action, next_path
):
    client, config, storage, callback = demo_route_client
    config.save({"demo_mode": True, "language": "de"})
    callback.reset_mock()

    response = client.post("/api/demo/migrate", json={"action": action})

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "purged": 17,
        "next_path": next_path,
    }
    storage.purge_demo_data.assert_called_once_with()
    assert config.get("language") == "de"
    assert config.is_demo_mode() is False
    assert config.is_configured() is False
    assert "modem_type" not in config._file_config
    get_runtime_controller().quiesce.assert_called_once_with(timeout=0.1)
    callback.assert_called_once_with()


def test_demo_exit_purges_only_demo_connection_monitor_targets(demo_route_client):
    client, config, storage, callback = demo_route_client
    config.save({"demo_mode": True})
    callback.reset_mock()
    cm_storage = ConnectionMonitorStorage(
        str(Path(config.data_dir) / "connection_monitor.db")
    )
    live_id = cm_storage.create_target("Live", "192.0.2.1")
    demo_id = cm_storage.create_target("Demo", "198.51.100.1", is_demo=True)

    response = client.post("/api/demo/migrate", json={"action": "exit"})

    assert response.status_code == 200
    assert response.get_json()["purged"] == storage.purge_demo_data.return_value + 1
    assert cm_storage.get_target(live_id) is not None
    assert cm_storage.get_target(demo_id) is None


def test_demo_exit_rejects_unknown_navigation_intent(demo_route_client):
    client, config, storage, callback = demo_route_client
    config.save({"demo_mode": True})
    callback.reset_mock()

    response = client.post("/api/demo/migrate", json={"action": "elsewhere"})

    assert response.status_code == 400
    storage.purge_demo_data.assert_not_called()
    assert config.is_demo_mode() is True
    callback.assert_not_called()


def test_demo_exit_retry_recovers_after_runtime_callback_failure(demo_route_client):
    client, config, storage, callback = demo_route_client
    config.save({"demo_mode": True, "language": "de"})
    callback.reset_mock()
    callback.side_effect = [RuntimeError("private runtime detail"), None, None]

    first = client.post("/api/demo/migrate", json={"action": "connect"})

    assert first.status_code == 500
    assert first.get_json() == {"success": False, "error": "Demo exit failed"}
    assert "private runtime detail" not in first.get_data(as_text=True)
    assert config.is_demo_mode() is True
    storage.purge_demo_data.assert_not_called()

    second = client.post("/api/demo/migrate", json={"action": "connect"})

    assert second.status_code == 200
    assert second.get_json() == {
        "success": True,
        "purged": 17,
        "next_path": "/setup?connect=1",
    }
    storage.purge_demo_data.assert_called_once_with()
    assert config.is_demo_mode() is False
    assert callback.call_count == 3


def test_demo_exit_runtime_without_callback_fails_before_side_effects(tmp_path):
    config = ConfigManager(str(tmp_path / "runtime-without-callback"))
    config.save({"demo_mode": True, "language": "de"})
    before_snapshot = config.snapshot()
    before_file = Path(config.config_path).read_bytes()
    storage = Mock()
    runtime = Mock(
        transaction_lock=threading.RLock(),
        stop_timeout=0.1,
    )
    init_config(config, runtime_controller=runtime)
    init_storage(storage)
    app.config["TESTING"] = True

    with app.test_client() as client:
        response = client.post(
            "/api/demo/migrate",
            json={"action": "exit"},
        )

    assert response.status_code == 500
    assert response.get_json() == {
        "success": False,
        "error": "Demo exit failed",
    }
    runtime.quiesce.assert_not_called()
    storage.purge_demo_data.assert_not_called()
    assert config.snapshot() == before_snapshot
    assert Path(config.config_path).read_bytes() == before_file
    init_config(config)


@pytest.mark.parametrize(
    ("action", "next_path"),
    [
        ("connect", "/setup?connect=1"),
        ("exit", "/setup"),
    ],
)
def test_demo_exit_quiesce_failure_rolls_back_without_purge_and_is_retryable(
    demo_route_client,
    action,
    next_path,
):
    client, config, storage, callback = demo_route_client
    config.save({"demo_mode": True, "language": "de"})
    callback.reset_mock()
    runtime = get_runtime_controller()
    runtime.quiesce.side_effect = [False, True]

    first = client.post("/api/demo/migrate", json={"action": action})

    assert first.status_code == 500
    assert first.get_json() == {
        "success": False,
        "error": "Demo exit failed",
    }
    assert config.is_demo_mode() is True
    assert config.get("language") == "de"
    storage.purge_demo_data.assert_not_called()
    callback.assert_called_once_with()

    second = client.post("/api/demo/migrate", json={"action": action})

    assert second.status_code == 200
    assert second.get_json() == {
        "success": True,
        "purged": 17,
        "next_path": next_path,
    }
    assert config.is_demo_mode() is False
    storage.purge_demo_data.assert_called_once_with()
    assert runtime.quiesce.call_count == 2
    assert callback.call_count == 2


def test_env_managed_demo_exit_is_localized_and_has_no_side_effects(
    demo_route_client, monkeypatch
):
    client, config, storage, callback = demo_route_client
    config.save({"demo_mode": True, "language": "de"})
    callback.reset_mock()
    before = Path(config.config_path).read_bytes()
    cm_storage = ConnectionMonitorStorage(
        str(Path(config.data_dir) / "connection_monitor.db")
    )
    demo_target = cm_storage.create_target(
        "Demo target", "198.51.100.2", is_demo=True
    )
    monkeypatch.setenv("DEMO_MODE", "true")

    page = client.get("/")

    assert page.status_code == 200
    assert "Bereitstellungskonfiguration".encode() in page.data
    assert b"demo-mode-banner-managed" in page.data
    assert b"data-demo-action" not in page.data

    response = client.post("/api/demo/migrate", json={"action": "exit"})

    assert response.status_code == 409
    assert response.get_json() == {
        "success": False,
        "error": "Demo Mode is managed by deployment configuration",
    }
    assert Path(config.config_path).read_bytes() == before
    assert cm_storage.get_target(demo_target) is not None
    storage.purge_demo_data.assert_not_called()
    callback.assert_not_called()


@pytest.mark.parametrize(
    ("path", "payload", "demo_mode"),
    [
        ("/api/config", {"language": "de"}, False),
        ("/api/demo/start", {}, False),
        ("/api/demo/migrate", {"action": "exit"}, True),
    ],
)
def test_browser_cross_origin_mutations_are_rejected_without_side_effects(
    demo_route_client, path, payload, demo_mode
):
    client, config, storage, callback = demo_route_client
    if demo_mode:
        config.save({"demo_mode": True})
    before = config.snapshot()
    callback.reset_mock()

    response = client.post(
        path,
        json=payload,
        headers={
            "Origin": "https://cross-origin.invalid",
            "Sec-Fetch-Site": "cross-site",
        },
    )

    assert response.status_code == 403
    assert config.snapshot() == before
    storage.purge_demo_data.assert_not_called()
    callback.assert_not_called()


@pytest.mark.parametrize(
    ("path", "payload", "demo_mode"),
    [
        ("/api/config", {"language": "de"}, False),
        ("/api/demo/start", {}, False),
        ("/api/demo/migrate", {"action": "exit"}, True),
    ],
)
@pytest.mark.parametrize(
    ("host", "origin"),
    [
        ("docsight.example.com", "https://docsight.example.com"),
        ("docsight.example.com", "https://docsight.example.com:443"),
        (
            "docsight.example.com:8765",
            "https://docsight.example.com:8765",
        ),
    ],
)
def test_https_frontend_origin_is_allowed_for_same_host_http_upstream(
    demo_route_client, path, payload, demo_mode, host, origin
):
    client, config, _storage, callback = demo_route_client
    if demo_mode:
        config.save({"demo_mode": True})
        callback.reset_mock()

    response = client.post(
        path,
        json=payload,
        headers={
            "Host": host,
            "Origin": origin,
            "Sec-Fetch-Site": "same-origin",
        },
    )

    assert response.status_code == 200
    callback.assert_called_once_with()


@pytest.mark.parametrize(
    ("path", "payload", "demo_mode"),
    [
        ("/api/config", {"language": "de"}, False),
        ("/api/demo/start", {}, False),
        ("/api/demo/migrate", {"action": "exit"}, True),
    ],
)
@pytest.mark.parametrize(
    ("host", "origin", "fetch_site"),
    [
        (
            "docsight.example.com",
            "https://other.example.com",
            "same-origin",
        ),
        (
            "docsight.example.com",
            "https://docsight.example.com:444",
            "same-origin",
        ),
        (
            "docsight.example.com:8765",
            "https://docsight.example.com",
            "same-origin",
        ),
        (
            "docsight.example.com",
            "https://docsight.example.com",
            "cross-site",
        ),
        (
            "docsight.example.com",
            "https://docsight.example.com:99999",
            "same-origin",
        ),
    ],
)
def test_browser_origin_authority_negatives_reject_all_mutation_routes(
    demo_route_client,
    path,
    payload,
    demo_mode,
    host,
    origin,
    fetch_site,
):
    client, config, storage, callback = demo_route_client
    if demo_mode:
        config.save({"demo_mode": True})
    before = config.snapshot()
    callback.reset_mock()

    response = client.post(
        path,
        json=payload,
        headers={
            "Host": host,
            "Origin": origin,
            "Sec-Fetch-Site": fetch_site,
        },
    )

    assert response.status_code == 403
    assert config.snapshot() == before
    storage.purge_demo_data.assert_not_called()
    callback.assert_not_called()


def test_same_site_browser_request_without_origin_is_rejected(demo_route_client):
    client, config, _storage, callback = demo_route_client

    response = client.post(
        "/api/config",
        json={"language": "de"},
        headers={"Sec-Fetch-Site": "same-site"},
    )

    assert response.status_code == 403
    assert config.get("language") != "de"
    callback.assert_not_called()


def test_invalid_url_validation_has_no_restore_or_runtime_side_effect(
    demo_route_client,
):
    client, config, _storage, callback = demo_route_client
    before = config.snapshot()
    original_restore = config.restore
    config.restore = Mock(wraps=original_restore)

    response = client.post(
        "/api/config",
        json={"modem_url": "ftp://bad"},
    )

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error": "Configuration URLs must use HTTP or HTTPS.",
    }
    assert config.snapshot() == before
    config.restore.assert_not_called()
    callback.assert_not_called()


def test_config_value_error_does_not_expose_sensitive_details(demo_route_client):
    client, config, _storage, callback = demo_route_client
    sensitive_error = "internal-validation-marker /internal/path"

    with patch.object(config, "save", side_effect=ValueError(sensitive_error)):
        response = client.post(
            "/api/config",
            json={"modem_url": "https://example.com"},
        )

    assert response.status_code == 400
    assert response.get_json() == {
        "success": False,
        "error": "Configuration URLs must use HTTP or HTTPS.",
    }
    response_text = response.get_data(as_text=True)
    assert "internal-validation-marker" not in response_text
    assert "/internal/path" not in response_text
    callback.assert_not_called()


@pytest.mark.parametrize("unknown_type", ["not-a-driver", None, ["fritzbox"]])
def test_unknown_modem_type_is_rejected_before_persistence_or_runtime_effect(
    demo_route_client,
    unknown_type,
):
    client, config, _storage, callback = demo_route_client
    before = config.snapshot()
    original_restore = config.restore
    config.restore = Mock(wraps=original_restore)

    response = client.post(
        "/api/config",
        json={"modem_type": unknown_type, "language": "de"},
    )

    assert response.status_code == 400
    assert response.get_json()["success"] is False
    assert "Unknown modem_type" in response.get_json()["error"]
    assert config.snapshot() == before
    assert not Path(config.config_path).exists()
    config.restore.assert_not_called()
    callback.assert_not_called()


def test_config_and_demo_mutations_share_one_reentrant_transaction(tmp_path):
    config = ConfigManager(str(tmp_path / "serialized"))
    storage = Mock()
    storage.purge_demo_data.return_value = 0
    first_callback_entered = threading.Event()
    release_first_callback = threading.Event()
    counter_lock = threading.Lock()
    active_callbacks = 0
    max_active_callbacks = 0
    callback_count = 0

    def callback():
        nonlocal active_callbacks, max_active_callbacks, callback_count
        with counter_lock:
            callback_count += 1
            current_call = callback_count
            active_callbacks += 1
            max_active_callbacks = max(max_active_callbacks, active_callbacks)
        if current_call == 1:
            first_callback_entered.set()
            assert release_first_callback.wait(timeout=5)
        with counter_lock:
            active_callbacks -= 1

    init_config(config, on_config_changed=callback)
    init_storage(storage)
    app.config["TESTING"] = True
    responses = {}

    def post_config():
        with app.test_client() as local_client:
            responses["config"] = local_client.post(
                "/api/config", json={"language": "de"}
            )

    def start_demo():
        with app.test_client() as local_client:
            responses["demo"] = local_client.post("/api/demo/start", json={})

    config_thread = threading.Thread(target=post_config)
    demo_thread = threading.Thread(target=start_demo)
    config_thread.start()
    assert first_callback_entered.wait(timeout=5)
    demo_thread.start()
    assert callback_count == 1
    release_first_callback.set()
    config_thread.join(timeout=5)
    demo_thread.join(timeout=5)

    assert not config_thread.is_alive()
    assert not demo_thread.is_alive()
    assert responses["config"].status_code == 200
    assert responses["demo"].status_code == 200
    assert max_active_callbacks == 1
    assert callback_count == 2
    assert config.get("language") == "de"
    assert config.is_demo_mode() is True


def test_parallel_config_and_demo_requests_never_orphan_polling_threads(tmp_path):
    config = ConfigManager(str(tmp_path / "runtime-serialized"))
    storage = Mock()
    storage.max_days = 7
    state_lock = threading.Lock()
    request_barrier = threading.Barrier(3)
    polling_started = threading.Event()
    active_threads = 0
    max_active_threads = 0

    def polling_target(_config, _storage, stop_event):
        nonlocal active_threads, max_active_threads
        with state_lock:
            active_threads += 1
            max_active_threads = max(max_active_threads, active_threads)
        polling_started.set()
        try:
            stop_event.wait()
        finally:
            with state_lock:
                active_threads -= 1

    runtime = RuntimeController(config, storage, polling_target)
    init_config(
        config,
        on_config_changed=runtime.apply_config_changed,
        runtime_controller=runtime,
    )
    init_storage(storage)
    app.config["TESTING"] = True
    responses = {}

    def post(name, path, payload):
        request_barrier.wait()
        with app.test_client() as local_client:
            responses[name] = local_client.post(path, json=payload)

    config_thread = threading.Thread(
        target=post,
        args=("config", "/api/config", {"language": "de"}),
    )
    demo_thread = threading.Thread(
        target=post,
        args=("demo", "/api/demo/start", {}),
    )
    config_thread.start()
    demo_thread.start()
    request_barrier.wait()
    config_thread.join(timeout=5)
    demo_thread.join(timeout=5)

    assert not config_thread.is_alive()
    assert not demo_thread.is_alive()
    assert responses["config"].status_code == 200
    assert responses["demo"].status_code == 200
    assert polling_started.wait(timeout=5)
    assert runtime.wait_for_state(True)
    assert runtime.is_running is True
    assert max_active_threads == 1

    runtime.stop_polling()
    assert runtime.wait_for_state(False)
    assert active_threads == 0
    init_config(config)


def test_slow_live_config_handoff_returns_success_and_eventually_restarts(
    tmp_path,
):
    config = ConfigManager(str(tmp_path / "slow-runtime"))
    config.save({"modem_type": "fritzbox"})
    storage = Mock()
    storage.max_days = 7
    first_started = threading.Event()
    replacement_started = threading.Event()
    allow_first_exit = threading.Event()
    state_lock = threading.Lock()
    starts = 0
    active = 0
    maximum_active = 0

    def polling_target(_config, _storage, stop_event):
        nonlocal starts, active, maximum_active
        with state_lock:
            starts += 1
            run_number = starts
            active += 1
            maximum_active = max(maximum_active, active)
        (first_started if run_number == 1 else replacement_started).set()
        try:
            stop_event.wait()
            if run_number == 1:
                allow_first_exit.wait()
        finally:
            with state_lock:
                active -= 1

    runtime = RuntimeController(
        config,
        storage,
        polling_target,
        stop_timeout=0.01,
    )
    init_config(
        config,
        on_config_changed=runtime.apply_config_changed,
        runtime_controller=runtime,
    )
    init_storage(storage)
    app.config["TESTING"] = True
    runtime.start_polling()
    assert first_started.wait(timeout=1)

    with app.test_client() as client:
        response = client.post("/api/config", json={"language": "de"})

    assert response.status_code == 200
    assert response.get_json() == {"success": True}
    assert config.get("language") == "de"
    assert starts == 1
    assert maximum_active == 1

    allow_first_exit.set()
    assert replacement_started.wait(timeout=1)
    assert runtime.is_running is True
    assert starts == 2
    assert maximum_active == 1

    runtime.shutdown()
    assert active == 0
    init_config(config)


def test_demo_exit_timeout_rolls_back_and_eventually_restarts_demo_once(
    tmp_path,
):
    config = ConfigManager(str(tmp_path / "slow-route-transitions"))
    config.save({"demo_mode": True})
    storage = Mock()
    storage.max_days = 7
    storage.purge_demo_data.return_value = 0
    first_started = threading.Event()
    replacement_started = threading.Event()
    allow_first_exit = threading.Event()
    state_lock = threading.Lock()
    starts = 0
    active = 0
    maximum_active = 0

    def polling_target(_config, _storage, stop_event):
        nonlocal starts, active, maximum_active
        with state_lock:
            starts += 1
            run_number = starts
            active += 1
            maximum_active = max(maximum_active, active)
        (first_started if run_number == 1 else replacement_started).set()
        try:
            stop_event.wait()
            if run_number == 1:
                allow_first_exit.wait()
        finally:
            with state_lock:
                active -= 1

    runtime = RuntimeController(
        config,
        storage,
        polling_target,
        stop_timeout=0.01,
    )
    init_config(
        config,
        on_config_changed=runtime.apply_config_changed,
        runtime_controller=runtime,
    )
    init_storage(storage)
    app.config["TESTING"] = True
    runtime.start_polling()
    assert first_started.wait(timeout=1)

    with app.test_client() as client:
        config_response = client.post(
            "/api/config", json={"language": "de"}
        )
        start_response = client.post("/api/demo/start", json={})
        exit_response = client.post(
            "/api/demo/migrate", json={"action": "exit"}
        )

    assert config_response.status_code == 200
    assert start_response.status_code == 200
    assert exit_response.status_code == 500
    assert exit_response.get_json() == {
        "success": False,
        "error": "Demo exit failed",
    }
    assert config.is_demo_mode() is True
    assert runtime.desired_running is True
    storage.purge_demo_data.assert_not_called()
    assert starts == 1

    allow_first_exit.set()
    assert replacement_started.wait(timeout=1)
    assert runtime.desired_running is True
    assert starts == 2
    assert maximum_active == 1
    storage.purge_demo_data.assert_not_called()

    runtime.shutdown()
    assert active == 0
    init_config(config)


@pytest.mark.parametrize(
    ("action", "next_path"),
    [
        ("connect", "/setup?connect=1"),
        ("exit", "/setup"),
    ],
)
def test_legacy_mixed_demo_state_quiesces_before_purge_then_starts_live_runtime(
    tmp_path,
    action,
    next_path,
):
    config = ConfigManager(str(tmp_path / f"legacy-mixed-{action}"))
    config.save({
        "demo_mode": True,
        "modem_type": "fritzbox",
        "modem_url": "http://192.0.2.1",
    })
    storage = Mock()
    storage.max_days = 7
    demo_started = threading.Event()
    demo_exited = threading.Event()
    demo_running = threading.Event()
    live_started = threading.Event()
    runtime_apply_finished = threading.Event()
    starts = 0

    def polling_target(_config, _storage, stop_event):
        nonlocal starts
        starts += 1
        run_number = starts
        if run_number == 1:
            demo_running.set()
            demo_started.set()
        else:
            live_started.set()
        try:
            stop_event.wait()
        finally:
            if run_number == 1:
                demo_running.clear()
                demo_exited.set()

    runtime = RuntimeController(
        config,
        storage,
        polling_target,
        stop_timeout=1,
    )

    def purge_demo_data():
        assert demo_exited.is_set()
        assert not demo_running.is_set()
        assert runtime_apply_finished.is_set()
        assert live_started.wait(timeout=1)
        assert runtime.wait_for_state(True, timeout=0)
        assert runtime.desired_running is True
        return 5

    storage.purge_demo_data.side_effect = purge_demo_data

    def apply_runtime_config():
        runtime.apply_config_changed()
        runtime_apply_finished.set()

    init_config(
        config,
        on_config_changed=apply_runtime_config,
        runtime_controller=runtime,
    )
    init_storage(storage)
    app.config["TESTING"] = True
    runtime.start_polling()
    assert demo_started.wait(timeout=1)

    with app.test_client() as client:
        response = client.post(
            "/api/demo/migrate",
            json={"action": action},
        )

    assert response.status_code == 200
    assert response.get_json() == {
        "success": True,
        "purged": 5,
        "next_path": next_path,
    }
    assert live_started.wait(timeout=1)
    assert config.is_demo_mode() is False
    assert config.is_configured() is True
    assert config.get("modem_type") == "fritzbox"
    assert runtime.desired_running is True
    assert starts == 2

    runtime.shutdown()
    init_config(config)


def test_demo_exit_waits_for_poll_exit_before_purge_and_does_not_restart(
    tmp_path,
):
    config = ConfigManager(str(tmp_path / "quiescent-demo-exit"))
    config.save({"demo_mode": True})
    storage = Mock()
    storage.max_days = 7
    poll_started = threading.Event()
    stop_observed = threading.Event()
    allow_poll_exit = threading.Event()
    poll_exited = threading.Event()
    starts = 0

    def polling_target(_config, _storage, stop_event):
        nonlocal starts
        starts += 1
        poll_started.set()
        stop_event.wait()
        stop_observed.set()
        try:
            allow_poll_exit.wait()
        finally:
            poll_exited.set()

    runtime = RuntimeController(
        config,
        storage,
        polling_target,
        stop_timeout=1,
    )

    def purge_demo_data():
        assert poll_exited.is_set()
        assert runtime.wait_for_state(False, timeout=0)
        return 3

    storage.purge_demo_data.side_effect = purge_demo_data
    init_config(
        config,
        on_config_changed=runtime.apply_config_changed,
        runtime_controller=runtime,
    )
    init_storage(storage)
    app.config["TESTING"] = True
    runtime.start_polling()
    assert poll_started.wait(timeout=1)
    responses = {}

    def exit_demo():
        with app.test_client() as client:
            responses["exit"] = client.post(
                "/api/demo/migrate",
                json={"action": "exit"},
            )

    request_thread = threading.Thread(target=exit_demo)
    request_thread.start()
    assert stop_observed.wait(timeout=1)
    storage.purge_demo_data.assert_not_called()
    assert request_thread.is_alive()

    allow_poll_exit.set()
    request_thread.join(timeout=2)

    assert not request_thread.is_alive()
    assert responses["exit"].status_code == 200
    assert responses["exit"].get_json() == {
        "success": True,
        "purged": 3,
        "next_path": "/setup",
    }
    storage.purge_demo_data.assert_called_once_with()
    assert poll_exited.is_set()
    assert runtime.wait_for_state(False, timeout=0)
    assert runtime.desired_running is False
    assert config.is_demo_mode() is False
    assert starts == 1

    runtime.shutdown()
    init_config(config)


@pytest.mark.parametrize(
    ("contender_path", "payload", "expected_demo_mode", "expected_starts"),
    [
        ("/api/demo/start", {}, True, 2),
        ("/api/config", {"language": "de"}, False, 1),
    ],
)
def test_demo_exit_transaction_blocks_mutations_through_quiescence_and_purge(
    tmp_path,
    contender_path,
    payload,
    expected_demo_mode,
    expected_starts,
):
    config = ConfigManager(str(tmp_path / "transactional-demo-exit"))
    config.save({"demo_mode": True})
    storage = Mock()
    storage.max_days = 7
    poll_started = threading.Event()
    stop_observed = threading.Event()
    allow_poll_exit = threading.Event()
    purge_started = threading.Event()
    allow_purge = threading.Event()
    purge_finished = threading.Event()
    contender_sent = threading.Event()
    starts = 0

    def polling_target(_config, _storage, stop_event):
        nonlocal starts
        starts += 1
        poll_started.set()
        stop_event.wait()
        stop_observed.set()
        if starts == 1:
            allow_poll_exit.wait()

    runtime = RuntimeController(
        config,
        storage,
        polling_target,
        stop_timeout=1,
    )

    def purge_demo_data():
        purge_started.set()
        assert allow_purge.wait(timeout=2)
        purge_finished.set()
        return 4

    storage.purge_demo_data.side_effect = purge_demo_data
    init_config(
        config,
        on_config_changed=runtime.apply_config_changed,
        runtime_controller=runtime,
    )
    init_storage(storage)
    app.config["TESTING"] = True
    runtime.start_polling()
    assert poll_started.wait(timeout=1)
    responses = {}

    def exit_demo():
        with app.test_client() as client:
            responses["exit"] = client.post(
                "/api/demo/migrate",
                json={"action": "exit"},
            )

    def mutate():
        contender_sent.set()
        with app.test_client() as client:
            responses["contender"] = client.post(
                contender_path,
                json=payload,
            )

    exit_thread = threading.Thread(target=exit_demo)
    contender_thread = threading.Thread(target=mutate)
    exit_thread.start()
    assert stop_observed.wait(timeout=1)

    contender_thread.start()
    assert contender_sent.wait(timeout=1)
    assert contender_thread.is_alive()
    assert "contender" not in responses

    allow_poll_exit.set()
    assert purge_started.wait(timeout=1)
    assert contender_thread.is_alive()
    assert "contender" not in responses

    allow_purge.set()
    exit_thread.join(timeout=2)
    contender_thread.join(timeout=2)

    assert not exit_thread.is_alive()
    assert not contender_thread.is_alive()
    assert purge_finished.is_set()
    assert responses["exit"].status_code == 200
    assert responses["contender"].status_code == 200
    assert config.is_demo_mode() is expected_demo_mode
    assert starts == expected_starts
    if contender_path == "/api/config":
        assert config.get("language") == "de"

    runtime.shutdown()
    init_config(config)
