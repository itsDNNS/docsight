"""Request failures in drivers: what is logged, how the connection test reads them, and the fallbacks.

Device and connection info fall back to defaults and log why without request URLs. Every logged
failure, tracebacks included, leaves the log formatter without URL user info or query values.
"""

import logging
import threading
import time
from http import HTTPStatus
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import requests

from app import main
from app.drivers.cgm4981 import CGM4981Driver
from app.drivers.ch7465 import CH7465Driver
from app.drivers.cm1000 import CM1000Driver
from app.drivers.cm3000 import CM3000Driver
from app.drivers.cm3500 import CM3500Driver
from app.drivers.cm8200 import CM8200Driver
from app.drivers.f3896lg import F3896LGDriver
from app.drivers.fritzbox import FritzBoxDriver
from app.drivers.hitron import HitronDriver
from app.drivers.hitron_coda_4680 import HitronCoda4680Driver
from app.drivers.pyur_fast3896 import PyurFast3896Driver
from app.drivers.sagemcom import SagemcomDriver
from app.drivers.sb6141 import SB6141Driver
from app.drivers.sb6183 import SB6183Driver
from app.drivers.sb6190 import SB6190Driver
from app.drivers.sb8200_cbn import SB8200CBNDriver
from app.drivers.sercom_dm1000 import SercomDM1000Driver
from app.drivers.surfboard import SurfboardDriver
from app.drivers.tc4400 import TC4400Driver
from app.drivers.ultrahub7 import UltraHub7Driver
from app.drivers.vodafone_station import VodafoneStationDriver
from app.modem_diagnosis import classify_failure
from app.runtime import get_runtime

SECRET_URL = "http://userinfo-secret:pass-secret@192.168.100.1/page?token=query-secret"
URL_SECRETS = ("query-secret", "userinfo-secret", "pass-secret")
# The two retry notices logged before a fallback, matched by their exact format template.
RETRY_NOTICES = {"CGM4981 status page fetch failed, retrying: %s", "%s request failed (%s), re-authenticating and retrying"}


def _device(manufacturer, model):
    return {"manufacturer": manufacturer, "model": model, "sw_version": ""}


HTTP_503 = "HTTPError (HTTP 503)"


def _request_error(failure):
    """A request error as requests raises it, with secrets in its URL, reason phrase and wrapped library error.

    ``failure`` is an HTTP status, or the request error class of a failed connection.
    """
    if isinstance(failure, int):
        response = requests.Response()
        response.status_code, response.url = failure, SECRET_URL
        response.reason = f"{HTTPStatus(failure).phrase} reason-secret"
        try:
            response.raise_for_status()
        except requests.HTTPError as error:
            return error
    try:
        raise OSError(f"library error for {SECRET_URL}")
    except OSError:
        try:
            raise failure(f"Max retries exceeded with url: {SECRET_URL}", request=requests.Request("GET", SECRET_URL))
        except failure as error:
            return error


def _call_with_failing_requests(monkeypatch, caplog, driver_cls, method, failure):
    """Call ``method`` while every request raises a fresh ``failure`` error; return its result or raised error."""
    def fail(*args, **kwargs):
        raise _request_error(failure)

    session = MagicMock()
    for verb in ("get", "post", "request"):
        getattr(session, verb).side_effect = fail
        monkeypatch.setattr(requests, verb, fail)
    monkeypatch.setattr(requests, "Session", lambda: session)
    monkeypatch.setattr(time, "sleep", lambda seconds: None)
    with caplog.at_level(logging.DEBUG):
        try:
            return getattr(driver_cls("http://192.168.100.1", "admin", "password"), method)()
        except Exception as error:
            return error


def _assert_one_redacted_warning(caplog, message):
    """Apart from the known retry notices, exactly one warning is logged and equals ``message``; no record keeps a URL secret."""
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING and r.msg not in RETRY_NOTICES]
    assert warnings == [message]
    assert not any(secret in caplog.text for secret in URL_SECRETS)


