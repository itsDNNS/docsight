"""Tests for Arris SB6190 modem driver."""

import pytest
import requests
from unittest.mock import patch, MagicMock
from app.drivers.sb6190 import SB6190Driver


# -- Sample HTML from SB6190 HAR capture --

SAMPLE_STATUS_HTML = """
<!DOCTYPE html>
<html>
<head><title>Arris SB6190</title></head>
<body>
<table border="1" cellpadding="4" cellspacing="0">
  <tr><th colspan="9"><strong>Downstream Bonded Channels</strong></th></tr>
  <tr>
    <th>Channel</th><th>Lock Status</th><th>Modulation</th><th>Channel ID</th>
    <th>Frequency</th><th>Power</th><th>SNR</th><th>Corrected</th><th>Uncorrectables</th>
  </tr>
  <tr><td>1</td><td> Locked </td><td>256QAM</td><td>13</td><td>807.00 MHz</td><td>10.50 dBmV</td><td>40.95 dB</td><td>33</td><td>0</td></tr>
  <tr><td>2</td><td> Locked </td><td>256QAM</td><td>1</td><td>651.00 MHz</td><td>9.80 dBmV</td><td>40.55 dB</td><td>12</td><td>0</td></tr>
  <tr><td>3</td><td> Locked </td><td>256QAM</td><td>2</td><td>657.00 MHz</td><td>9.90 dBmV</td><td>40.64 dB</td><td>5</td><td>0</td></tr>
  <tr><td>4</td><td> Locked </td><td>256QAM</td><td>3</td><td>663.00 MHz</td><td>9.90 dBmV</td><td>40.65 dB</td><td>8</td><td>0</td></tr>
  <tr><td>5</td><td> Locked </td><td>256QAM</td><td>4</td><td>669.00 MHz</td><td>9.90 dBmV</td><td>40.70 dB</td><td>7</td><td>0</td></tr>
  <tr><td>6</td><td> Locked </td><td>256QAM</td><td>5</td><td>675.00 MHz</td><td>10.10 dBmV</td><td>40.80 dB</td><td>4</td><td>0</td></tr>
  <tr><td>7</td><td> Locked </td><td>256QAM</td><td>6</td><td>681.00 MHz</td><td>10.20 dBmV</td><td>40.83 dB</td><td>3</td><td>0</td></tr>
  <tr><td>8</td><td> Locked </td><td>256QAM</td><td>7</td><td>687.00 MHz</td><td>10.30 dBmV</td><td>40.88 dB</td><td>2</td><td>0</td></tr>
  <tr><td>9</td><td> Locked </td><td>256QAM</td><td>8</td><td>693.00 MHz</td><td>10.40 dBmV</td><td>40.90 dB</td><td>1</td><td>0</td></tr>
  <tr><td>10</td><td> Locked </td><td>256QAM</td><td>9</td><td>699.00 MHz</td><td>10.50 dBmV</td><td>40.95 dB</td><td>0</td><td>0</td></tr>
  <tr><td>11</td><td> Locked </td><td>256QAM</td><td>10</td><td>705.00 MHz</td><td>10.60 dBmV</td><td>41.00 dB</td><td>0</td><td>0</td></tr>
  <tr><td>12</td><td> Locked </td><td>256QAM</td><td>11</td><td>711.00 MHz</td><td>10.70 dBmV</td><td>41.05 dB</td><td>0</td><td>0</td></tr>
  <tr><td>13</td><td> Locked </td><td>256QAM</td><td>12</td><td>717.00 MHz</td><td>10.80 dBmV</td><td>41.10 dB</td><td>0</td><td>0</td></tr>
  <tr><td>14</td><td> Locked </td><td>256QAM</td><td>14</td><td>723.00 MHz</td><td>10.90 dBmV</td><td>41.15 dB</td><td>0</td><td>0</td></tr>
  <tr><td>15</td><td> Locked </td><td>256QAM</td><td>15</td><td>729.00 MHz</td><td>11.00 dBmV</td><td>41.20 dB</td><td>0</td><td>0</td></tr>
  <tr><td>16</td><td> Locked </td><td>256QAM</td><td>16</td><td>735.00 MHz</td><td>11.10 dBmV</td><td>41.25 dB</td><td>0</td><td>0</td></tr>
  <tr><td>17</td><td> Locked </td><td>256QAM</td><td>17</td><td>741.00 MHz</td><td>11.20 dBmV</td><td>41.30 dB</td><td>0</td><td>0</td></tr>
  <tr><td>18</td><td> Locked </td><td>256QAM</td><td>18</td><td>747.00 MHz</td><td>11.30 dBmV</td><td>41.35 dB</td><td>0</td><td>0</td></tr>
  <tr><td>19</td><td> Locked </td><td>256QAM</td><td>19</td><td>753.00 MHz</td><td>11.40 dBmV</td><td>41.40 dB</td><td>0</td><td>0</td></tr>
  <tr><td>20</td><td> Locked </td><td>256QAM</td><td>20</td><td>759.00 MHz</td><td>11.50 dBmV</td><td>41.45 dB</td><td>0</td><td>0</td></tr>
  <tr><td>21</td><td> Locked </td><td>256QAM</td><td>21</td><td>765.00 MHz</td><td>11.60 dBmV</td><td>41.50 dB</td><td>0</td><td>0</td></tr>
  <tr><td>22</td><td> Locked </td><td>256QAM</td><td>22</td><td>771.00 MHz</td><td>11.70 dBmV</td><td>41.55 dB</td><td>0</td><td>0</td></tr>
  <tr><td>23</td><td> Locked </td><td>256QAM</td><td>23</td><td>777.00 MHz</td><td>11.80 dBmV</td><td>41.60 dB</td><td>0</td><td>0</td></tr>
  <tr><td>24</td><td> Locked </td><td>256QAM</td><td>24</td><td>783.00 MHz</td><td>11.90 dBmV</td><td>41.65 dB</td><td>0</td><td>0</td></tr>
  <tr><td>25</td><td> Locked </td><td>256QAM</td><td>25</td><td>789.00 MHz</td><td>12.00 dBmV</td><td>41.70 dB</td><td>0</td><td>0</td></tr>
  <tr><td>26</td><td> Locked </td><td>256QAM</td><td>26</td><td>795.00 MHz</td><td>12.10 dBmV</td><td>41.75 dB</td><td>0</td><td>0</td></tr>
  <tr><td>27</td><td> Locked </td><td>256QAM</td><td>27</td><td>801.00 MHz</td><td>12.20 dBmV</td><td>41.80 dB</td><td>0</td><td>0</td></tr>
  <tr><td>28</td><td> Locked </td><td>256QAM</td><td>28</td><td>813.00 MHz</td><td>12.30 dBmV</td><td>41.85 dB</td><td>0</td><td>0</td></tr>
  <tr><td>29</td><td> Locked </td><td>256QAM</td><td>29</td><td>819.00 MHz</td><td>12.40 dBmV</td><td>41.90 dB</td><td>0</td><td>0</td></tr>
  <tr><td>30</td><td> Locked </td><td>256QAM</td><td>30</td><td>825.00 MHz</td><td>12.50 dBmV</td><td>41.95 dB</td><td>0</td><td>0</td></tr>
  <tr><td>31</td><td> Locked </td><td>256QAM</td><td>31</td><td>831.00 MHz</td><td>12.60 dBmV</td><td>42.00 dB</td><td>0</td><td>0</td></tr>
  <tr><td>32</td><td> Locked </td><td>256QAM</td><td>32</td><td>837.00 MHz</td><td>12.70 dBmV</td><td>42.05 dB</td><td>0</td><td>0</td></tr>
</table>

<table border="1" cellpadding="4" cellspacing="0">
  <tr><th colspan="7"><strong>Upstream Bonded Channels</strong></th></tr>
  <tr>
    <th>Channel</th><th>Lock Status</th><th>US Channel Type</th><th>Channel ID</th>
    <th>Symbol Rate</th><th>Frequency</th><th>Power</th>
  </tr>
  <tr><td>1</td><td> Locked </td><td>ATDMA</td><td>1</td><td>5120 kSym/s</td><td>17.60 MHz</td><td>35.00 dBmV</td></tr>
  <tr><td>2</td><td> Locked </td><td>ATDMA</td><td>2</td><td>5120 kSym/s</td><td>23.60 MHz</td><td>35.25 dBmV</td></tr>
  <tr><td>3</td><td> Locked </td><td>ATDMA</td><td>3</td><td>5120 kSym/s</td><td>29.70 MHz</td><td>35.50 dBmV</td></tr>
  <tr><td>4</td><td> Locked </td><td>ATDMA</td><td>4</td><td>5120 kSym/s</td><td>35.70 MHz</td><td>35.75 dBmV</td></tr>
</table>
</body>
</html>
"""

