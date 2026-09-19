"""Synthetic sessions only: never contact a modem or use reporter auth data."""

import json
import traceback
from unittest.mock import Mock

import pytest
import requests

from app.drivers import driver_registry, load_driver
from app.drivers.pyur_fast3896 import PyurFast3896Driver
from app.drivers.pyur_auth import sha512_crypt
from tests.drivers.test_pyur_format import FIXTURE


# Passlib 1.7.4's explicitly selected builtin SHA512-crypt backend, 5000 rounds.
# Generated independently before implementation; no runtime test dependency.
AUTH_KEY = "10aa7ab2b640afc3df5e2037a9fa97199df6458e7bac8e2b415a2902a469946b6615162d48d112a979f8922bd92181dbcafa82d07ef6d51241e1acee18484161"
VECTORS = [
    ("synthetic-password", "salt1234", "7uUGXeaZ35f/OYwRDqnrmiJTwqtttglHa2/vVV8vemP28v2zZ9jWldy1A6BO9qOsAiBmYuLTt3Y2YFC6pVv57."),
    ("", "salt1234", "ylKI6MsIAu0NNg3Yw839dUbJ7jKOkUR3atroPBf3Mp9EFKS2Cd6MbDbACc0ColeYrZbNmfJs8xtsKVQ0u2mnw."),
    ("pässwörd", "./Ab0123", "91E4XHBY.CGj7dfjkyZbGLyq7hzyRfh.G8gOMEx.dbZFp7XHuWwUdKjTcem08s78XxggANhDsVScC2RyaFBFT0"),
    ("a" * 80, "salt1234", "sVQf9BkNRs3iCl2PVubL4MFlbMZ3NJMeqE8C66epqCfPxFej17B95qGWsRfYkE8UhDPKFYaxdd7AukFdxUKOa1"),
    # Published default-round vector: https://www.akkadia.org/drepper/SHA-crypt.txt
    ("Hello world!", "saltstring", "svn8UoSVapNtMuq1ukKS4tPQd8iKwSMHWjl/O817G3uBnIFNjnQJuesI68u4OTLiBFdcbYEdFCoEOfaS35inz1"),
    # OpenSSL 3.6.4: passwd -6 -salt './Ab0123456789z' -stdin (5000 rounds).
    ("synthetic-password", "./Ab0123456789z", "Ku3usnuDiQTyqMADFk3Ogk1qbj6i.59HSazRAX49x0zFQ9G7vjWSiOPnUfLqehbSm5tH1e2VO8XFR8VwAU2ux0"),
]


class Response:
    def __init__(self, status=200, payload=None, *, body=None, cookies=None, headers=None):
        self.status_code = status
        self.body = json.dumps(payload).encode() if body is None else body
        self.cookies = cookies or {}
        self.headers = headers or {}
        self.closed = False

    def iter_content(self, chunk_size):
        for start in range(0, len(self.body), chunk_size):
            yield self.body[start:start + chunk_size]

    def close(self):
        self.closed = True


class Session:
    def __init__(self, steps):
        self.steps = list(steps)
        self.calls = []
        self.cookies = requests.cookies.RequestsCookieJar()
        self.cookie_snapshots = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        self.cookie_snapshots.append(self.cookies.get_dict(domain="modem.invalid"))
        expected_method, path, response = self.steps.pop(0)
        assert (method, url) == (expected_method, "http://modem.invalid/api/v1/" + path)
        assert kwargs["allow_redirects"] is False
        assert kwargs["stream"] is True
        assert kwargs["timeout"] == (5, 15)
        if isinstance(response, Exception):
            raise response
        for name, value in response.cookies.items():
            self.cookies.set(name, value, domain="modem.invalid", path="/")
        return response


def login_steps(*, verify=None, csrf=True, salt="salt1234"):
    return [
        ("POST", "login-params", Response(201, body=b"", cookies={"salt": salt, "nonce": "1234567890", "BBOX_ID": "synthetic-session-1", **({"Host-csrf_token": "csrf-params"} if csrf else {})})),
        ("POST", "login", Response(201, body=b"", cookies={"BBOX_ID": "synthetic-session-2", **({"Host-csrf_token": "csrf-login"} if csrf else {})})),
        ("GET", "authenticated", verify or Response(payload=[{"authenticated": "true"}])),
    ]


