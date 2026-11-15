"""Without an admin password, DOCSight stays locked until the setup code from the log proves access."""

import logging
import re

import pytest

from app.doctor import _check_admin_password
from app.runtime import get_runtime


def _csrf(client):
    response = client.get("/password-setup")
    match = re.search(rb'name="csrf_token" value="([^"]+)"', response.data)
    assert match, response.data[:200]
    return match.group(1).decode()


def _code(app):
    return get_runtime(app).password_setup_code


NEW_ADMIN_CREDENTIAL = "correct horse"


def _submit(client, code, password=NEW_ADMIN_CREDENTIAL, confirm=None, csrf=None):
    return client.post("/password-setup", data={
        "csrf_token": _csrf(client) if csrf is None else csrf,
        "setup_code": code,
        "password": password,
        "password_confirm": password if confirm is None else confirm,
    })


@pytest.fixture
def locked_app(make_app, make_config, builtin_module_loader_factory):
    config = make_config()
    return make_app(config_manager=config, module_loader_factory=builtin_module_loader_factory(config), environ={})


def test_without_a_password_every_page_and_api_waits_for_the_password(locked_app):
    client = locked_app.test_client()

    for path in ("/", "/settings", "/setup", "/login"):
        response = client.get(path)
        assert response.status_code == 302, path
        assert response.headers["Location"].endswith("/password-setup"), path

    api = client.post("/api/config", json={"admin_password": "taken over"})
    assert api.status_code == 401
    assert api.get_json() == {"error": "Admin password not set", "setup_required": True}
    assert client.get("/api/backup/list").status_code == 401
    assert get_runtime(locked_app).config_manager.get("admin_password") == ""


def test_the_setup_code_is_logged_at_startup(make_app, caplog):
    with caplog.at_level(logging.WARNING, logger="docsis.web"):
        app = make_app(environ={})

    code = _code(app)
    assert re.fullmatch(r"[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}-[A-HJ-NP-Z2-9]{4}", code)
    assert any(code in record.getMessage() for record in caplog.records)


def test_a_wrong_code_neither_sets_a_password_nor_unlocks(locked_app):
    client = locked_app.test_client()

    response = _submit(client, "AAAA-BBBB-CCCC")

    assert response.status_code == 200
    assert b"setup code does not match" in response.data
    assert get_runtime(locked_app).config_manager.get("admin_password") == ""
    assert client.get("/").headers["Location"].endswith("/password-setup")


def test_wrong_codes_are_rate_limited(locked_app):
    client = locked_app.test_client()
    for _ in range(5):
        _submit(client, "AAAA-BBBB-CCCC")

    response = _submit(client, _code(locked_app))

    assert b"Too many attempts" in response.data
    assert get_runtime(locked_app).config_manager.get("admin_password") == ""


@pytest.mark.parametrize(("password", "confirm", "message"), [
    ("short", "short", b"at least 8 characters"),
    ("correct horse", "correct hose", b"do not match"),
])
def test_the_new_password_must_be_long_enough_and_confirmed(locked_app, password, confirm, message):
    client = locked_app.test_client()

    response = _submit(client, _code(locked_app), password=password, confirm=confirm)

    assert message in response.data
    assert get_runtime(locked_app).config_manager.get("admin_password") == ""


def test_a_missing_csrf_token_is_rejected(locked_app):
    client = locked_app.test_client()
    client.get("/password-setup")

    response = _submit(client, _code(locked_app), csrf="")

    assert response.status_code == 400
    assert get_runtime(locked_app).config_manager.get("admin_password") == ""


def test_the_right_code_sets_a_hashed_password_and_signs_in(locked_app):
    client = locked_app.test_client()
    code = _code(locked_app).lower().replace("-", " ")

    response = _submit(client, code)

    assert response.status_code == 302
    stored = get_runtime(locked_app).config_manager.get("admin_password")
    assert stored.startswith(("scrypt:", "pbkdf2:"))
    assert _code(locked_app) == ""
    # Signed in: the unconfigured instance continues with the first-run setup.
    assert client.get("/").headers["Location"].endswith("/setup")
    assert client.get("/setup").status_code == 200
    assert client.get("/password-setup").headers["Location"].endswith("/")
    # Anyone else now meets the normal login.
    assert locked_app.test_client().get("/").headers["Location"].endswith("/login")


@pytest.mark.parametrize("environ", [{"AUTH_DISABLED": "true"}, {"DOCSIGHT_DESKTOP_MODE": "1"}])
def test_an_explicit_opt_out_and_the_desktop_app_stay_open(make_app, environ):
    app = make_app(environ=environ)
    client = app.test_client()

    assert client.get("/").headers["Location"].endswith("/setup")
    assert client.get("/password-setup").headers["Location"].endswith("/")
    assert _code(app) == ""


def test_demo_mode_stays_open(make_app, make_config):
    app = make_app(config_manager=make_config({"demo_mode": True}), environ={})

    assert app.test_client().get("/").status_code == 200
    assert _code(app) == ""


def test_only_a_deliberate_opt_out_shows_the_open_instance_warning(make_app):
    warning = 'class="notice-line notice-warning" role="status"'
    open_settings = make_app(environ={"AUTH_DISABLED": "true"}).test_client().get("/settings").get_data(as_text=True)
    desktop_settings = make_app(environ={"DOCSIGHT_DESKTOP_MODE": "1"}).test_client().get("/settings").get_data(as_text=True)

    assert warning in open_settings
    assert warning not in desktop_settings


@pytest.mark.parametrize(("raw_config", "environ", "status"), [
    ({"admin_password": "scrypt:hash"}, {}, "pass"),
    ({}, {"ADMIN_PASSWORD": "secret123"}, "pass"),
    ({"demo_mode": True}, {}, "skipped"),
    ({}, {"DOCSIGHT_DESKTOP_MODE": "1"}, "pass"),
    ({}, {"AUTH_DISABLED": "true"}, "warn"),
    ({}, {}, "warn"),
])
def test_doctor_reports_the_admin_password_state(raw_config, environ, status):
    result = _check_admin_password(raw_config, environ)

    assert result.id == "auth.admin_password"
    assert result.status == status


def _login(client, credential):
    page = client.get("/login")
    csrf = re.search(rb'name="csrf_token" value="([^"]+)"', page.data).group(1).decode()
    return client.post("/login", data={"password": credential, "csrf_token": csrf})


def test_a_password_that_looks_like_a_hash_still_signs_in(locked_app):
    credential = "scrypt:not-a-hash"
    _submit(locked_app.test_client(), _code(locked_app), password=credential)

    response = _login(locked_app.test_client(), credential)

    assert response.status_code == 302
    assert response.headers["Location"].endswith("/")


def test_settings_hash_a_password_that_looks_like_a_hash(locked_app):
    client = locked_app.test_client()
    _submit(client, _code(locked_app))
    credential = "pbkdf2:also-not-a-hash"

    assert client.post("/api/config", json={"admin_password": credential}).get_json()["success"] is True

    assert _login(locked_app.test_client(), credential).headers["Location"].endswith("/")


def test_removing_the_password_later_locks_again_with_a_fresh_code(locked_app, caplog):
    client = locked_app.test_client()
    _submit(client, _code(locked_app))
    get_runtime(locked_app).config_manager.save({"admin_password": ""})

    with caplog.at_level(logging.WARNING, logger="docsis.web"):
        page = locked_app.test_client().get("/password-setup")

    assert page.status_code == 200
    code = _code(locked_app)
    assert code and any(code in record.getMessage() for record in caplog.records)
