"""API tokens are for integrations: they read, and write only where allowed.

A token must never reach backups, restore, modules, settings, connection
tests that reuse stored secrets, or anything else that makes it an admin.
"""

import re

import pytest
from flask.sessions import SecureCookieSessionInterface

from app.config import ConfigManager
from app.storage import SnapshotStorage
from app.web_auth import _AUTH_STATE_CONTEXT, _keyed_sha256_hexdigest
from tests.test_auth import _login

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}
_OLD_KEY = bytes(range(32))

# Every write a token may make. Adding one is a deliberate decision: no
# deletes, bulk imports, secrets, code, files or token management.
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


def _config(tmp_path):
    config = ConfigManager(str(tmp_path / "data"))
    config.save({"modem_type": "fritzbox", "admin_password": "secret123"})
    return config


@pytest.fixture
def secured(make_app, builtin_module_loader_factory, tmp_path):
    config = _config(tmp_path)
    storage = SnapshotStorage(str(tmp_path / "data" / "docsis_history.db"), max_days=7)
    app = make_app(
        config_manager=config, storage=storage, environ={},
        module_loader_factory=builtin_module_loader_factory(config),
    )
    _, token = storage.create_api_token("integration")
    return app, {"Authorization": f"Bearer {token}"}


def _api_writes(app):
    for rule in app.url_map.iter_rules():
        if rule.rule.startswith("/api/"):
            for method in rule.methods - _SAFE_METHODS:
                yield method, rule, getattr(app.view_functions[rule.endpoint], "docsight_token_access", None)


def test_token_writes_are_exactly_the_reviewed_list(secured):
    app, _ = secured
    writes = {(method, rule.rule): policy for method, rule, policy in _api_writes(app)}
    assert None not in writes.values()
    assert {key for key, policy in writes.items() if policy == "write"} == EXPECTED_TOKEN_WRITES


def test_token_is_refused_on_every_other_write(secured):
    app, bearer = secured
    client = app.test_client()
    allowed = []
    for method, rule, _ in _api_writes(app):
        if (method, rule.rule) not in EXPECTED_TOKEN_WRITES:
            path = re.sub(r"<[^>]+>", "1", rule.rule)
            if client.open(path, method=method, headers=bearer).status_code != 403:
                allowed.append((method, rule.rule))
    assert allowed == []


@pytest.mark.parametrize(("path", "status"), [
    ("/api/snapshots", 200),
    ("/api/backup/list", 403),
    ("/api/browse", 403),
    ("/api/tokens", 403),
    ("/api/de-tkg/context", 403),
    ("/api/de-tkg/claims/1/letter", 403),
    ("/", 302),
    ("/settings", 302),
])
def test_token_reads(secured, path, status):
    app, bearer = secured
    assert app.test_client().get(path, headers=bearer).status_code == status


def test_token_can_write_where_allowed(secured):
    app, bearer = secured
    assert app.test_client().post("/api/events/acknowledge-all", headers=bearer).status_code == 200


def test_session_wins_over_a_token(secured):
    app, bearer = secured
    client = app.test_client()
    _login(client)
    assert client.get("/api/tokens", headers=bearer).status_code == 200


@pytest.mark.parametrize("auth_state", ["v1", None, "not-a-fingerprint"])
def test_upgrade_rotates_a_session_key_that_older_backups_may_contain(make_app, tmp_path, auth_state):
    config = _config(tmp_path)
    password = config.get("admin_password").encode()
    (tmp_path / "data" / ".session_key").write_bytes(_OLD_KEY)
    if auth_state == "v1":
        assert not _AUTH_STATE_CONTEXT.startswith(b"docsight-admin-auth-state-v1")
        auth_state = _keyed_sha256_hexdigest(_OLD_KEY, b"docsight-admin-auth-state-v1\0" + password)
    if auth_state is not None:
        (tmp_path / "data" / ".auth_state").write_text(auth_state)

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
