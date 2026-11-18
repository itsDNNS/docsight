"""API tokens read; only routes that opt in accept writes from a token.

A token is handed to integrations such as Home Assistant or a monitoring
script. It must never reach backups, restore, module installation, connection
tests that reuse stored secrets, or anything else that turns a token into an
administrator.
"""

import io
import tarfile

import pytest

from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.web_auth import _AUTH_STATE_CONTEXT, _keyed_sha256_hexdigest

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Every route and method that accepts a write from an API token. Adding one
# here is a deliberate decision: integrations may record and acknowledge, but
# never delete, bulk-import, reach secrets, code, the filesystem or the token
# boundary itself.
EXPECTED_TOKEN_WRITES = {
    ("POST", "/api/poll"),
    ("POST", "/api/events/<int:event_id>/acknowledge"),
    ("POST", "/api/events/acknowledge"),
    ("POST", "/api/events/unacknowledge"),
    ("POST", "/api/events/acknowledge-all"),
    ("POST", "/api/journal"),
    ("PUT", "/api/journal/<int:entry_id>"),
    ("POST", "/api/journal/unassign"),
    ("POST", "/api/incidents"),
    ("PUT", "/api/incidents/<int:incident_id>"),
    ("POST", "/api/incidents/<int:incident_id>/extend"),
    ("POST", "/api/incidents/<int:incident_id>/assign"),
    ("POST", "/api/speedtest/run"),
    ("POST", "/api/connection-monitor/pinned-days"),
    ("POST", "/api/bqm/fetch-now"),
}

PRIVILEGED_REQUESTS = [
    ("POST", "/api/backup", {}),
    ("POST", "/api/backup/scheduled", {}),
    ("DELETE", "/api/backup/docsight_backup_2026-01-01_000000.tar.gz", {}),
    ("GET", "/api/backup/list", {}),
    ("GET", "/api/browse", {}),
    ("POST", "/api/restore/validate", {}),
    ("POST", "/api/restore", {}),
    ("POST", "/api/modules/install", {"json": {"id": "evil", "download_url": "https://github.com/x/y/tree/main/evil"}}),
    ("POST", "/api/modules/uninstall", {"json": {"id": "evil"}}),
    ("POST", "/api/modules/docsight.journal/disable", {}),
    ("POST", "/api/modules/docsight.journal/enable", {}),
    ("POST", "/api/modules/batch", {"json": {}}),
    ("POST", "/api/themes/install", {"json": {}}),
    ("POST", "/api/test-modem", {"json": {}}),
    ("POST", "/api/test-fritz", {"json": {}}),
    ("POST", "/api/test-mqtt", {"json": {"mqtt_host": "attacker.invalid", "mqtt_user": "u", "mqtt_password": "••••••••"}}),
    ("POST", "/api/test-speedtest", {"json": {}}),
    ("POST", "/api/setup/detect-modem", {}),
    ("POST", "/api/notifications/test", {}),
    ("POST", "/api/demo/migrate", {}),
    ("POST", "/api/connection-monitor/targets", {"json": {"host": "10.0.0.1", "label": "x"}}),
    ("POST", "/api/connection-monitor/traceroute/1", {}),
    ("POST", "/api/bqm/validate-monitor", {"json": {"url": "https://example.invalid"}}),
    ("GET", "/api/tokens", {}),
    ("GET", "/api/de-tkg/context", {}),
    ("GET", "/api/de-tkg/claims/1/letter", {}),
    ("POST", "/api/de-tkg/claims", {"json": {}}),
    ("DELETE", "/api/journal/batch", {"json": {"all": True}}),
    ("DELETE", "/api/journal/1", {}),
    ("POST", "/api/journal/1/attachments", {}),
    ("POST", "/api/journal/import/preview", {}),
    ("POST", "/api/bnetz/upload", {}),
    ("DELETE", "/api/bqm/images", {}),
    ("DELETE", "/api/speedtest/cache", {}),
]


@pytest.fixture
def secured(make_app, builtin_module_loader_factory, tmp_path):
    data_dir = tmp_path / "data"
    config = ConfigManager(str(data_dir))
    config.save({
        "modem_type": "fritzbox",
        "modem_password": "modem-secret",
        "admin_password": "secret123",
        "mqtt_user": "u",
        "mqtt_password": "mqtt-secret",
    })
    storage = SnapshotStorage(str(data_dir / "docsis_history.db"), max_days=7)
    app = make_app(
        config_manager=config,
        storage=storage,
        module_loader_factory=builtin_module_loader_factory(config),
        environ={},
    )
    _, token = storage.create_api_token("integration")
    return app, config, token


def _bearer(token):
    return {"Authorization": f"Bearer {token}"}


def _login(client):
    import re

    page = client.get("/login")
    csrf = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
    response = client.post("/login", data={"password": "secret123", "csrf_token": csrf})
    assert response.status_code == 302


def test_token_can_still_read(secured):
    app, _, token = secured
    response = app.test_client().get("/api/snapshots", headers=_bearer(token))
    assert response.status_code == 200


def test_token_can_use_routes_that_allow_token_writes(secured):
    app, _, token = secured
    response = app.test_client().post("/api/events/acknowledge-all", headers=_bearer(token))
    assert response.status_code == 200


