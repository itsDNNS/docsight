"""Tests for fritzbox_cable segment utilization collector."""

from unittest.mock import patch, MagicMock
import pytest
from app.modules.fritzbox_cable.collector import SegmentUtilizationCollector


SEGMENT_RESPONSE = {
    "lastSampleTime": 1773066360,
    "sampleInterval": 60000,
    "data": [
        {
            "mediaType": "cable",
            "type": "own",
            "downstream": [0.01, 0.02, None, 0.05],
            "upstream": [0.1, 0.2, None, 0.17],
        },
        {
            "mediaType": "cable",
            "type": "total",
            "downstream": [5.0, 6.0, None, 6.2],
            "upstream": [10.0, 11.0, None, 11.4],
        },
    ],
}


@pytest.fixture
def mock_config():
    cfg = MagicMock()
    cfg.get.side_effect = lambda k, d=None: {
        "modem_type": "fritzbox",
        "segment_utilization_enabled": True,
        "modem_url": "http://192.168.178.1",
        "modem_user": "admin",
        "modem_password": "secret",
    }.get(k, d)
    return cfg


@pytest.fixture
def mock_storage(tmp_path):
    s = MagicMock()
    s.db_path = str(tmp_path / "test.db")
    return s


@pytest.fixture
def collector(mock_config, mock_storage):
    return SegmentUtilizationCollector(
        config_mgr=mock_config, storage=mock_storage, web=MagicMock()
    )


class TestIsEnabled:
    def test_enabled_when_fritzbox_and_config_true(self, collector):
        assert collector.is_enabled() is True

    def test_disabled_when_not_fritzbox(self, mock_config, mock_storage):
        mock_config.get.side_effect = lambda k, d=None: {
            "modem_type": "arris",
            "segment_utilization_enabled": True,
        }.get(k, d)
        c = SegmentUtilizationCollector(config_mgr=mock_config, storage=mock_storage, web=MagicMock())
        assert c.is_enabled() is False

    def test_disabled_when_config_false(self, mock_config, mock_storage):
        mock_config.get.side_effect = lambda k, d=None: {
            "modem_type": "fritzbox",
            "segment_utilization_enabled": False,
        }.get(k, d)
        c = SegmentUtilizationCollector(config_mgr=mock_config, storage=mock_storage, web=MagicMock())
        assert c.is_enabled() is False


class TestCollect:
    @patch("app.modules.fritzbox_cable.collector.requests")
    @patch("app.modules.fritzbox_cable.collector.fb")
    def test_collect_success(self, mock_fb, mock_requests, collector):
        mock_fb.login.return_value = "test-sid"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SEGMENT_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        result = collector.collect()

        assert result.success is True
        assert result.source == "segment_utilization"
        mock_requests.get.assert_called_once()
        call_kwargs = mock_requests.get.call_args
        assert "AVM-SID test-sid" in call_kwargs[1]["headers"]["AUTHORIZATION"]

    @patch("app.modules.fritzbox_cable.collector.requests")
    @patch("app.modules.fritzbox_cable.collector.fb")
    def test_collect_stores_last_non_null(self, mock_fb, mock_requests, collector):
        mock_fb.login.return_value = "test-sid"
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = SEGMENT_RESPONSE
        mock_resp.raise_for_status = MagicMock()
        mock_requests.get.return_value = mock_resp

        result = collector.collect()
        assert result.data["ds_total"] == pytest.approx(6.2)
        assert result.data["us_total"] == pytest.approx(11.4)
        assert result.data["ds_own"] == pytest.approx(0.05)
        assert result.data["us_own"] == pytest.approx(0.17)

    @patch("app.modules.fritzbox_cable.collector.fb")
    def test_collect_login_failure(self, mock_fb, collector):
        mock_fb.login.side_effect = RuntimeError("Auth failed")
        result = collector.collect()
        assert result.success is False
        assert "Auth failed" in result.error


class TestLastNonNull:
    def test_last_non_null_basic(self):
        from app.modules.fritzbox_cable.collector import _last_non_null
        assert _last_non_null([1.0, 2.0, None, 3.0]) == pytest.approx(3.0)

    def test_last_non_null_trailing_nulls(self):
        from app.modules.fritzbox_cable.collector import _last_non_null
        assert _last_non_null([1.0, 2.0, None]) == pytest.approx(2.0)

    def test_last_non_null_all_none(self):
        from app.modules.fritzbox_cable.collector import _last_non_null
        assert _last_non_null([None, None, None]) is None

    def test_last_non_null_empty(self):
        from app.modules.fritzbox_cable.collector import _last_non_null
        assert _last_non_null([]) is None
