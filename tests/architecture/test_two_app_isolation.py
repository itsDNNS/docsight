from concurrent.futures import ThreadPoolExecutor
import re

import pytest

from app.app_factory import create_app
from app.config import ConfigManager
from app.runtime import get_runtime
from app.storage import SnapshotStorage


class EmptyLoader:
    def get_enabled_modules(self):
        return []

    def get_theme_modules(self):
        return []


def _login(client, password):
    response = client.get("/login")
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert match
    return client.post(
        "/login",
        data={"password": password, "csrf_token": match.group(1).decode()},
        follow_redirects=False,
    )


@pytest.mark.parametrize("order", [("a", "b"), ("b", "a")])
def test_two_apps_isolate_runtime_auth_storage_and_requests(tmp_path, order):
    applications = {}
    managers = {}
    for name in order:
        manager = ConfigManager(str(tmp_path / name))
        manager.save({
            "admin_password": f"secret-{name}",
            "metrics_require_token": name == "a",
            "update_check_enabled": name == "b",
        })
        storage = SnapshotStorage(str(tmp_path / f"{name}.db"), max_days=7)
        managers[name] = manager
        applications[name] = create_app(
            config_manager=manager,
            storage=storage,
            module_loader_factory=lambda app: EmptyLoader(),
            environ={},
            testing=True,
        )

    app_a, app_b = applications["a"], applications["b"]
    runtime_a, runtime_b = get_runtime(app_a), get_runtime(app_b)
    assert runtime_a is not runtime_b
    assert runtime_a.state is not runtime_b.state
    assert runtime_a.login_rate_limiter is not runtime_b.login_rate_limiter
    assert runtime_a.update_checker is not runtime_b.update_checker
    assert runtime_a.auth_state is not runtime_b.auth_state
    assert runtime_a.derived_storage is not runtime_b.derived_storage
    assert runtime_a.module_loader is not runtime_b.module_loader
    assert runtime_a.config_manager.data_dir != runtime_b.config_manager.data_dir
    assert runtime_a.storage.db_path != runtime_b.storage.db_path
    assert app_a.secret_key != app_b.secret_key
    assert app_a.jinja_loader is not app_b.jinja_loader

    client_a = app_a.test_client()
    client_b = app_b.test_client()
    assert _login(client_a, "secret-a").status_code == 302
    assert _login(client_b, "secret-b").status_code == 302

    cookie_a = client_a.get_cookie("session")
    cookie_b = client_b.get_cookie("session")
    replay_b = app_b.test_client()
    replay_b.set_cookie("session", cookie_a.value)
    assert replay_b.get("/api/connection").status_code == 401
    replay_a = app_a.test_client()
    replay_a.set_cookie("session", cookie_b.value)
    assert replay_a.get("/api/connection").status_code == 401

    _, token_a = runtime_a.storage.create_api_token("app-a")
    _, token_b = runtime_b.storage.create_api_token("app-b")
    bearer_a = {"Authorization": f"Bearer {token_a}"}
    bearer_b = {"Authorization": f"Bearer {token_b}"}
    assert app_a.test_client().get("/api/connection", headers=bearer_a).status_code == 200
    assert app_b.test_client().get("/api/connection", headers=bearer_a).status_code == 401
    assert app_b.test_client().get("/api/connection", headers=bearer_b).status_code == 200
    assert app_a.test_client().get("/api/connection", headers=bearer_b).status_code == 401
    assert app_a.test_client().get("/metrics").status_code == 401
    assert app_a.test_client().get("/metrics", headers=bearer_a).status_code == 200
    assert app_b.test_client().get("/metrics").status_code == 200

    runtime_a.update_state(analysis={"summary": {"health": "poor"}})
    assert client_a.get("/health").json["docsis_health"] == "poor"
    assert client_b.get("/health").json["docsis_health"] == "waiting"
    for application in (app_a, app_b):
        headers = application.test_client().get("/health").headers
        assert "Content-Security-Policy" in headers

    from app.modules.bnetz.routes import _get_bnetz_storage
    from app.modules.bqm.routes import _get_bqm_storage
    from app.modules.speedtest.routes import _get_speedtest_storage

    for application, runtime in ((app_a, runtime_a), (app_b, runtime_b)):
        with application.app_context():
            derived = (
                _get_bnetz_storage(),
                _get_bqm_storage(),
                _get_speedtest_storage(),
            )
        assert all(item.db_path == runtime.storage.db_path for item in derived)

    key_b = app_b.secret_key
    auth_state_b = (tmp_path / "b" / ".auth_state").read_bytes()
    key_a = app_a.secret_key
    managers["a"].save({"admin_password": "replacement-a"})
    assert client_a.get("/api/connection").status_code == 401
    assert app_a.secret_key != key_a
    assert app_b.secret_key == key_b
    assert (tmp_path / "b" / ".auth_state").read_bytes() == auth_state_b
    assert client_b.get("/api/connection").status_code == 200

    for _ in range(6):
        runtime_a.login_rate_limiter.record_failure("127.0.0.1")
    assert runtime_a.login_rate_limiter.retry_after("127.0.0.1") > 0
    assert runtime_b.login_rate_limiter.retry_after("127.0.0.1") == 0

    def drive(name):
        runtime = get_runtime(applications[name])
        for value in range(25):
            runtime.update_state(device_info={"app": name, "value": value})
            assert applications[name].test_client().get("/health").status_code == 200

    with ThreadPoolExecutor(max_workers=2) as executor:
        list(executor.map(drive, ("a", "b")))
    assert runtime_a.get_state()["device_info"] == {"app": "a", "value": 24}
    assert runtime_b.get_state()["device_info"] == {"app": "b", "value": 24}
