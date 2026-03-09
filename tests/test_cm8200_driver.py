"""Tests for Arris Touchstone CM8200A modem driver."""

import base64

import pytest
from unittest.mock import patch, MagicMock
from app.drivers.cm8200 import CM8200Driver


# -- Sample HTML from CM8200A HAR capture --

SAMPLE_STATUS_HTML = """
<html>
<body>
<span id="thisModelNumberIs">CM8200A</span>

<table class="simpleTable">
<tr><th colspan="8">Downstream Bonded Channels</th></tr>
<tr>
<td>Channel ID</td><td>Lock Status</td><td>Modulation</td><td>Frequency</td>
<td>Power</td><td>SNR/MER</td><td>Corrected</td><td>Uncorrectables</td>
</tr>
<tr><td>33</td><td>Locked</td><td>Other</td><td>795000000 Hz</td><td>8.2 dBmV</td><td>43.0 dB</td><td>191405078</td><td>0</td></tr>
<tr><td>1</td><td>Locked</td><td>QAM256</td><td>561000000 Hz</td><td>4.9 dBmV</td><td>43.4 dB</td><td>17</td><td>0</td></tr>
<tr><td>2</td><td>Locked</td><td>QAM256</td><td>567000000 Hz</td><td>4.5 dBmV</td><td>43.0 dB</td><td>10</td><td>0</td></tr>
<tr><td>3</td><td>Locked</td><td>QAM256</td><td>573000000 Hz</td><td>4.2 dBmV</td><td>42.8 dB</td><td>8</td><td>0</td></tr>
<tr><td>4</td><td>Locked</td><td>QAM256</td><td>579000000 Hz</td><td>3.9 dBmV</td><td>42.5 dB</td><td>5</td><td>1</td></tr>
<tr><td>5</td><td>Locked</td><td>QAM256</td><td>585000000 Hz</td><td>3.7 dBmV</td><td>42.3 dB</td><td>3</td><td>0</td></tr>
<tr><td>6</td><td>Locked</td><td>QAM256</td><td>591000000 Hz</td><td>3.5 dBmV</td><td>42.1 dB</td><td>2</td><td>0</td></tr>
<tr><td>7</td><td>Locked</td><td>QAM256</td><td>597000000 Hz</td><td>3.3 dBmV</td><td>41.9 dB</td><td>1</td><td>0</td></tr>
<tr><td>8</td><td>Locked</td><td>QAM256</td><td>603000000 Hz</td><td>3.1 dBmV</td><td>41.7 dB</td><td>0</td><td>0</td></tr>
<tr><td>9</td><td>Locked</td><td>QAM256</td><td>609000000 Hz</td><td>3.0 dBmV</td><td>41.5 dB</td><td>0</td><td>0</td></tr>
<tr><td>10</td><td>Locked</td><td>QAM256</td><td>615000000 Hz</td><td>2.9 dBmV</td><td>41.3 dB</td><td>0</td><td>0</td></tr>
<tr><td>11</td><td>Locked</td><td>QAM256</td><td>621000000 Hz</td><td>2.8 dBmV</td><td>41.1 dB</td><td>0</td><td>0</td></tr>
<tr><td>12</td><td>Locked</td><td>QAM256</td><td>627000000 Hz</td><td>2.7 dBmV</td><td>40.9 dB</td><td>0</td><td>0</td></tr>
<tr><td>13</td><td>Locked</td><td>QAM256</td><td>633000000 Hz</td><td>2.6 dBmV</td><td>40.7 dB</td><td>0</td><td>0</td></tr>
<tr><td>14</td><td>Locked</td><td>QAM256</td><td>639000000 Hz</td><td>2.5 dBmV</td><td>40.5 dB</td><td>0</td><td>0</td></tr>
<tr><td>15</td><td>Locked</td><td>QAM256</td><td>645000000 Hz</td><td>2.4 dBmV</td><td>40.3 dB</td><td>0</td><td>0</td></tr>
<tr><td>16</td><td>Locked</td><td>QAM256</td><td>651000000 Hz</td><td>2.3 dBmV</td><td>40.1 dB</td><td>0</td><td>0</td></tr>
<tr><td>17</td><td>Locked</td><td>QAM256</td><td>657000000 Hz</td><td>2.2 dBmV</td><td>39.9 dB</td><td>0</td><td>0</td></tr>
<tr><td>18</td><td>Locked</td><td>QAM256</td><td>663000000 Hz</td><td>2.1 dBmV</td><td>39.7 dB</td><td>0</td><td>0</td></tr>
<tr><td>19</td><td>Locked</td><td>QAM256</td><td>669000000 Hz</td><td>2.0 dBmV</td><td>39.5 dB</td><td>0</td><td>0</td></tr>
<tr><td>20</td><td>Locked</td><td>QAM256</td><td>675000000 Hz</td><td>1.9 dBmV</td><td>39.3 dB</td><td>0</td><td>0</td></tr>
<tr><td>21</td><td>Locked</td><td>QAM256</td><td>681000000 Hz</td><td>1.8 dBmV</td><td>39.1 dB</td><td>0</td><td>0</td></tr>
<tr><td>22</td><td>Locked</td><td>QAM256</td><td>687000000 Hz</td><td>1.7 dBmV</td><td>38.9 dB</td><td>0</td><td>0</td></tr>
<tr><td>23</td><td>Locked</td><td>QAM256</td><td>693000000 Hz</td><td>1.6 dBmV</td><td>38.7 dB</td><td>0</td><td>0</td></tr>
<tr><td>24</td><td>Locked</td><td>QAM256</td><td>699000000 Hz</td><td>1.5 dBmV</td><td>38.5 dB</td><td>0</td><td>0</td></tr>
<tr><td>25</td><td>Locked</td><td>QAM256</td><td>705000000 Hz</td><td>1.4 dBmV</td><td>38.3 dB</td><td>0</td><td>0</td></tr>
<tr><td>26</td><td>Locked</td><td>QAM256</td><td>711000000 Hz</td><td>1.3 dBmV</td><td>38.1 dB</td><td>0</td><td>0</td></tr>
<tr><td>27</td><td>Locked</td><td>QAM256</td><td>717000000 Hz</td><td>1.2 dBmV</td><td>37.9 dB</td><td>0</td><td>0</td></tr>
<tr><td>28</td><td>Locked</td><td>QAM256</td><td>723000000 Hz</td><td>1.1 dBmV</td><td>37.7 dB</td><td>0</td><td>0</td></tr>
<tr><td>29</td><td>Locked</td><td>QAM256</td><td>729000000 Hz</td><td>1.0 dBmV</td><td>37.5 dB</td><td>0</td><td>0</td></tr>
<tr><td>30</td><td>Locked</td><td>QAM256</td><td>735000000 Hz</td><td>0.9 dBmV</td><td>37.3 dB</td><td>0</td><td>0</td></tr>
<tr><td>31</td><td>Locked</td><td>QAM256</td><td>741000000 Hz</td><td>0.8 dBmV</td><td>37.1 dB</td><td>0</td><td>0</td></tr>
<tr><td>32</td><td>Locked</td><td>QAM256</td><td>747000000 Hz</td><td>0.7 dBmV</td><td>36.9 dB</td><td>0</td><td>0</td></tr>
</table>

<table class="simpleTable">
<tr><th colspan="7">Upstream Bonded Channels</th></tr>
<tr>
<td>Channel</td><td>Channel ID</td><td>Lock Status</td><td>US Channel Type</td>
<td>Frequency</td><td>Width</td><td>Power</td>
</tr>
<tr><td>1</td><td>3</td><td>Locked</td><td>SC-QAM Upstream</td><td>15500000 Hz</td><td>3200000 Hz</td><td>48.0 dBmV</td></tr>
<tr><td>2</td><td>4</td><td>Locked</td><td>SC-QAM Upstream</td><td>22100000 Hz</td><td>6400000 Hz</td><td>47.0 dBmV</td></tr>
<tr><td>3</td><td>5</td><td>Locked</td><td>SC-QAM Upstream</td><td>28700000 Hz</td><td>6400000 Hz</td><td>46.5 dBmV</td></tr>
<tr><td>4</td><td>24</td><td>Locked</td><td>OFDM Upstream</td><td>26525000 Hz</td><td>11000000 Hz</td><td>47.0 dBmV</td></tr>
</table>

</body>
</html>
"""


