"""Request failure contracts shared by modem drivers.

HTML drivers rebuild their session once when the login loses its connection.
JSON drivers raise a fetch failure in strict mode and log it otherwise.
"""

import base64
import logging
import traceback
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.drivers.cm1000 import CM1000Driver
from app.drivers.cm3000 import CM3000Driver
from app.drivers.cm3500 import CM3500Driver
from app.drivers.cm8200 import CM8200Driver
from app.drivers.hitron_coda_4680 import HitronCoda4680Driver
from app.drivers.sercom_dm1000 import SercomDM1000Driver
from app.modem_diagnosis import classify_failure
from tests.test_hitron_coda_4680_driver import make_http_error_response as hitron_http_error
from tests.test_hitron_coda_4680_driver import make_response as hitron_response
from tests.test_sercom_dm1000_driver import make_http_error_response as sercom_http_error
from tests.test_sercom_dm1000_driver import make_response as sercom_response

CREDENTIALS = base64.b64encode(b"admin:secret").decode()  # the query CM8200 logs in with
HTTP_401 = f"401 Client Error for url: /cmconnectionstatus.html?{CREDENTIALS}"
UNAUTHORIZED = requests.Response()
UNAUTHORIZED.status_code, UNAUTHORIZED.url = 401, f"https://192.168.100.1/cmconnectionstatus.html?{CREDENTIALS}"
UNAUTHORIZED.request = requests.Request("GET", UNAUTHORIZED.url)
# Driver, entry point, login request method, session settings and (prefix, TLS
# security level) adapter mounts every built session must have, and how an
# HTTP 401 appears (CM8200 keeps the credential-carrying URL out of the message
# and the exception chain).
# CM8200 also logs in again when its status page is gone.
LOGIN_DRIVERS = [
    pytest.param(CM1000Driver, "login", "get", {"auth": ("admin", "secret")}, [], HTTP_401, id="cm1000"),
    pytest.param(CM3000Driver, "login", "get", {"auth": ("admin", "secret")}, [], HTTP_401, id="cm3000"),
    pytest.param(CM3500Driver, "login", "post", {"verify": False}, [], HTTP_401, id="cm3500"),
    pytest.param(CM8200Driver, "login", "get", {"verify": False}, [("https://", 0)], "HTTPError (HTTP 401)", id="cm8200"),
    pytest.param(CM8200Driver, "_fetch_status_page", "get", {"verify": False}, [("https://", 0)],
                 "HTTPError (HTTP 401)", id="cm8200-fetch"),
]


def _login(driver_cls, entry, method, error, caplog):
    """Call ``entry`` while every request fails with ``error``; return the raised error, sessions and warnings."""
    sessions = []

    def new_session():
        session = MagicMock()
        getattr(session, method).side_effect = error
        sessions.append(session)
        return session

    with patch("requests.Session", side_effect=new_session), pytest.raises(RuntimeError) as raised:
        getattr(driver_cls("http://192.168.100.1", "admin", "secret"), entry)()
    warnings = [(r.name, r.getMessage()) for r in caplog.records if r.levelno == logging.WARNING]
    return raised.value, sessions, warnings


def _shows_request_url(error):
    """Whether the credentials appear in the formatted traceback or anywhere in the exception graph."""
    parts, pending, seen = ["".join(traceback.format_exception(error))], [error], set()
    while pending:
        exc = pending.pop()
        if exc is None or id(exc) in seen:
            continue
        seen.add(id(exc))
        response = getattr(exc, "response", None)
        holders = (getattr(exc, "request", None), response, getattr(response, "request", None))
        parts += [repr(exc.args), *(str(getattr(holder, "url", None)) for holder in holders)]
        pending += [exc.__cause__, exc.__context__]
    return CREDENTIALS in " ".join(parts)


@pytest.mark.parametrize("driver_cls, entry, method, settings, mounts, detail", LOGIN_DRIVERS)
def test_login_rebuilds_session_once_after_connection_loss(driver_cls, entry, method, settings, mounts, detail, caplog):
    label = driver_cls.__name__.removesuffix("Driver")
    dropped = requests.ConnectionError(f"Max retries exceeded with url: /cmconnectionstatus.html?{CREDENTIALS}",
                                       request=UNAUTHORIZED.request)
    error, sessions, warnings = _login(driver_cls, entry, method, dropped, caplog)

    assert str(error) == f"{label} authentication failed: connection refused after retry"
    assert isinstance(error.__cause__ or error.__context__, requests.ConnectionError)
    assert _shows_request_url(error) == (detail == HTTP_401)
    assert warnings == [(f"docsis.driver.{label.lower()}", f"{label} connection lost, retrying with fresh session")]
    assert len(sessions) == 2
    sessions[0].close.assert_called_once_with()
    assert getattr(sessions[1], method).call_count == 1
    for session in sessions:
        assert {name: getattr(session, name) for name in settings} == settings
        assert [(c.args[0], c.args[1]._sec_level) for c in session.mount.call_args_list] == mounts