@pytest.fixture
def make_driver(monkeypatch):
    def make(steps):
        session = Session(steps)
        constructor = Mock(return_value=session)
        monkeypatch.setattr("app.drivers.pyur_fast3896.requests.Session", constructor)
        monkeypatch.setattr("app.drivers.pyur_fast3896.secrets.randbelow", lambda limit: 42)
        driver = PyurFast3896Driver("http://modem.invalid/", "", "synthetic-password")
        constructor.assert_called_once_with()
        return driver, session
    return make


@pytest.mark.parametrize("password,salt,digest", VECTORS)
def test_sha512_crypt_independent_vectors(password, salt, digest):
    assert sha512_crypt(password, salt) == f"$6${salt}${digest}"


@pytest.mark.parametrize("salt", ["", "a" * 17, "$6$salt1234", "rounds=999999999$salt1234", "bad salt", "a\nb", None])
def test_salt_cannot_select_rounds_or_unbounded_work(salt):
    with pytest.raises(ValueError, match="PYUR"):
        sha512_crypt("synthetic-password", salt)


# Synthetic payloads generated with OpenSSL 3.6.4 passwd -6 and dgst -sha512;
# the oracle is development-only, never called by these tests or the driver.
@pytest.mark.parametrize("salt,auth_key", [
    (".", "49765c4c8b7e06b9703a2da8dd3e0491c7c65d5c197271461e100e022471ea7075625d8eac2fe34e3f2fe8e4d0bbfc6044036b7befdd9b0a05268f9186a636b8"),
    ("salt1234", AUTH_KEY),
    ("./Ab0123456789z", "42f2498ac53f4673200cc497fb8550a24ce5184fa6700231dd9986651ca64718ac8081d1bd74c03443444ac026f86d62577160def4869fc7dd9ac75e5f08d8cd"),
    ("./Ab0123456789zZ", "c6105a74afd8045cb97c0e2167cd46dff17750c3f6e25d0951a302e41cb5ee2b562cdaa2dc66c20e4b13e29c161780e0fe314e356b5e1b7d26781b8ceb650e12"),
], ids=["salt-1", "salt-8", "salt-15", "salt-16"])
def test_login_form_hash_empty_201_cookie_rotation_and_reuse(make_driver, salt, auth_key):
    steps = login_steps(salt=salt) + [
        ("GET", "docsis-info/connection", Response(payload=json.loads(FIXTURE.read_text()), cookies={"Host-csrf_token": "csrf-poll"})),
        ("GET", "device", Response(payload=[{"device": {}}])),
    ]
    driver, session = make_driver(steps)
    driver.login()
    driver.login()  # Collector calls login every poll; reuse the session.
    driver.get_docsis_data()
    driver.get_device_info()
    assert session.calls[0][2]["data"] == {"login": "admin"}
    assert session.calls[1][2]["data"] == {"login": "admin", "auth_key": auth_key, "cnonce": "0000000000000000042"}
    assert [call[2]["headers"].get("X-Csrf-Token") for call in session.calls] == [None, "csrf-params", "csrf-login", "csrf-login", "csrf-poll"]
    assert session.cookies.get("BBOX_ID") == "synthetic-session-2"
    assert session.cookie_snapshots[1]["BBOX_ID"] == "synthetic-session-1"
    assert session.cookie_snapshots[2]["BBOX_ID"] == "synthetic-session-2"
    assert session.trust_env is False
    assert all(step[2].closed for step in steps)
    assert not session.steps


@pytest.mark.parametrize("verify", [Response(401, body=b"private-marker"), Response(payload=[{"authenticated": "false"}]), Response(payload=[]), Response(payload={"authenticated": "true"})])
def test_login_requires_authenticated_verification(make_driver, verify):
    driver, session = make_driver(login_steps(verify=verify))
    with pytest.raises(RuntimeError, match="PYUR"):
        driver.login()
    assert len(session.calls) == 3
    assert not driver._authenticated


def test_initial_unauthenticated_probe_cannot_recurse(make_driver):
    # Before login /authenticated may return 401; verification happens after login.
    driver, session = make_driver(login_steps(verify=Response(401)))
    with pytest.raises(RuntimeError, match="PYUR"):
        driver.get_docsis_data()
    assert len(session.calls) == 3