@pytest.mark.parametrize(("method", "path", "kwargs"), PRIVILEGED_REQUESTS)
def test_token_is_refused_on_privileged_routes(secured, method, path, kwargs):
    app, _, token = secured
    response = app.test_client().open(path, method=method, headers=_bearer(token), **kwargs)
    assert response.status_code == 403
    assert response.get_json() == {"error": "Session authentication required"}


def test_token_cannot_restore_a_backup_with_its_own_admin_password(secured):
    app, config, token = secured
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w:gz") as tar:
        for name, payload in (
            ("backup_meta.json", b'{"magic": "docsight-backup", "format_version": 1}'),
            ("config.json", b'{"modem_type": "fritzbox", "admin_password": "attacker"}'),
        ):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    archive.seek(0)

    response = app.test_client().post(
        "/api/restore",
        headers=_bearer(token),
        data={"file": (archive, "backup.tar.gz")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 403
    assert config.get("admin_password") != "attacker"


def test_token_cannot_send_stored_mqtt_password_to_another_host(secured, monkeypatch):
    import paho.mqtt.client as mqtt

    app, _, token = secured
    connects = []
    monkeypatch.setattr(mqtt.Client, "connect", lambda self, *args, **kwargs: connects.append(args))

    response = app.test_client().post(
        "/api/test-mqtt",
        headers=_bearer(token),
        json={"mqtt_host": "attacker.invalid", "mqtt_user": "u", "mqtt_password": "••••••••"},
    )

    assert response.status_code == 403
    assert connects == []


def test_token_cannot_install_a_module(secured, monkeypatch):
    from app.blueprints import modules_bp

    app, _, token = secured
    downloads = []
    monkeypatch.setattr(modules_bp, "download_github_directory", lambda *args: downloads.append(args) or False)

    response = app.test_client().post(
        "/api/modules/install",
        headers=_bearer(token),
        json={"id": "evil", "download_url": "https://github.com/x/y/tree/main/evil"},
    )

    assert response.status_code == 403
    assert downloads == []


def test_session_backup_leaves_out_cookie_signing_state(secured):
    app, _, _ = secured
    client = app.test_client()
    _login(client)

    response = client.post("/api/backup")

    assert response.status_code == 200
    with tarfile.open(fileobj=io.BytesIO(response.data), mode="r:gz") as tar:
        names = set(tar.getnames())
    assert {"config.json", ".config_key", "docsis_history.db"} <= names
    assert ".session_key" not in names
    assert ".auth_state" not in names


def test_token_writes_are_exactly_the_reviewed_list(secured):
    app, _, _ = secured
    token_writes = set()
    unprotected = set()
    for rule in app.url_map.iter_rules():
        if not rule.rule.startswith("/api/"):
            continue
        policy = getattr(app.view_functions[rule.endpoint], "docsight_token_access", None)
        writes = {(method, rule.rule) for method in rule.methods - _SAFE_METHODS}
        if policy is None:
            unprotected |= writes
        elif policy == "write":
            token_writes |= writes

    assert token_writes == EXPECTED_TOKEN_WRITES
    # Undecorated API routes do their own checks; none of them may write.
    assert unprotected == set()


@pytest.mark.parametrize("path", ["/", "/settings"])
def test_token_does_not_open_pages(secured, path):
    app, _, token = secured
    response = app.test_client().get(path, headers=_bearer(token))
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_session_wins_over_a_token_on_session_only_routes(secured):
    app, _, token = secured
    client = app.test_client()
    _login(client)
    assert client.get("/api/tokens", headers=_bearer(token)).status_code == 200


_OLD_KEY = bytes(range(32))


@pytest.mark.parametrize("auth_state", ["v1", None, "not-a-fingerprint"])
def test_upgrade_rotates_a_session_key_that_older_backups_may_contain(make_app, tmp_path, auth_state):
    from flask.sessions import SecureCookieSessionInterface

    data_dir = tmp_path / "data"
    config = ConfigManager(str(data_dir))
    config.save({"modem_type": "fritzbox", "admin_password": "secret123"})
    password = config.get("admin_password").encode()
    (data_dir / ".session_key").write_bytes(_OLD_KEY)
    if auth_state == "v1":
        assert not _AUTH_STATE_CONTEXT.startswith(b"docsight-admin-auth-state-v1")
        auth_state = _keyed_sha256_hexdigest(_OLD_KEY, b"docsight-admin-auth-state-v1\0" + password)
    if auth_state is not None:
        (data_dir / ".auth_state").write_text(auth_state)

    app = make_app(config_manager=config, environ={})
    restarted = make_app(config_manager=config, environ={})

    assert app.secret_key != _OLD_KEY
    assert restarted.secret_key == app.secret_key
    forger = type(app)("forger")
    forger.secret_key = _OLD_KEY
    forged = SecureCookieSessionInterface().get_signing_serializer(forger).dumps({
        "authenticated": True,
        "auth_marker": _keyed_sha256_hexdigest(_OLD_KEY, b"docsight-admin-session-v1\0" + password),
    })
    client = restarted.test_client()
    client.set_cookie("session", forged)
    assert client.get("/api/tokens").status_code == 401