SAMPLE_SWINFO_HTML = """
<!DOCTYPE html>
<html>
<head><title>Arris SB6190</title></head>
<body>
<table border="0" cellpadding="4" cellspacing="0">
  <tr><td><strong>Software Version</strong></td><td>9.1.103AA72</td></tr>
  <tr><td><strong>Hardware Version</strong></td><td>3</td></tr>
  <tr><td><strong>Boot Version</strong></td><td>PSPU-Boot 2.0.6</td></tr>
  <tr><td><strong>Serial Number</strong></td><td>ABX12345</td></tr>
</table>
</body>
</html>
"""


@pytest.fixture
def driver():
    return SB6190Driver("https://192.168.100.1", "admin", "password")


@pytest.fixture
def mock_status(driver):
    """Patch session.get to return sample status HTML."""
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.text = SAMPLE_STATUS_HTML

    with patch.object(driver._session, "get", return_value=mock_response):
        yield driver


# -- Driver instantiation --

class TestDriverInit:
    def test_stores_url(self):
        d = SB6190Driver("https://192.168.100.1", "admin", "pass")
        assert d._url == "https://192.168.100.1"

    def test_stores_credentials(self):
        d = SB6190Driver("https://192.168.100.1", "admin", "secret")
        assert d._user == "admin"
        assert d._password == "secret"

    def test_ssl_verify_disabled(self):
        d = SB6190Driver("https://192.168.100.1", "admin", "pass")
        assert d._session.verify is False

    def test_load_via_registry(self):
        from app.drivers import load_driver
        d = load_driver("sb6190", "https://192.168.100.1", "admin", "pass")
        assert isinstance(d, SB6190Driver)