@pytest.mark.parametrize("last_status", [200, 401])
def test_expired_session_reauthenticates_and_retries_at_most_once(make_driver, last_status):
    driver, session = make_driver(login_steps() + [
        ("GET", "docsis-info/connection", Response(401)),
    ] + login_steps() + [
        ("GET", "docsis-info/connection", Response(last_status, json.loads(FIXTURE.read_text()))),
    ])
    if last_status == 200:
        assert len(driver.get_docsis_data()["channelDs"]["docsis30"]) == 20
    else:
        with pytest.raises(RuntimeError, match="PYUR"):
            driver.get_docsis_data()
    assert len(session.calls) == 8
    assert not session.steps


@pytest.mark.parametrize("response", [Response(500, body=b"private-marker"), Response(body=b"private-marker"), Response(payload=[{}]), requests.ConnectionError("private-marker synthetic-password " + AUTH_KEY)])
def test_failures_never_relogin_or_expose_secrets(make_driver, response, caplog, capsys):
    driver, session = make_driver(login_steps() + [("GET", "docsis-info/connection", response)])
    with pytest.raises(RuntimeError) as caught:
        driver.get_docsis_data()
    output = "".join(traceback.format_exception(caught.value)) + caplog.text + repr(capsys.readouterr())
    for secret in ("private-marker", "synthetic-password", AUTH_KEY, "synthetic-session-1", "csrf-login"):
        assert secret not in output
    assert len(session.calls) == 4


@pytest.mark.parametrize("path,method", [("login-params", "POST"), ("login", "POST"), ("authenticated", "GET"), ("docsis-info/connection", "GET")])
def test_redirects_are_rejected_without_following(make_driver, path, method):
    steps = login_steps()
    redirect = (method, path, Response(307, headers={"Location": "https://other.invalid/"}))
    index = [step[1] for step in steps].index(path) if path != "docsis-info/connection" else 3
    driver, session = make_driver(steps[:index] + [redirect])
    with pytest.raises(RuntimeError, match="PYUR"):
        driver.get_docsis_data()
    assert len(session.calls) == index + 1


@pytest.mark.parametrize("cookies", [
    {},
    {"salt": "salt1234", "nonce": "not-a-nonce"},
    {"salt": "salt1234", "nonce": "1" * 1000},
] + [{"salt": salt, "nonce": "1234567890"} for salt in (
    "", "a" * 17, "$6$salt1234", "rounds=999999999$salt1234",
    "rounds=5000$a", "rounds=5000", "bad salt", "salt_1234",
    "salt-1234", "salt%2F12", "sält1234", "a\nb",
)])
def test_invalid_challenges_fail_before_sending_hash(make_driver, cookies, monkeypatch):
    driver, session = make_driver([("POST", "login-params", Response(201, cookies=cookies))])
    hash_password = Mock(side_effect=AssertionError("invalid challenge reached hashing"))
    monkeypatch.setattr("app.drivers.pyur_fast3896.sha512_crypt", hash_password)
    with pytest.raises(RuntimeError, match="PYUR invalid login challenge"):
        driver.login()
    hash_password.assert_not_called()
    assert len(session.calls) == 1
    assert not driver._authenticated


def test_cookies_are_origin_scoped_and_csrf_is_optional(make_driver):
    driver, session = make_driver(login_steps(csrf=False))
    session.cookies.set("Host-csrf_token", "foreign-token", domain="other.invalid", path="/")
    driver.login()
    assert all("X-Csrf-Token" not in call[2]["headers"] for call in session.calls)


def test_json_response_size_is_bounded_and_closed(make_driver):
    response = Response(body=b" " * (1024 * 1024 + 1))
    driver, session = make_driver(login_steps() + [("GET", "device", response)])
    with pytest.raises(RuntimeError, match="PYUR"):
        driver.get_device_info()
    assert response.closed
    assert len(session.calls) == 4


@pytest.mark.parametrize("operation", ["iter_content", "close"])
def test_response_read_and_close_errors_are_sanitized(make_driver, operation):
    response = Response(payload=[{"device": {}}])
    setattr(response, operation, Mock(side_effect=requests.ConnectionError("synthetic-private-marker")))
    driver, session = make_driver(login_steps() + [("GET", "device", response)])
    with pytest.raises(RuntimeError) as caught:
        driver.get_device_info()
    assert "synthetic-private-marker" not in "".join(traceback.format_exception(caught.value))
    assert len(session.calls) == 4


