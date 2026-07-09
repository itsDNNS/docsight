"""Tests for Arris SB6183 modem driver."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.drivers.sb6183 import SB6183Driver

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "sb6183"
SAMPLE_STATUS_HTML = (FIXTURE_DIR / "RgConnect.asp.html").read_text(encoding="utf-8")
SAMPLE_SWINFO_HTML = (FIXTURE_DIR / "RgSwInfo.asp.html").read_text(encoding="utf-8")


@pytest.fixture
def driver():
    return SB6183Driver("http://192.168.100.1/", "", "")


@pytest.fixture
def mock_status(driver):
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = SAMPLE_STATUS_HTML
    with patch.object(driver._session, "get", return_value=mock_response):
        yield driver


class TestDriverInit:
    def test_strips_trailing_slash(self):
        d = SB6183Driver("http://192.168.100.1/", "", "")
        assert d._url == "http://192.168.100.1"

    def test_load_via_registry(self):
        from app.drivers import load_driver
        d = load_driver("sb6183", "http://192.168.100.1", "", "")
        assert isinstance(d, SB6183Driver)

    def test_registry_hints_mark_credentials_optional(self):
        from app.drivers import driver_registry
        hints = driver_registry.get_driver_hints()["sb6183"]
        assert hints["default_url"] == "http://192.168.100.1"
        assert hints["credentials_required"] is False


class TestLogin:
    def test_login_verifies_rgconnect(self, driver):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = SAMPLE_STATUS_HTML
        with patch.object(driver._session, "get", return_value=mock_resp) as mock_get:
            driver.login()
            assert mock_get.call_args[0][0].endswith("/RgConnect.asp")

    def test_login_rejects_non_status_page(self, driver):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "<html><body>Product Information</body></html>"
        with patch.object(driver._session, "get", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="status page not returned"):
                driver.login()

    def test_login_raises_on_connection_error(self, driver):
        with patch.object(driver._session, "get", side_effect=requests.ConnectionError("refused")):
            with pytest.raises(RuntimeError, match="SB6183 connection failed"):
                driver.login()


class TestDownstream:
    def test_channel_count(self, mock_status):
        data = mock_status.get_docsis_data()
        assert len(data["channelDs"]["docsis30"]) == 16
        assert data["channelDs"]["docsis31"] == []

    def test_first_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelDs"]["docsis30"][0]
        assert ch["channelID"] == 6
        assert ch["frequency"] == "315 MHz"
        assert ch["powerLevel"] == pytest.approx(0.7)
        assert ch["mer"] == pytest.approx(40.2)
        assert ch["mse"] == pytest.approx(-40.2)
        assert ch["modulation"] == "QAM256"
        assert ch["corrErrors"] == 29
        assert ch["nonCorrErrors"] == 0

    def test_last_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelDs"]["docsis30"][-1]
        assert ch["channelID"] == 33
        assert ch["frequency"] == "495 MHz"
        assert ch["powerLevel"] == pytest.approx(0.5)
        assert ch["corrErrors"] == 55
        assert ch["nonCorrErrors"] == 0


class TestUpstream:
    def test_channel_count(self, mock_status):
        data = mock_status.get_docsis_data()
        assert len(data["channelUs"]["docsis30"]) == 4
        assert data["channelUs"]["docsis31"] == []

    def test_first_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelUs"]["docsis30"][0]
        assert ch["channelID"] == 67
        assert ch["frequency"] == "30.4 MHz"
        assert ch["powerLevel"] == pytest.approx(48.3)
        assert ch["modulation"] == "ATDMA"
        assert ch["multiplex"] == "ATDMA"

    def test_last_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelUs"]["docsis30"][-1]
        assert ch["channelID"] == 68
        assert ch["frequency"] == "36.8 MHz"
        assert ch["powerLevel"] == pytest.approx(48.5)


class TestDeviceInfo:
    def test_parses_swinfo_page(self, driver):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = SAMPLE_SWINFO_HTML
        with patch.object(driver._session, "get", return_value=mock_resp) as mock_get:
            info = driver.get_device_info()
        assert mock_get.call_args[0][0].endswith("/RgSwInfo.asp")
        assert info["manufacturer"] == "Arris"
        assert info["model"] == "SB6183"
        assert info["sw_version"] == "D30CM-OSPREY-2.4.0.3-GA-00-NOSH"
        assert info["hw_version"] == "1"
        assert info["docsis_status"] == "DOCSIS 3.0"

    def test_fallback_on_connection_error(self, driver):
        with patch.object(driver._session, "get", side_effect=requests.ConnectionError()):
            info = driver.get_device_info()
            assert info == {"manufacturer": "Arris", "model": "SB6183", "sw_version": ""}

    def test_connection_info_empty(self, driver):
        assert driver.get_connection_info() == {}


class TestEdgeCases:
    def test_no_tables(self, driver):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "<html><body></body></html>"
        with patch.object(driver._session, "get", return_value=mock_resp):
            data = driver.get_docsis_data()
        assert data["channelDs"]["docsis30"] == []
        assert data["channelUs"]["docsis30"] == []

    def test_get_docsis_data_raises_on_connection_error(self, driver):
        with patch.object(driver._session, "get", side_effect=requests.ConnectionError("refused")):
            with pytest.raises(RuntimeError, match="SB6183 DOCSIS data retrieval failed"):
                driver.get_docsis_data()

    def test_unlocked_channels_are_skipped(self, driver):
        html = """<html><body>
        <table><tr><th>Downstream Bonded Channels</th></tr>
        <tr><td>1</td><td>Locked</td><td>QAM256</td><td>6</td><td>315000000 Hz</td><td>0.7 dBmV</td><td>40.2 dB</td><td>29</td><td>0</td></tr>
        <tr><td>2</td><td>Not Locked</td><td>QAM256</td><td>1</td><td>285000000 Hz</td><td>0.4 dBmV</td><td>40.0 dB</td><td>1</td><td>0</td></tr>
        </table>
        <table><tr><th>Upstream Bonded Channels</th></tr>
        <tr><td>1</td><td>Locked</td><td>ATDMA</td><td>67</td><td>5120 Ksym/sec</td><td>30400000 Hz</td><td>48.3 dBmV</td></tr>
        <tr><td>2</td><td>Not Locked</td><td>ATDMA</td><td>65</td><td>5120 Ksym/sec</td><td>17600000 Hz</td><td>47.5 dBmV</td></tr>
        </table></body></html>"""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = html
        with patch.object(driver._session, "get", return_value=mock_resp):
            data = driver.get_docsis_data()
        assert [ch["channelID"] for ch in data["channelDs"]["docsis30"]] == [6]
        assert [ch["channelID"] for ch in data["channelUs"]["docsis30"]] == [67]


class TestAnalyzerIntegration:
    def test_full_pipeline(self, mock_status):
        from app.analyzer import analyze
        data = mock_status.get_docsis_data()
        result = analyze(data)
        assert result["summary"]["ds_total"] == 16
        assert result["summary"]["us_total"] == 4
        assert result["summary"]["health"] in ("good", "tolerated", "marginal", "poor", "critical")
        assert len(result["ds_channels"]) == 16
        assert len(result["us_channels"]) == 4
        assert {ch["docsis_version"] for ch in result["ds_channels"]} == {"3.0"}
        assert {ch["docsis_version"] for ch in result["us_channels"]} == {"3.0"}
