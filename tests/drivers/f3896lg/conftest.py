"""Fixtures for F3896LG driver tests: fake requests session serving REST paths."""

from unittest.mock import MagicMock

import pytest

from app.drivers.f3896lg import F3896LGDriver
from . import _data

_ROUTES = {
    "cablemodem/downstream": _data.DOWNSTREAM,
    "cablemodem/upstream": _data.UPSTREAM,
    "cablemodem/state_": _data.STATE,
    "cablemodem/registration": _data.REGISTRATION,
    "cablemodem/serviceflows": _data.SERVICEFLOWS,
}


@pytest.fixture
def driver():
    d = F3896LGDriver("https://192.168.100.1", "", "")

    def fake_get(url, timeout=None):
        path = url.split("/rest/v1/", 1)[1]
        resp = MagicMock()
        resp.json.return_value = _ROUTES[path]
        resp.raise_for_status.return_value = None
        return resp

    d._session = MagicMock()
    d._session.get.side_effect = fake_get
    return d
