"""Tests for Arris CM3500B modem driver."""

import pytest
from unittest.mock import patch, MagicMock
from app.drivers.cm3500 import CM3500Driver


# -- Sample HTML matching real CM3500B status page structure --

STATUS_HTML = """<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN">
<html><head><title>Touchstone Status</title></head>
<body class="CM3500">
<div class="main_body">

<h4> Downstream QAM </h4>
<table class="heading2 thinset spc0">
<tbody>
<tr>
  <td></td><td>DCID</td><td>Freq</td><td>Power</td><td>SNR</td>
  <td>Modulation</td><td>Octets</td><td>Correcteds</td><td>Uncorrectables</td>
</tr>
<tr><td>Downstream 1</td><td>3</td><td>570.00 MHz</td><td>4.70 dBmV</td><td>38.98 dB</td><td>256QAM</td><td>200962211770</td><td>92</td><td>0</td></tr>
<tr><td>Downstream 2</td><td>4</td><td>578.00 MHz</td><td>4.80 dBmV</td><td>38.61 dB</td><td>256QAM</td><td>101707462174</td><td>114515</td><td>0</td></tr>
<tr><td>Downstream 3</td><td>5</td><td>586.00 MHz</td><td>4.70 dBmV</td><td>38.98 dB</td><td>256QAM</td><td>299546718863</td><td>108</td><td>0</td></tr>
</tbody>
</table>

<h4> Downstream OFDM </h4>
<table class="heading2 thinset spc0">
<thead>
<tr>
  <td rowspan="2"></td><td rowspan="2">FFT Type</td>
  <td rowspan="2">Channel Width(MHz)</td><td rowspan="2"># of Active Subcarriers</td>
  <td rowspan="2">First Active Subcarrier(MHz)</td><td rowspan="2">Last Active Subcarrier(MHz)</td>
  <td colspan="3">Average RxMER(dB)</td>
</tr>
<tr><td>Pilot</td><td>PLC</td><td>Data</td></tr>
</thead>
<tbody>
<tr><td>Downstream 1</td><td>4K</td><td>190</td><td>3800</td><td>135</td><td>324</td><td>47</td><td>40</td><td>41</td></tr>
<tr><td>Downstream 2</td><td>4K</td><td>110</td><td>2200</td><td>751</td><td>860</td><td>43</td><td>36</td><td>37</td></tr>
</tbody>
</table>

<h4> Upstream QAM </h4>
<table class="heading2 thinset spc0">
<tbody>
<tr>
  <td></td><td>UCID</td><td>Freq</td><td>Power</td>
  <td>Channel Type</td><td>Symbol Rate</td><td>Modulation</td>
</tr>
<tr><td>Upstream 1</td><td>9</td><td>30.80 MHz</td><td>39.50 dBmV</td><td>DOCSIS2.0 (ATDMA)</td><td>5120 kSym/s</td><td>64QAM</td></tr>
<tr><td>Upstream 2</td><td>13</td><td>58.40 MHz</td><td>40.00 dBmV</td><td>DOCSIS2.0 (ATDMA)</td><td>5120 kSym/s</td><td>64QAM</td></tr>
<tr><td>Upstream 3</td><td>12</td><td>51.00 MHz</td><td>39.75 dBmV</td><td>DOCSIS2.0 (ATDMA)</td><td>5120 kSym/s</td><td>64QAM</td></tr>
</tbody>
</table>

<h4> Upstream OFDM </h4>
<table class="heading2 thinset spc0">
<tbody>
<tr>
  <td></td><td>FFT Type</td><td>Channel Width(MHz)</td>
  <td># of Active Subcarriers</td><td>First Active Subcarrier(MHz)</td>
  <td>Last Active Subcarrier(MHz)</td><td>Tx Power(dBmV)</td>
</tr>
</tbody>
</table>

<table cellpadding="0" cellspacing="0">
<tbody>
<tr><td width="160">System Uptime: </td><td>58 d:  1 h: 30 m</td></tr>
<tr><td width="160">CM Status:</td><td>OPERATIONAL</td></tr>
</tbody>
</table>

<table CELLSPACING=0 CELLPADDING=0>
<tr><td width="160">Hardware Model</td><td>CM3500B</td></tr>
<tr><td width="160">Hardware Info</td><td>ARRIS DOCSIS 3.1 / EuroDOCSIS 3.0 Touchstone Cable Modem</td></tr>
</table>

</div>
</body></html>"""


@pytest.fixture
def driver():
    return CM3500Driver("https://192.168.100.1", "admin", "password")