@pytest.fixture
def driver():
    return CM8200Driver("https://192.168.100.1", "admin", "password")


@pytest.fixture
def mock_status(driver):
    """Patch _fetch_status_page to return sample HTML."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(SAMPLE_STATUS_HTML, "html.parser")
    with patch.object(driver, "_fetch_status_page", return_value=soup):
        yield driver


# -- Driver instantiation --

class TestDriverInit:
    def test_stores_credentials(self):
        d = CM8200Driver("https://192.168.100.1", "admin", "pass123")
        assert d._url == "https://192.168.100.1"
        assert d._user == "admin"
        assert d._password == "pass123"

    def test_https_upgrade(self):
        d = CM8200Driver("http://192.168.100.1", "admin", "pass")
        assert d._url == "https://192.168.100.1"

    def test_https_preserved(self):
        d = CM8200Driver("https://10.0.0.1", "admin", "pass")
        assert d._url == "https://10.0.0.1"

    def test_ssl_verify_disabled(self):
        d = CM8200Driver("https://192.168.100.1", "admin", "pass")
        assert d._session.verify is False

    def test_load_via_registry(self):
        from app.drivers import load_driver
        d = load_driver("cm8200", "https://192.168.100.1", "admin", "pass")
        assert isinstance(d, CM8200Driver)


# -- Login --

class TestLogin:
    def test_two_step_auth_flow(self, driver):
        """Login sends two GETs: first with credentials (returns token), then with cookie."""
        expected_creds = base64.b64encode(b"admin:password").decode()

        token_response = MagicMock()
        token_response.raise_for_status = MagicMock()
        token_response.text = "abc123sessiontoken"

        status_response = MagicMock()
        status_response.raise_for_status = MagicMock()
        status_response.text = SAMPLE_STATUS_HTML

        with patch.object(driver._session, "get", side_effect=[token_response, status_response]) as mock_get:
            driver.login()

            assert mock_get.call_count == 2
            # First call: with credentials in query string
            url1 = mock_get.call_args_list[0][0][0]
            assert f"?{expected_creds}" in url1
            # Second call: bare GET with Cookie header
            url2 = mock_get.call_args_list[1][0][0]
            assert url2.endswith("/cmconnectionstatus.html")
            assert "?" not in url2
            cookie = mock_get.call_args_list[1][1]["headers"]["Cookie"]
            assert "credential=abc123sessiontoken" in cookie

    def test_login_retries_on_connection_error(self, driver):
        import requests as req

        token_response = MagicMock()
        token_response.raise_for_status = MagicMock()
        token_response.text = "abc123token"

        status_response = MagicMock()
        status_response.raise_for_status = MagicMock()
        status_response.text = SAMPLE_STATUS_HTML

        call_count = []

        def side_effect(*args, **kwargs):
            call_count.append(1)
            if len(call_count) == 1:
                raise req.ConnectionError("reset")
            return token_response

        with patch("requests.Session") as MockSession:
            mock_new_session = MagicMock()
            mock_new_session.get = MagicMock(side_effect=[token_response, status_response])
            mock_new_session.verify = False
            MockSession.return_value = mock_new_session

            with patch.object(driver._session, "get", side_effect=side_effect):
                driver.login()

        assert len(call_count) == 1
        # Retry uses fresh session: 2 GETs (auth + status)
        assert mock_new_session.get.call_count == 2

    def test_login_raises_after_retry_exhausted(self, driver):
        import requests as req

        with patch("requests.Session") as MockSession:
            mock_new_session = MagicMock()
            mock_new_session.get = MagicMock(side_effect=req.ConnectionError("down"))
            MockSession.return_value = mock_new_session

            with patch.object(driver._session, "get", side_effect=req.ConnectionError("down")):
                with pytest.raises(RuntimeError, match="connection refused after retry"):
                    driver.login()

    def test_login_raises_on_http_error(self, driver):
        import requests as req

        with patch.object(driver._session, "get", side_effect=req.HTTPError("401")):
            with pytest.raises(RuntimeError, match="CM8200 authentication failed"):
                driver.login()

    def test_login_caches_status_html(self, driver):
        """Login caches the second response (status page) for reuse."""
        auth_response = MagicMock()
        auth_response.text = "1"  # session token

        status_response = MagicMock()
        status_response.raise_for_status = MagicMock()
        status_response.text = SAMPLE_STATUS_HTML

        with patch.object(driver._session, "get", side_effect=[auth_response, status_response]):
            driver.login()

        assert driver._status_html == SAMPLE_STATUS_HTML


# -- Downstream QAM --

class TestDownstreamQAM:
    def test_channel_count(self, mock_status):
        data = mock_status.get_docsis_data()
        assert len(data["channelDs"]["docsis30"]) == 32

    def test_first_qam_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelDs"]["docsis30"][0]
        assert ch["channelID"] == 1
        assert ch["frequency"] == "561 MHz"
        assert ch["powerLevel"] == 4.9
        assert ch["mer"] == 43.4
        assert ch["mse"] == -43.4
        assert ch["modulation"] == "QAM256"
        assert ch["corrErrors"] == 17
        assert ch["nonCorrErrors"] == 0

    def test_frequency_conversion(self, mock_status):
        """Hz values are converted to MHz strings."""
        data = mock_status.get_docsis_data()
        freqs = [ch["frequency"] for ch in data["channelDs"]["docsis30"]]
        assert all("MHz" in f for f in freqs)
        assert freqs[0] == "561 MHz"

    def test_last_qam_channel(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelDs"]["docsis30"][-1]
        assert ch["channelID"] == 32
        assert ch["frequency"] == "747 MHz"
        assert ch["powerLevel"] == 0.7

    def test_channel_with_uncorrectables(self, mock_status):
        """Channel 4 has 1 uncorrectable error."""
        data = mock_status.get_docsis_data()
        ch4 = [c for c in data["channelDs"]["docsis30"] if c["channelID"] == 4][0]
        assert ch4["nonCorrErrors"] == 1
        assert ch4["corrErrors"] == 5


# -- Downstream OFDM --

class TestDownstreamOFDM:
    def test_ofdm_in_docsis31(self, mock_status):
        data = mock_status.get_docsis_data()
        assert len(data["channelDs"]["docsis31"]) == 1

    def test_ofdm_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelDs"]["docsis31"][0]
        assert ch["channelID"] == 33
        assert ch["type"] == "OFDM"
        assert ch["frequency"] == "795 MHz"
        assert ch["powerLevel"] == 8.2
        assert ch["mer"] == 43.0
        assert ch["mse"] is None
        assert ch["modulation"] == "Other"
        assert ch["corrErrors"] == 191405078
        assert ch["nonCorrErrors"] == 0


# -- Upstream SC-QAM --

class TestUpstreamSCQAM:
    def test_locked_count(self, mock_status):
        data = mock_status.get_docsis_data()
        assert len(data["channelUs"]["docsis30"]) == 3

    def test_first_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelUs"]["docsis30"][0]
        assert ch["channelID"] == 3
        assert ch["frequency"] == "15.5 MHz"
        assert ch["powerLevel"] == 48.0
        assert ch["modulation"] == "SC-QAM Upstream"
        assert ch["multiplex"] == "SC-QAM"

    def test_all_upstream_scqam_ids(self, mock_status):
        data = mock_status.get_docsis_data()
        ids = [ch["channelID"] for ch in data["channelUs"]["docsis30"]]
        assert ids == [3, 4, 5]


# -- Upstream OFDMA --

class TestUpstreamOFDMA:
    def test_ofdma_in_docsis31(self, mock_status):
        data = mock_status.get_docsis_data()
        assert len(data["channelUs"]["docsis31"]) == 1

    def test_ofdma_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelUs"]["docsis31"][0]
        assert ch["channelID"] == 24
        assert ch["type"] == "OFDMA"
        assert ch["frequency"] == "26.5 MHz"
        assert ch["powerLevel"] == 47.0
        assert ch["modulation"] == "OFDM Upstream"
        assert ch["multiplex"] == ""


# -- Device info --

class TestDeviceInfo:
    def test_model_from_span(self, mock_status):
        info = mock_status.get_device_info()
        assert info["manufacturer"] == "Arris"
        assert info["model"] == "CM8200A"

    def test_connection_info_empty(self, driver):
        assert driver.get_connection_info() == {}

    def test_device_info_fallback_on_error(self, driver):
        with patch.object(driver, "_fetch_status_page", side_effect=Exception("network")):
            info = driver.get_device_info()
            assert info["manufacturer"] == "Arris"
            assert info["model"] == "CM8200A"


# -- Value helpers --

class TestValueHelpers:
    def test_parse_freq_hz_integer_mhz(self):
        assert CM8200Driver._parse_freq_hz("795000000 Hz") == "795 MHz"

    def test_parse_freq_hz_decimal_mhz(self):
        assert CM8200Driver._parse_freq_hz("15500000 Hz") == "15.5 MHz"

    def test_parse_freq_hz_empty(self):
        assert CM8200Driver._parse_freq_hz("") == ""

    def test_parse_freq_hz_zero(self):
        assert CM8200Driver._parse_freq_hz("0 Hz") == "0 MHz"

    def test_parse_value_dbmv(self):
        assert CM8200Driver._parse_value("8.2 dBmV") == 8.2

    def test_parse_value_db(self):
        assert CM8200Driver._parse_value("43.0 dB") == 43.0

    def test_parse_value_empty(self):
        assert CM8200Driver._parse_value("") is None

    def test_parse_value_none(self):
        assert CM8200Driver._parse_value(None) is None


# -- Edge cases --

class TestEdgeCases:
    def test_empty_tables(self, driver):
        from bs4 import BeautifulSoup
        html = "<html><body></body></html>"
        soup = BeautifulSoup(html, "html.parser")
        with patch.object(driver, "_fetch_status_page", return_value=soup):
            data = driver.get_docsis_data()
            assert data["channelDs"]["docsis30"] == []
            assert data["channelDs"]["docsis31"] == []
            assert data["channelUs"]["docsis30"] == []
            assert data["channelUs"]["docsis31"] == []

    def test_unlocked_channels_skipped(self, driver):
        from bs4 import BeautifulSoup
        html = """<html><body>
        <table class="simpleTable">
        <tr><th colspan="8">Downstream Bonded Channels</th></tr>
        <tr><td>Channel ID</td><td>Lock Status</td><td>Modulation</td><td>Frequency</td>
        <td>Power</td><td>SNR/MER</td><td>Corrected</td><td>Uncorrectables</td></tr>
        <tr><td>1</td><td>Not Locked</td><td>QAM256</td><td>561000000 Hz</td><td>4.9 dBmV</td><td>43.4 dB</td><td>0</td><td>0</td></tr>
        <tr><td>2</td><td>Locked</td><td>QAM256</td><td>567000000 Hz</td><td>4.5 dBmV</td><td>43.0 dB</td><td>0</td><td>0</td></tr>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        with patch.object(driver, "_fetch_status_page", return_value=soup):
            data = driver.get_docsis_data()
            assert len(data["channelDs"]["docsis30"]) == 1
            assert data["channelDs"]["docsis30"][0]["channelID"] == 2

    def test_malformed_rows_skipped(self, driver):
        from bs4 import BeautifulSoup
        html = """<html><body>
        <table class="simpleTable">
        <tr><th colspan="8">Downstream Bonded Channels</th></tr>
        <tr><td>Channel ID</td><td>Lock Status</td><td>Modulation</td><td>Frequency</td>
        <td>Power</td><td>SNR/MER</td><td>Corrected</td><td>Uncorrectables</td></tr>
        <tr><td>1</td><td>Locked</td><td>QAM256</td></tr>
        <tr><td>2</td><td>Locked</td><td>QAM256</td><td>567000000 Hz</td><td>4.5 dBmV</td><td>43.0 dB</td><td>0</td><td>0</td></tr>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        with patch.object(driver, "_fetch_status_page", return_value=soup):
            data = driver.get_docsis_data()
            assert len(data["channelDs"]["docsis30"]) == 1

    def test_missing_tr_on_column_headers(self, driver):
        """Real CM8200 HTML has no <tr> before column-header <td>s.

        BeautifulSoup merges the orphaned <td>s into the first data row,
        so the column-header row disappears and data starts at rows[1].
        The driver must not skip real data by assuming rows[2:].
        """
        from bs4 import BeautifulSoup
        # Reproduces the real CM8200 HTML structure (missing <tr> before column headers)
        html = """<html><body>
        <table class='simpleTable'>
        <tr><th colspan=8><strong>Downstream Bonded Channels</strong></th></tr>
            <td><strong>Channel ID</strong></td>
            <td><strong>Lock Status</strong></td>
            <td><strong>Modulation</strong></td>
            <td><strong>Frequency</strong></td>
            <td><strong>Power</strong></td>
            <td><strong>SNR/MER</strong></td>
            <td><strong>Corrected</strong></td>
            <td><strong>Uncorrectables</strong></td>
        </tr>
        <tr align='left'>
            <td>33</td><td>Locked</td><td>Other</td><td>795000000 Hz</td>
            <td>8.2 dBmV</td><td>43.0 dB</td><td>191405078</td><td>0</td>
        </tr>
        <tr align='left'>
            <td>1</td><td>Locked</td><td>QAM256</td><td>561000000 Hz</td>
            <td>4.9 dBmV</td><td>43.4 dB</td><td>17</td><td>0</td>
        </tr>
        </table>

        <table class='simpleTable'>
        <tr><th colspan=7><strong>Upstream Bonded Channels</strong></th></tr>
            <td><strong>Channel</strong></td>
            <td><strong>Channel ID</strong></td>
            <td><strong>Lock Status</strong></td>
            <td><strong>US Channel Type</td>
            <td><strong>Frequency</strong></td>
            <td><strong>Width</strong></td>
            <td><strong>Power</strong></td>
        </tr>
        <tr align='left'>
            <td>1</td><td>3</td><td>Locked</td><td>SC-QAM Upstream</td>
            <td>15500000 Hz</td><td>3200000 Hz</td><td>48.0 dBmV</td>
        </tr>
        </table>
        </body></html>"""
        soup = BeautifulSoup(html, "html.parser")
        with patch.object(driver, "_fetch_status_page", return_value=soup):
            data = driver.get_docsis_data()
            # Must find both channels despite malformed HTML
            assert len(data["channelDs"]["docsis31"]) == 1
            assert len(data["channelDs"]["docsis30"]) == 1
            assert data["channelDs"]["docsis31"][0]["channelID"] == 33
            assert data["channelDs"]["docsis30"][0]["channelID"] == 1
            # Upstream too
            assert len(data["channelUs"]["docsis30"]) == 1
            assert data["channelUs"]["docsis30"][0]["channelID"] == 3

    def test_status_html_cache_persists_across_calls(self, driver):
        """Cached HTML from login is reused across multiple fetches."""
        driver._status_html = SAMPLE_STATUS_HTML
        soup1 = driver._fetch_status_page()
        assert soup1.find("span", id="thisModelNumberIs") is not None
        assert driver._status_html is not None
        soup2 = driver._fetch_status_page()
        assert soup2.find("span", id="thisModelNumberIs") is not None

    def test_login_clears_stale_cache(self, driver):
        """login() invalidates old cache before authenticating."""
        driver._status_html = "<html>stale</html>"

        token_response = MagicMock()
        token_response.raise_for_status = MagicMock()
        token_response.text = "freshtoken123"

        status_response = MagicMock()
        status_response.raise_for_status = MagicMock()
        status_response.text = SAMPLE_STATUS_HTML

        with patch.object(driver._session, "get", side_effect=[token_response, status_response]):
            driver.login()

        assert driver._status_html == SAMPLE_STATUS_HTML


# -- Collector flow (login -> device_info -> docsis_data) --

class TestCollectorFlow:
    def test_single_auth_for_full_poll(self, driver):
        """Real collector calls login(), get_device_info(), get_docsis_data().

        All three must work with a single auth round-trip.  get_device_info()
        must not consume the cache so get_docsis_data() can reuse it.
        """
        token_response = MagicMock()
        token_response.raise_for_status = MagicMock()
        token_response.text = "token123"

        status_response = MagicMock()
        status_response.raise_for_status = MagicMock()
        status_response.text = SAMPLE_STATUS_HTML

        with patch.object(driver._session, "get", side_effect=[token_response, status_response]) as mock_get:
            driver.login()
            info = driver.get_device_info()
            data = driver.get_docsis_data()

        # Only 2 GETs: auth token + status page (both during login)
        assert mock_get.call_count == 2
        assert info["model"] == "CM8200A"
        assert len(data["channelDs"]["docsis30"]) == 32
        assert len(data["channelDs"]["docsis31"]) == 1

    def test_fetch_reauth_validates_token(self, driver):
        """_fetch_status_page re-auth rejects HTML instead of token."""
        driver._status_html = None
        driver._cookie_header = None

        html_response = MagicMock()
        html_response.text = "<html><body>Login page</body></html>"

        with patch.object(driver._session, "get", return_value=html_response):
            with pytest.raises(RuntimeError, match="re-auth failed"):
                driver._fetch_status_page()

    def test_fetch_reauth_validates_status_page(self, driver):
        """_fetch_status_page re-auth rejects small/login pages."""
        driver._status_html = None

        token_response = MagicMock()
        token_response.text = "validtoken99"

        login_page = MagicMock()
        login_page.raise_for_status = MagicMock()
        login_page.text = "<html>small login page</html>"

        with patch.object(driver._session, "get", side_effect=[token_response, login_page]):
            with pytest.raises(RuntimeError, match="re-auth succeeded but status page not returned"):
                driver._fetch_status_page()

    def test_fetch_reauth_caches_result(self, driver):
        """Successful re-auth in _fetch_status_page caches the HTML."""
        driver._status_html = None

        token_response = MagicMock()
        token_response.text = "reauth123"

        status_response = MagicMock()
        status_response.raise_for_status = MagicMock()
        status_response.text = SAMPLE_STATUS_HTML

        with patch.object(driver._session, "get", side_effect=[token_response, status_response]):
            soup = driver._fetch_status_page()

        assert driver._status_html == SAMPLE_STATUS_HTML
        assert soup.find("span", id="thisModelNumberIs") is not None


# -- Analyzer integration --

class TestAnalyzerIntegration:
    def test_full_pipeline(self, mock_status):
        """Verify CM8200 output feeds cleanly into the analyzer."""
        from app.analyzer import analyze
        data = mock_status.get_docsis_data()
        result = analyze(data)

        # 32 QAM + 1 OFDM = 33 downstream
        assert result["summary"]["ds_total"] == 33
        # 3 SC-QAM + 1 OFDMA = 4 upstream
        assert result["summary"]["us_total"] == 4
        assert result["summary"]["health"] in ("good", "tolerated", "marginal", "poor", "critical")
        assert len(result["ds_channels"]) == 33
        assert len(result["us_channels"]) == 4

    def test_qam_channels_labeled_docsis30(self, mock_status):
        from app.analyzer import analyze
        data = mock_status.get_docsis_data()
        result = analyze(data)

        qam_ids = {ch["channelID"] for ch in data["channelDs"]["docsis30"]}
        qam_ds = [c for c in result["ds_channels"] if c["channel_id"] in qam_ids]
        assert len(qam_ds) == 32
        for ch in qam_ds:
            assert ch["docsis_version"] == "3.0"

    def test_ofdm_channels_labeled_docsis31(self, mock_status):
        from app.analyzer import analyze
        data = mock_status.get_docsis_data()
        result = analyze(data)

        ofdm_ids = {ch["channelID"] for ch in data["channelDs"]["docsis31"]}
        ofdm_ds = [c for c in result["ds_channels"] if c["channel_id"] in ofdm_ids]
        assert len(ofdm_ds) == 1
        for ch in ofdm_ds:
            assert ch["docsis_version"] == "3.1"