def test_device_metadata_allowlist_and_unsupported_rates(make_driver):
    driver, session = make_driver(login_steps() + [("GET", "device", Response(payload=[{"device": {
        "modelname": "FAST3896-15", "main": {"version": "synthetic-main"},
        "running": {"version": "synthetic-running"}, "uptime": 12345,
    }}]))])
    assert driver.get_device_info() == {"manufacturer": "Sagemcom", "model": "FAST3896-15", "sw_version": "synthetic-running", "uptime_seconds": 12345}
    assert driver.get_connection_info() == {}
    assert len(session.calls) == 4  # No network_parameters request.


def test_registry_hints_and_metadata():
    assert isinstance(load_driver("pyur_fast3896", "http://modem.invalid", "", "synthetic"), PyurFast3896Driver)
    assert PyurFast3896Driver.FORMAT_FAMILIES == ("pyur_api_v1",)
    assert ("pyur_fast3896", "PYUR FAST3896-15 (experimental)") in driver_registry.get_available_drivers()
    assert driver_registry.get_driver_hints()["pyur_fast3896"] == {
        "default_url": "http://192.168.100.1", "default_user": "admin",
        "credentials_required": True, "username_required": False,
    }


@pytest.mark.parametrize("index", [0, 1, 2])
@pytest.mark.parametrize("status", [401, 500])
def test_login_http_failures_are_bounded_and_safe(make_driver, index, status, caplog):
    steps = login_steps()
    method, path, _ = steps[index]
    steps[index] = (method, path, Response(status, body=b"synthetic-private-response"))
    driver, session = make_driver(steps[:index + 1])
    with pytest.raises(RuntimeError) as caught:
        driver.login()
    assert "synthetic-private-response" not in str(caught.value) + caplog.text
    assert len(session.calls) == index + 1
    assert not driver._authenticated


def test_stale_challenge_cookies_do_not_mask_missing_new_challenge(make_driver):
    driver, session = make_driver([("POST", "login-params", Response(201, body=b""))])
    session.cookies.set("salt", "salt1234", domain="modem.invalid", path="/")
    session.cookies.set("nonce", "1234567890", domain="modem.invalid", path="/")
    with pytest.raises(RuntimeError, match="challenge"):
        driver.login()
    assert len(session.calls) == 1


def test_csrf_removal_and_secure_path_scoping(make_driver):
    driver, session = make_driver(login_steps() + [
        ("GET", "device", Response(payload=[{"device": {}}])),
    ])
    driver.login()
    session.cookies.clear("modem.invalid", "/", "Host-csrf_token")
    session.cookies.set("Host-csrf_token", "secure-token", domain="modem.invalid", path="/", secure=True)
    session.cookies.set("Host-csrf_token", "other-path", domain="modem.invalid", path="/elsewhere")
    driver.get_device_info()
    assert "X-Csrf-Token" not in session.calls[-1][2]["headers"]


def test_ambiguous_matching_cookie_names_fail_safely(make_driver):
    driver, session = make_driver([])
    session.cookies.set("Host-csrf_token", "synthetic-a", domain="modem.invalid", path="/")
    session.cookies.set("Host-csrf_token", "synthetic-b", domain="modem.invalid", path="/api")
    with pytest.raises(RuntimeError, match="cookie"):
        driver.login()
    assert not session.calls


def test_full_width_client_nonce(make_driver, monkeypatch):
    driver, session = make_driver(login_steps())
    random = Mock(return_value=10**19 - 1)
    monkeypatch.setattr("app.drivers.pyur_fast3896.secrets.randbelow", random)
    driver.login()
    random.assert_called_once_with(10**19)
    assert session.calls[1][2]["data"]["cnonce"] == "9" * 19


@pytest.mark.parametrize("password", ["x" * 1025, "ü" * 513, "embedded\0nul", "\ud800"])
def test_password_work_and_encoding_are_bounded(password):
    with pytest.raises(ValueError, match="PYUR"):
        sha512_crypt(password, "salt1234")


@pytest.mark.parametrize("url", ["ftp://modem.invalid", "http://modem.invalid/path", "http://modem.invalid/?secret=synthetic", "http://synthetic:synthetic@modem.invalid", "http://modem.invalid:bad"])
def test_origin_url_validation_does_not_echo_input(url):
    with pytest.raises(ValueError, match="PYUR") as caught:
        PyurFast3896Driver(url, "", "")
    assert url not in str(caught.value)