@pytest.mark.parametrize("driver_cls,method,message,fallback", [
    (CGM4981Driver, "get_device_info", f"CGM4981 device info unavailable: CGM4981 login request failed: {HTTP_503}",
     _device("Technicolor", "CGM4981COM")),
    (CGM4981Driver, "get_connection_info",
     f"CGM4981 connection info unavailable: CGM4981 login request failed: {HTTP_503}", {}),
    (CM3000Driver, "get_device_info", f"CM3000 device info unavailable: CM3000 status page retrieval failed: {HTTP_503}",
     _device("Netgear", "CM3000")),
    (CM3500Driver, "get_device_info", f"CM3500 device info unavailable: CM3500 status page retrieval failed: {HTTP_503}",
     _device("Arris", "CM3500B")),
    (CM3500Driver, "get_connection_info", f"CM3500 config params unavailable: {HTTP_503}", {}),
    (CM8200Driver, "get_device_info", f"CM8200 device info unavailable: CM8200 authentication failed: {HTTP_503}",
     _device("Arris", "CM8200A")),
    (CH7465Driver, "get_device_info", f"CH7465 device info unavailable: {HTTP_503}", _device("Compal", "CH7465")),
    (CH7465Driver, "get_connection_info", f"Failed to get connection info: {HTTP_503}", {}),
    (TC4400Driver, "get_device_info", f"TC4400 device info failed: {HTTP_503}", _device("Technicolor", "TC4400")),
    (F3896LGDriver, "get_device_info", f"F3896LG device info fetch failed: {HTTP_503}",
     {"manufacturer": "Sagemcom", "model": "F3896LG (Virgin Media Hub 5)"}),
    (F3896LGDriver, "get_connection_info", f"F3896LG connection info fetch failed: {HTTP_503}",
     {"connection_type": "DOCSIS 3.1"}),
    (SB8200CBNDriver, "get_device_info", f"Failed to get device info: {HTTP_503}", _device("ARRIS", "SB8200")),
    (SB8200CBNDriver, "get_connection_info", f"Failed to get connection info: {HTTP_503}", {}),
    (SagemcomDriver, "get_device_info", f"Sagemcom device info unavailable: {HTTP_503}", _device("Sagemcom", "")),
    (SB6141Driver, "get_device_info", f"SB6141 device info unavailable: {HTTP_503}", _device("Arris", "SB6141")),
    (SB6183Driver, "get_device_info", f"SB6183 device info unavailable: {HTTP_503}", _device("Arris", "SB6183")),
    (SB6190Driver, "get_device_info", f"SB6190 device info unavailable: {HTTP_503}", _device("Arris", "SB6190")),
    (SurfboardDriver, "get_device_info", f"SURFboard device info unavailable: {HTTP_503}", _device("Arris", "")),
    (VodafoneStationDriver, "_get_device_info_cga", f"CGA device info unavailable: {HTTP_503}",
     _device("CommScope/Technicolor", "Vodafone Station (CGA6444VF/CGA4322DE)")),
])
def test_unreadable_modem_logs_cause_and_returns_fallback(driver_cls, method, message, fallback, monkeypatch, caplog):
    assert _call_with_failing_requests(monkeypatch, caplog, driver_cls, method, 503) == fallback
    _assert_one_redacted_warning(caplog, message)


@pytest.mark.parametrize("status,message", [
    (503, "TG device info retrieval failed: HTTPError (HTTP 503)"),
    (401, "TG device info retrieval failed after retry: HTTPError (HTTP 401)"),
])
def test_vodafone_stale_session_failure_names_only_error_type_and_status(status, message, monkeypatch, caplog):
    assert _call_with_failing_requests(monkeypatch, caplog, VodafoneStationDriver, "_get_device_info_tg", status) == {
        "manufacturer": "CommScope/ARRIS", "model": "Vodafone Station (TG6442VF/TG3442DE)",
    }
    _assert_one_redacted_warning(caplog, message)


