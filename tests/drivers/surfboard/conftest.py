import pytest
import requests
from unittest.mock import MagicMock, patch

from app.drivers.surfboard import SurfboardDriver
from ._data import (
    HNAP_DS_RESPONSE,
    HNAP_DS_RESPONSE_MOTO,
    HNAP_DEVICE_RESPONSE,
    HNAP_DEVICE_RESPONSE_MOTO,
)


@pytest.fixture
def driver():
    return SurfboardDriver("https://192.168.100.1", "admin", "password")


@pytest.fixture
def mock_hnap(driver):
    """Patch _hnap_post to return channel data."""
    def side_effect(action, body, **kwargs):
        if action == "GetMultipleHNAPs":
            keys = body.get("GetMultipleHNAPs", {})
            if "GetCustomerStatusDownstreamChannelInfo" in keys:
                return HNAP_DS_RESPONSE
            if "GetMotoStatusDownstreamChannelInfo" in keys:
                return HNAP_DS_RESPONSE_MOTO
            if "GetCustomerStatusConnectionInfo" in keys:
                return HNAP_DEVICE_RESPONSE
            if "GetMotoStatusConnectionInfo" in keys:
                return HNAP_DEVICE_RESPONSE_MOTO
        return {}

    with patch.object(driver, "_hnap_post", side_effect=side_effect):
        yield driver


@pytest.fixture
def hnap_headers(driver):
    """Send one _hnap_post(action) at a fixed clock and return the headers it posted."""
    def send(action, now=1700000000.0):
        with patch.object(driver._session, "post") as mock_post, \
             patch("app.drivers.surfboard.time") as mock_time:
            mock_post.return_value.json.return_value = {"result": "ok"}
            mock_time.time.return_value = now
            driver._hnap_post(action, {action: {}})
        return mock_post.call_args.kwargs["headers"]
    return send


@pytest.fixture
def failing_fetch(driver, monkeypatch):
    """Make _fetch_docsis_data raise the given errors in turn, then return empty data.

    An int stands for an HTTPError with that status. Returns the action
    namespace each call ran under.
    """
    def install(*errors):
        calls = []

        def fetch():
            calls.append(driver._action_ns)
            if len(calls) <= len(errors):
                error = errors[len(calls) - 1]
                if isinstance(error, int):
                    error = requests.HTTPError(response=MagicMock(status_code=error))
                raise error
            return {
                "channelDs": {"docsis30": [], "docsis31": []},
                "channelUs": {"docsis30": [], "docsis31": []},
            }

        monkeypatch.setattr(driver, "_fetch_docsis_data", fetch)
        return calls
    return install