# -- Login --

class TestLogin:
    def test_login_posts_to_correct_url(self, driver):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "Url:status"

        with patch.object(driver._session, "post", return_value=mock_resp) as mock_post:
            driver.login()
            url = mock_post.call_args[0][0]
            assert "/cgi-bin/adv_pwd_cgi" in url

    def test_login_sends_arguments_and_nonce(self, driver):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "Url:status"

        with patch.object(driver._session, "post", return_value=mock_resp) as mock_post:
            driver.login()
            data = mock_post.call_args[1]["data"]
            assert "arguments" in data
            assert "ar_nonce" in data
            assert len(data["ar_nonce"]) == 8

    def test_login_raises_on_error_body(self, driver):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "Error: Invalid credentials"

        with patch.object(driver._session, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="SB6190 login rejected"):
                driver.login()

    def test_login_raises_on_connection_error(self, driver):
        with patch.object(driver._session, "post", side_effect=requests.ConnectionError("refused")):
            with pytest.raises(RuntimeError, match="SB6190 login failed"):
                driver.login()

    def test_login_raises_on_http_error(self, driver):
        mock_resp = MagicMock()
        mock_resp.raise_for_status.side_effect = requests.HTTPError("503")
        mock_resp.text = ""

        with patch.object(driver._session, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="SB6190 login failed"):
                driver.login()

    def test_login_raises_when_no_url_in_response(self, driver):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "OK"

        with patch.object(driver._session, "post", return_value=mock_resp):
            with pytest.raises(RuntimeError, match="unexpected response"):
                driver.login()


# -- Downstream --

