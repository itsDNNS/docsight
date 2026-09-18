"""Modem connection tests must not expose driver exception details."""

import logging
import secrets
from unittest.mock import patch

import pytest

from app.config import PASSWORD_MASK
from app.runtime import get_runtime


MODEM_URL = "http://redaction-modem.invalid"
MODEM_USER = "redaction-user-sentinel"
MODEM_PASSWORD = secrets.token_urlsafe(24)
PRIVATE_PATH = "/private/redaction-sentinel/config.json"
ROUTES = ["/api/test-modem", "/api/test-fritz"]


@pytest.fixture
def modem_app(make_app, make_config):
    config = make_config({"modem_password": MODEM_PASSWORD})
    application = make_app(config_manager=config)
    assert get_runtime(application).driver_registry.is_builtin("fritzbox")
    return application


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("password", [MODEM_PASSWORD, PASSWORD_MASK], ids=["plain", "masked"])
@pytest.mark.parametrize("exception_type", [ValueError, Exception])
@pytest.mark.parametrize("phase", ["constructor", "login", "get_device_info"])
def test_builtin_modem_errors_are_redacted(
    modem_app, caplog, route, password, exception_type, phase,
):
    sentinels = (MODEM_USER, MODEM_PASSWORD, MODEM_URL, PRIVATE_PATH)
    error = exception_type(" ".join(sentinels) + "\nprivate exception details")
    with patch("app.drivers.fritzbox.FritzBoxDriver", autospec=True) as constructor:
        driver = constructor.return_value
        failing_call = constructor if phase == "constructor" else getattr(driver, phase)
        failing_call.side_effect = error
        caplog.clear()
        with caplog.at_level(logging.DEBUG):
            response = modem_app.test_client().post(route, json={
                "modem_type": "fritzbox", "modem_url": MODEM_URL,
                "modem_user": MODEM_USER, "modem_password": password,
            })
        constructor.assert_called_once_with(MODEM_URL, MODEM_USER, MODEM_PASSWORD)
        assert driver.login.call_count == (phase != "constructor")
        assert driver.get_device_info.call_count == (phase == "get_device_info")

    assert response.status_code == 200
    for output in (response.text, caplog.text):
        for sentinel in sentinels:
            assert sentinel not in output
    assert response.json == {"success": False, "error": "Modem connection failed"}
    assert caplog.record_tuples == [("docsis.web", logging.WARNING, "Modem test failed")]
    assert all(record.exc_info is None and record.stack_info is None for record in caplog.records)


@pytest.mark.parametrize("route", ROUTES)
@pytest.mark.parametrize("password", [MODEM_PASSWORD, PASSWORD_MASK], ids=["plain", "masked"])
def test_builtin_modem_success_preserves_password_resolution(modem_app, route, password):
    with patch("app.drivers.fritzbox.FritzBoxDriver", autospec=True) as constructor:
        driver = constructor.return_value
        driver.get_device_info.return_value = {"model": "Test Modem"}
        response = modem_app.test_client().post(route, json={
            "modem_type": "fritzbox", "modem_url": MODEM_URL,
            "modem_user": MODEM_USER, "modem_password": password,
        })
        constructor.assert_called_once_with(MODEM_URL, MODEM_USER, MODEM_PASSWORD)
        driver.login.assert_called_once_with()
        driver.get_device_info.assert_called_once_with()
    assert response.status_code == 200
    assert response.json == {"success": True, "model": "Test Modem"}


@pytest.mark.parametrize("route", ROUTES)
def test_modem_aliases_require_authentication(modem_app, route):
    get_runtime(modem_app).config_manager.save({"admin_password": "test-admin-password"})
    with patch("app.drivers.fritzbox.FritzBoxDriver", autospec=True) as constructor:
        response = modem_app.test_client().post(route, json={"modem_type": "fritzbox"})
        constructor.assert_not_called()
    assert response.status_code == 401
    assert response.json == {"error": "Authentication required"}