@pytest.mark.parametrize("driver_cls, entry, method, settings, mounts, detail", LOGIN_DRIVERS)
def test_login_reports_http_errors_without_reconnect(driver_cls, entry, method, settings, mounts, detail, caplog):
    label = driver_cls.__name__.removesuffix("Driver")
    http_error = requests.HTTPError(HTTP_401, response=UNAUTHORIZED)
    error, sessions, warnings = _login(driver_cls, entry, method, http_error, caplog)

    assert str(error) == f"{label} authentication failed: {detail}"
    assert isinstance(error.__cause__ or error.__context__, requests.HTTPError)
    assert _shows_request_url(error) == (detail == HTTP_401)
    assert {classify_failure(error, stage) for stage in ("login", "read")} == {"auth"}
    assert warnings == []
    assert len(sessions) == 1


def _hitron():
    return HitronCoda4680Driver("http://192.168.100.1", "username", "secret")


def _sercom():
    return SercomDM1000Driver("http://192.168.100.1", "technician", "secret")


H, S = "Hitron CODA-4680", "Sercom DM1000"
ODD = requests.RequestException("odd", response=UNAUTHORIZED)
# Driver factory, endpoint, response, re-login allowed, re-login error, message, chained cause.
FETCH_FAILURES = [
    (_hitron, "/p", hitron_http_error(500), True, None, f"{H} fetch /p failed: 500 Client Error", requests.HTTPError),
    (_hitron, "/p", requests.Timeout("slow"), True, None, f"{H} fetch /p failed: slow", requests.Timeout),
    (_hitron, "/p", ODD, True, None, f"{H} fetch /p failed: odd", requests.RequestException),
    (_hitron, "/p", hitron_http_error(403), True, RuntimeError("no"), f"{H} re-login before fetching /p failed: no",
     RuntimeError),
    (_hitron, "/p", hitron_response({"errCode": "9", "errMsg": "busy"}), True, None, f"{H} /p failed: busy", None),
    (_sercom, "t", sercom_http_error(500), True, None, f"{S} fetch t failed: 500 Client Error", requests.HTTPError),
    (_sercom, "t", requests.Timeout("slow"), True, None, f"{S} fetch t failed: slow", requests.Timeout),
    (_sercom, "t", ODD, True, None, f"{S} fetch t failed: odd", requests.RequestException),
    (_sercom, "t", sercom_response({}, headers={"Location": "login.html?token=c2VjcmV0"}), False, None,
     f"{S} fetch t redirected to login (Location: login.html)", None),
    (_sercom, "t", sercom_response({}, headers={"Location": "http://[bad/login.html"}), True, RuntimeError("no"),
     f"{S} re-login before fetching t failed: no", RuntimeError),
    (_sercom, "t", sercom_response("<html>", content_type="text/html"), False, None,
     f"{S} fetch t returned an HTML login page", None),
    (_sercom, "t", sercom_response("{"), True, None, f"{S} fetch t returned invalid JSON payload", ValueError),
    (_sercom, "t", sercom_response([1]), True, None, f"{S} fetch t returned non-object JSON payload", None),
    (_sercom, "t", sercom_http_error(401), True, RuntimeError("no"), f"{S} re-login before fetching t failed: no",
     RuntimeError),
    (_sercom, "t", sercom_response({"errCode": "9", "errMsg": "busy"}), True, None, f"{S} t failed: busy", None),
]


@pytest.mark.parametrize("strict", [True, False])
@pytest.mark.parametrize("make_driver, endpoint, response, reauth, login_error, message, cause", FETCH_FAILURES)
def test_fetch_failure_raises_in_strict_mode_and_warns_otherwise(
    make_driver, endpoint, response, reauth, login_error, message, cause, strict, caplog
):
    driver = make_driver()
    with patch.object(driver._session, "get", side_effect=[response]) as get, \
            patch.object(driver, "login", side_effect=login_error) as login:
        if strict:
            with pytest.raises(RuntimeError) as raised:
                driver._fetch_payload(endpoint, raise_on_error=True, allow_reauth=reauth)
            assert str(raised.value) == message
            assert type(raised.value.__cause__) is (cause or type(None))
            assert raised.value.__suppress_context__ == (cause is not None)
        else:
            assert driver._fetch_payload(endpoint, allow_reauth=reauth) == {}
            assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == [message]
    assert login.call_count == (login_error is not None)
    assert get.call_count == 1
