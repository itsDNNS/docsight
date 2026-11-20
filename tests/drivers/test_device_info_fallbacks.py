"""Device and connection info fall back to defaults and log why, without request URLs, when the modem cannot be read."""

import logging
from unittest.mock import MagicMock

import pytest
import requests

from app.drivers.cgm4981 import CGM4981Driver
from app.drivers.ch7465 import CH7465Driver
from app.drivers.cm3000 import CM3000Driver
from app.drivers.cm3500 import CM3500Driver
from app.drivers.cm8200 import CM8200Driver
from app.drivers.f3896lg import F3896LGDriver
from app.drivers.sagemcom import SagemcomDriver
from app.drivers.sb6141 import SB6141Driver
from app.drivers.sb6183 import SB6183Driver
from app.drivers.sb6190 import SB6190Driver
from app.drivers.sb8200_cbn import SB8200CBNDriver
from app.drivers.surfboard import SurfboardDriver
from app.drivers.tc4400 import TC4400Driver
from app.drivers.vodafone_station import VodafoneStationDriver

URL_SECRETS = ("query-secret", "userinfo-secret", "password-secret")
# The two retry notices logged before a fallback, matched by their exact format template.
RETRY_NOTICES = {"CGM4981 status page fetch failed, retrying: %s", "%s request failed (%s), re-authenticating and retrying"}


def _device(manufacturer, model):
    return {"manufacturer": manufacturer, "model": model, "sw_version": ""}


HTTP_503 = "HTTPError (HTTP 503)"


def _fallback_of_unreadable_modem(monkeypatch, caplog, driver_cls, method, status):
    """Call ``method`` while every request fails with HTTP ``status`` and return its result."""
    response = requests.Response()
    response.status_code = status
    response.url = "http://userinfo-secret:password-secret@192.168.100.1/page?token=query-secret"
    session = MagicMock()
    for verb in ("get", "post", "request"):
        getattr(session, verb).side_effect = requests.HTTPError(
            f"{status} Server Error: Busy for url: {response.url}", response=response)
    monkeypatch.setattr(requests, "Session", lambda: session)
    with caplog.at_level(logging.DEBUG):
        return getattr(driver_cls("http://192.168.100.1", "admin", "password"), method)()


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
    assert _fallback_of_unreadable_modem(monkeypatch, caplog, driver_cls, method, 503) == fallback
    _assert_one_redacted_warning(caplog, message)


@pytest.mark.parametrize("status,message", [
    (503, "TG device info retrieval failed: HTTPError (HTTP 503)"),
    (401, "TG device info retrieval failed after retry: HTTPError (HTTP 401)"),
])
def test_vodafone_stale_session_failure_names_only_error_type_and_status(status, message, monkeypatch, caplog):
    assert _fallback_of_unreadable_modem(monkeypatch, caplog, VodafoneStationDriver, "_get_device_info_tg", status) == {
        "manufacturer": "CommScope/ARRIS", "model": "Vodafone Station (TG6442VF/TG3442DE)",
    }
    _assert_one_redacted_warning(caplog, message)