REQUEST_FAILURES = (401, 500, 504, requests.ConnectionError, requests.ReadTimeout)
# The connection test reason for each of REQUEST_FAILURES, or None when the call falls back instead of raising.
BY_TYPE = ("auth", "unexpected", "unreachable", "unreachable", "unreachable")
# Wrappers worded "authentication failed" or "login failed" make an HTTP 500 at login read as a login error.
BY_WORDING = ("auth", "auth", "unreachable", "unreachable", "unreachable")
FALLS_BACK = (None,) * 5
# Pre-login checks: without a login these DOCSIS reads stop with "Not authenticated" before any request.
PRE_LOGIN_CHECK = ("unexpected",) * 5
ENTRY_POINTS = [
    (CGM4981Driver, "login", BY_TYPE), (CGM4981Driver, "get_docsis_data", BY_TYPE),
    (CH7465Driver, "login", BY_TYPE), (CH7465Driver, "get_docsis_data", BY_TYPE),
    (CM1000Driver, "login", BY_WORDING), (CM1000Driver, "get_docsis_data", BY_TYPE),
    (CM3000Driver, "login", BY_WORDING), (CM3000Driver, "get_docsis_data", BY_TYPE),
    (CM3500Driver, "login", BY_WORDING), (CM3500Driver, "get_docsis_data", BY_TYPE),
    # CM8200 drops the reason phrase of its login request, so a 504 is read by the wrapper wording.
    (CM8200Driver, "login", ("auth", "auth", "auth", "unreachable", "unreachable")),
    (CM8200Driver, "get_docsis_data", ("auth", "unexpected", "unexpected", "unreachable", "unreachable")),
    (F3896LGDriver, "login", BY_TYPE), (F3896LGDriver, "get_docsis_data", BY_TYPE),
    (FritzBoxDriver, "login", BY_TYPE), (FritzBoxDriver, "get_docsis_data", BY_TYPE),
    (FritzBoxDriver, "get_device_info", FALLS_BACK), (FritzBoxDriver, "get_connection_info", FALLS_BACK),
    (HitronDriver, "login", BY_TYPE), (HitronDriver, "get_docsis_data", FALLS_BACK),
    (HitronCoda4680Driver, "login", BY_WORDING), (HitronCoda4680Driver, "get_docsis_data", FALLS_BACK),
    (PyurFast3896Driver, "login", BY_TYPE), (PyurFast3896Driver, "get_docsis_data", BY_TYPE),
    (SagemcomDriver, "login", BY_WORDING), (SagemcomDriver, "get_docsis_data", BY_TYPE),
    (SB6141Driver, "login", BY_TYPE), (SB6141Driver, "get_docsis_data", BY_TYPE),
    (SB6183Driver, "login", BY_TYPE), (SB6183Driver, "get_docsis_data", BY_TYPE),
    (SB6190Driver, "login", BY_WORDING), (SB6190Driver, "get_docsis_data", BY_TYPE),
    (SB8200CBNDriver, "login", BY_TYPE), (SB8200CBNDriver, "get_docsis_data", BY_TYPE),
    (SercomDM1000Driver, "login", BY_TYPE), (SercomDM1000Driver, "get_docsis_data", FALLS_BACK),
    (SurfboardDriver, "login", BY_WORDING), (SurfboardDriver, "get_docsis_data", BY_TYPE),
    (TC4400Driver, "login", BY_WORDING), (TC4400Driver, "get_docsis_data", BY_TYPE),
    (UltraHub7Driver, "login", BY_WORDING), (UltraHub7Driver, "get_docsis_data", PRE_LOGIN_CHECK),
    (VodafoneStationDriver, "login", BY_WORDING), (VodafoneStationDriver, "get_docsis_data", PRE_LOGIN_CHECK),
]


@pytest.mark.parametrize("driver_cls,method,reasons", ENTRY_POINTS)
def test_connection_test_reason_for_each_request_failure(driver_cls, method, reasons, monkeypatch, caplog):
    stage = "login" if method == "login" else "read"
    results = [_call_with_failing_requests(monkeypatch, caplog, driver_cls, method, f) for f in REQUEST_FAILURES]
    assert tuple(classify_failure(r, stage) if isinstance(r, Exception) else None for r in results) == reasons


def _manual_poll(error, make_app, make_config):
    """Let a manual poll fail with ``error``; the poll handler logs it with its traceback."""
    def collect():
        raise error

    app = make_app(config_manager=make_config({"modem_type": "fritzbox"}))
    get_runtime(app).modem_collector = SimpleNamespace(collect=collect, _collect_lock=threading.Lock())
    assert app.test_client().post("/api/poll").status_code == 500


@pytest.mark.parametrize("driver_cls,method,failure,raises", [
    *[(d, m, f, r is not None) for d, m, reasons in ENTRY_POINTS for f, r in zip(REQUEST_FAILURES, reasons)],
    (SurfboardDriver, "login", requests.exceptions.SSLError, True),
])
def test_logged_request_failures_show_no_url_userinfo_or_query(
    driver_cls, method, failure, raises, monkeypatch, caplog, make_app, make_config
):
    result = _call_with_failing_requests(monkeypatch, caplog, driver_cls, method, failure)
    assert isinstance(result, Exception) == raises
    if raises:
        _manual_poll(result, make_app, make_config)
        assert any(r.exc_info and r.getMessage() == "Manual poll failed" for r in caplog.records)
    # The formatter app.main puts on the root log handlers, applied to every captured record.
    formatter = main._RedactingFormatter(main._LOG_FORMAT)
    logged = "\n".join(formatter.format(record) for record in caplog.records)
    assert not any(secret in logged for secret in URL_SECRETS)