@pytest.fixture
def mock_status(driver):
    """Patch _fetch_status_page to return parsed sample HTML."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(STATUS_HTML, "html.parser")
    with patch.object(driver, "_fetch_status_page", return_value=soup):
        yield driver


# -- Driver instantiation --

class TestDriverInit:
    def test_stores_credentials(self):
        d = CM3500Driver("https://192.168.100.1", "admin", "pass123")
        assert d._url == "https://192.168.100.1"
        assert d._user == "admin"
        assert d._password == "pass123"

    def test_load_via_registry(self):
        from app.drivers import load_driver
        d = load_driver("cm3500", "https://192.168.100.1", "admin", "pass")
        assert isinstance(d, CM3500Driver)


# -- Login --

class TestLogin:
    def test_login_posts_credentials(self, driver):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch.object(driver._session, "post", return_value=mock_response) as mock_post:
            driver.login()
            mock_post.assert_called_once_with(
                "https://192.168.100.1/cgi-bin/login_cgi",
                data={"username": "admin", "password": "password"},
                timeout=30,
            )

    def test_login_failure_raises(self, driver):
        import requests as req
        with patch.object(
            driver._session, "post",
            side_effect=req.RequestException("Connection refused"),
        ):
            with pytest.raises(RuntimeError, match="CM3500 authentication failed"):
                driver.login()


# -- DOCSIS data parsing --

class TestDocsisData:
    def test_returns_docsis_31(self, mock_status):
        data = mock_status.get_docsis_data()
        assert data["docsis"] == "3.1"

    def test_downstream_qam_count(self, mock_status):
        data = mock_status.get_docsis_data()
        ds_qam = [ch for ch in data["downstream"] if ch.get("type") != "OFDM"]
        assert len(ds_qam) == 3

    def test_downstream_qam_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["downstream"][0]
        assert ch["channelID"] == 3
        assert ch["frequency"] == "570 MHz"
        assert ch["powerLevel"] == 4.70
        assert ch["mer"] == 38.98
        assert ch["mse"] == -38.98
        assert ch["modulation"] == "256QAM"
        assert ch["corrErrors"] == 92
        assert ch["nonCorrErrors"] == 0

    def test_downstream_ofdm_count(self, mock_status):
        data = mock_status.get_docsis_data()
        ds_ofdm = [ch for ch in data["downstream"] if ch.get("type") == "OFDM"]
        assert len(ds_ofdm) == 2

    def test_downstream_ofdm_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ofdm = [ch for ch in data["downstream"] if ch.get("type") == "OFDM"]
        ch = ofdm[0]
        assert ch["channelID"] == 200
        assert ch["frequency"] == "135-324 MHz"
        assert ch["mer"] == 41.0
        assert ch["type"] == "OFDM"

    def test_upstream_qam_count(self, mock_status):
        data = mock_status.get_docsis_data()
        assert len(data["upstream"]) == 3

    def test_upstream_qam_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["upstream"][0]
        assert ch["channelID"] == 9
        assert ch["frequency"] == "30 MHz"
        assert ch["powerLevel"] == 39.50
        assert ch["modulation"] == "64QAM"
        assert ch["multiplex"] == "ATDMA"

    def test_upstream_ofdm_empty(self, mock_status):
        """Upstream OFDM table exists but has no data rows."""
        data = mock_status.get_docsis_data()
        us_ofdma = [ch for ch in data["upstream"] if ch.get("type") == "OFDMA"]
        assert len(us_ofdma) == 0


# -- Device info --

class TestDeviceInfo:
    def test_device_info(self, mock_status):
        info = mock_status.get_device_info()
        assert info["manufacturer"] == "Arris"
        assert info["model"] == "CM3500B"

    def test_uptime_parsed(self, mock_status):
        info = mock_status.get_device_info()
        # 58 days, 1 hour, 30 minutes
        expected = 58 * 86400 + 1 * 3600 + 30 * 60
        assert info["uptime_seconds"] == expected

    def test_connection_info_empty(self, mock_status):
        assert mock_status.get_connection_info() == {}


# -- Table section finding --

class TestTableSections:
    def test_finds_all_sections(self, mock_status):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(STATUS_HTML, "html.parser")
        sections = mock_status._find_table_sections(soup)
        assert "downstream qam" in sections
        assert "downstream ofdm" in sections
        assert "upstream qam" in sections
        assert "upstream ofdm" in sections


# -- Value parsers --

class TestValueParsers:
    def test_parse_number_with_unit(self):
        assert CM3500Driver._parse_number("4.70 dBmV") == 4.70

    def test_parse_number_plain(self):
        assert CM3500Driver._parse_number("38.98") == 38.98

    def test_parse_number_empty(self):
        assert CM3500Driver._parse_number("") == 0.0

    def test_parse_number_integer(self):
        assert CM3500Driver._parse_number("92") == 92.0

    def test_format_freq(self):
        assert CM3500Driver._format_freq("570.00 MHz") == "570 MHz"

    def test_format_freq_integer(self):
        assert CM3500Driver._format_freq("30.80 MHz") == "30 MHz"

    def test_format_freq_empty(self):
        assert CM3500Driver._format_freq("") == ""


# -- Integration with analyzer --

class TestAnalyzerIntegration:
    def test_full_pipeline(self, mock_status):
        """Verify CM3500 output feeds cleanly into the analyzer."""
        from app.analyzer import analyze
        data = mock_status.get_docsis_data()
        result = analyze(data)

        assert result["summary"]["ds_total"] == 5  # 3 QAM + 2 OFDM
        assert result["summary"]["us_total"] == 3
        assert result["summary"]["health"] in ("good", "marginal", "poor")
        assert len(result["ds_channels"]) == 5
        assert len(result["us_channels"]) == 3