class TestDownstream:
    def test_channel_count(self, mock_status):
        data = mock_status.get_docsis_data()
        assert len(data["channelDs"]["docsis30"]) == 32

    def test_docsis31_empty(self, mock_status):
        data = mock_status.get_docsis_data()
        assert data["channelDs"]["docsis31"] == []

    def test_first_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelDs"]["docsis30"][0]
        assert ch["channelID"] == 13
        assert ch["frequency"] == "807 MHz"
        assert ch["powerLevel"] == 10.50
        assert ch["mer"] == 40.95
        assert ch["mse"] == pytest.approx(-40.95)
        assert ch["modulation"] == "256QAM"
        assert ch["corrErrors"] == 33
        assert ch["nonCorrErrors"] == 0

    def test_second_channel_id(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelDs"]["docsis30"][1]
        assert ch["channelID"] == 1
        assert ch["frequency"] == "651 MHz"

    def test_last_channel(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelDs"]["docsis30"][-1]
        assert ch["channelID"] == 32
        assert ch["frequency"] == "837 MHz"

    def test_all_channels_have_required_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        for ch in data["channelDs"]["docsis30"]:
            assert "channelID" in ch
            assert "frequency" in ch
            assert "powerLevel" in ch
            assert "mer" in ch
            assert "modulation" in ch
            assert "corrErrors" in ch
            assert "nonCorrErrors" in ch


# -- Upstream --

class TestUpstream:
    def test_channel_count(self, mock_status):
        data = mock_status.get_docsis_data()
        assert len(data["channelUs"]["docsis30"]) == 4

    def test_docsis31_empty(self, mock_status):
        data = mock_status.get_docsis_data()
        assert data["channelUs"]["docsis31"] == []

    def test_first_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelUs"]["docsis30"][0]
        assert ch["channelID"] == 1
        assert ch["frequency"] == "17.6 MHz"
        assert ch["powerLevel"] == 35.00
        assert ch["modulation"] == "ATDMA"
        assert ch["multiplex"] == "ATDMA"

    def test_second_channel(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelUs"]["docsis30"][1]
        assert ch["channelID"] == 2
        assert ch["frequency"] == "23.6 MHz"

    def test_all_channels_have_required_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        for ch in data["channelUs"]["docsis30"]:
            assert "channelID" in ch
            assert "frequency" in ch
            assert "powerLevel" in ch
            assert "modulation" in ch
            assert "multiplex" in ch


# -- Device info --

class TestDeviceInfo:
    def test_parses_swinfo_page(self, driver):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = SAMPLE_SWINFO_HTML

        with patch.object(driver._session, "get", return_value=mock_resp):
            info = driver.get_device_info()

        assert info["manufacturer"] == "Arris"
        assert info["model"] == "SB6190"
        assert info["sw_version"] == "9.1.103AA72"

    def test_fallback_on_connection_error(self, driver):
        with patch.object(driver._session, "get", side_effect=requests.ConnectionError()):
            info = driver.get_device_info()
            assert info["manufacturer"] == "Arris"
            assert info["model"] == "SB6190"
            assert info["sw_version"] == ""

    def test_connection_info_empty(self, driver):
        assert driver.get_connection_info() == {}


# -- Value helpers --

class TestValueHelpers:
    def test_normalize_mhz_integer(self):
        assert SB6190Driver._normalize_mhz("807.00 MHz") == "807 MHz"

    def test_normalize_mhz_decimal(self):
        assert SB6190Driver._normalize_mhz("17.60 MHz") == "17.6 MHz"

    def test_normalize_mhz_already_integer(self):
        assert SB6190Driver._normalize_mhz("100 MHz") == "100 MHz"

    def test_normalize_mhz_invalid(self):
        assert SB6190Driver._normalize_mhz("unknown") == "unknown"

    def test_parse_number_dbmv(self):
        assert SB6190Driver._parse_number("10.50 dBmV") == 10.50

    def test_parse_number_db(self):
        assert SB6190Driver._parse_number("40.95 dB") == 40.95

    def test_parse_number_integer(self):
        assert SB6190Driver._parse_number("33") == 33.0

    def test_parse_number_empty(self):
        assert SB6190Driver._parse_number("") == 0.0

    def test_parse_number_invalid(self):
        assert SB6190Driver._parse_number("Locked") == 0.0


# -- Edge cases --

class TestEdgeCases:
    def test_no_tables(self, driver):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = "<html><body></body></html>"

        with patch.object(driver._session, "get", return_value=mock_resp):
            data = driver.get_docsis_data()
            assert data["channelDs"]["docsis30"] == []
            assert data["channelUs"]["docsis30"] == []

    def test_empty_html(self, driver):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = ""

        with patch.object(driver._session, "get", return_value=mock_resp):
            data = driver.get_docsis_data()
            assert data["channelDs"]["docsis30"] == []
            assert data["channelUs"]["docsis30"] == []

    def test_get_docsis_data_raises_on_connection_error(self, driver):
        with patch.object(driver._session, "get", side_effect=requests.ConnectionError("refused")):
            with pytest.raises(RuntimeError, match="SB6190 DOCSIS data retrieval failed"):
                driver.get_docsis_data()

    def test_unlocked_downstream_channels_excluded(self, driver):
        html = """<html><body>
        <table>
          <tr><th colspan="9"><strong>Downstream Bonded Channels</strong></th></tr>
          <tr><td>1</td><td>Locked</td><td>256QAM</td><td>1</td><td>651.00 MHz</td><td>9.80 dBmV</td><td>40.55 dB</td><td>12</td><td>0</td></tr>
          <tr><td>2</td><td>Not Locked</td><td>256QAM</td><td>2</td><td>657.00 MHz</td><td>9.90 dBmV</td><td>40.64 dB</td><td>5</td><td>0</td></tr>
        </table>
        </body></html>"""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = html

        with patch.object(driver._session, "get", return_value=mock_resp):
            data = driver.get_docsis_data()
            assert len(data["channelDs"]["docsis30"]) == 1
            assert data["channelDs"]["docsis30"][0]["channelID"] == 1

    def test_unlocked_upstream_channels_excluded(self, driver):
        html = """<html><body>
        <table>
          <tr><th colspan="7"><strong>Upstream Bonded Channels</strong></th></tr>
          <tr><td>1</td><td>Locked</td><td>ATDMA</td><td>1</td><td>5120 kSym/s</td><td>17.60 MHz</td><td>35.00 dBmV</td></tr>
          <tr><td>2</td><td>Not Locked</td><td>ATDMA</td><td>2</td><td>5120 kSym/s</td><td>23.60 MHz</td><td>35.25 dBmV</td></tr>
        </table>
        </body></html>"""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = html

        with patch.object(driver._session, "get", return_value=mock_resp):
            data = driver.get_docsis_data()
            assert len(data["channelUs"]["docsis30"]) == 1
            assert data["channelUs"]["docsis30"][0]["channelID"] == 1

    def test_short_rows_skipped(self, driver):
        """Rows with fewer than 9 DS cells or 7 US cells are skipped."""
        html = """<html><body>
        <table>
          <tr><th colspan="9"><strong>Downstream Bonded Channels</strong></th></tr>
          <tr><td>1</td><td>Locked</td><td>256QAM</td></tr>
        </table>
        </body></html>"""
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.text = html

        with patch.object(driver._session, "get", return_value=mock_resp):
            data = driver.get_docsis_data()
            assert data["channelDs"]["docsis30"] == []


# -- Analyzer integration --

class TestAnalyzerIntegration:
    def test_full_pipeline(self, mock_status):
        from app.analyzer import analyze
        data = mock_status.get_docsis_data()
        result = analyze(data)

        assert result["summary"]["ds_total"] == 32
        assert result["summary"]["us_total"] == 4
        assert result["summary"]["health"] in ("good", "tolerated", "marginal", "poor", "critical")
        assert len(result["ds_channels"]) == 32
        assert len(result["us_channels"]) == 4

    def test_all_channels_labeled_docsis30(self, mock_status):
        from app.analyzer import analyze
        data = mock_status.get_docsis_data()
        result = analyze(data)

        for ch in result["ds_channels"]:
            assert ch["docsis_version"] == "3.0"
        for ch in result["us_channels"]:
            assert ch["docsis_version"] == "3.0"
