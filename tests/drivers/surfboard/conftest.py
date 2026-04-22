import pytest
from unittest.mock import patch

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
