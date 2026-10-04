"""Reasons for a failed modem connection test (app/modem_diagnosis.py)."""

import socket

import pytest
import requests

from app import modem_diagnosis as diagnosis


def _http_error(status):
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status} Client Error", response=response)


def _wrapped(inner, message):
    try:
        try:
            raise inner
        except Exception as exc:
            raise RuntimeError(message) from exc
    except RuntimeError as outer:
        return outer


@pytest.mark.parametrize("exc, stage, reason", [
    (requests.ConnectionError("Max retries exceeded"), "login", "unreachable"),
    (requests.Timeout("read timed out"), "read", "unreachable"),
    (_wrapped(requests.ConnectionError("refused"), "Login request failed"), "login", "unreachable"),
    # Drivers that re-raise without chaining still name the connection problem.
    (RuntimeError("CM3500 authentication failed: connection refused after retry"), "login", "unreachable"),
    (_wrapped(_http_error(401), "Login request failed"), "login", "auth"),
    (_http_error(403), "read", "auth"),
    (RuntimeError("PYUR invalid login credentials"), "login", "auth"),
    (RuntimeError("Modem authentication failed: wrong password"), "login", "auth"),
    # After a successful login, the same words describe a parsing problem, not the login.
    (RuntimeError("authentication token missing in status page"), "read", "unexpected"),
    (_http_error(500), "login", "unexpected"),
    (RuntimeError("CM1000 login page did not contain a login form"), "login", "unexpected"),
    (ValueError("could not parse channel table"), "read", "unexpected"),
])
def test_failures_are_classified(exc, stage, reason):
    assert diagnosis.classify_failure(exc, stage) == reason


def test_every_reason_has_a_help_page():
    assert set(diagnosis.HELP_URLS) == {diagnosis.UNREACHABLE, diagnosis.AUTH, diagnosis.UNEXPECTED}
    assert all(url.startswith("https://github.com/itsDNNS/docsight/wiki/") for url in diagnosis.HELP_URLS.values())


class FakeSocket:
    def close(self):
        pass


def test_reachability_uses_the_url_host_and_default_ports():
    calls = []

    def connect(address, timeout):
        calls.append((address, timeout))
        return FakeSocket()

    assert diagnosis.host_reachable("https://192.168.100.1", connect=connect)
    assert diagnosis.host_reachable("http://modem.lan:8080/status", connect=connect)
    assert diagnosis.host_reachable("192.168.0.1", connect=connect)
    assert calls == [
        (("192.168.100.1", 443), diagnosis.REACHABILITY_TIMEOUT_SECONDS),
        (("modem.lan", 8080), diagnosis.REACHABILITY_TIMEOUT_SECONDS),
        (("192.168.0.1", 80), diagnosis.REACHABILITY_TIMEOUT_SECONDS),
    ]


def test_unanswered_or_malformed_addresses_are_unreachable():
    def refuse(address, timeout):
        raise socket.timeout("timed out")

    assert not diagnosis.host_reachable("http://192.168.100.1", connect=refuse)
    assert not diagnosis.host_reachable("http://:80", connect=lambda *a, **k: FakeSocket())
    assert not diagnosis.host_reachable("http://host:notaport", connect=lambda *a, **k: FakeSocket())
