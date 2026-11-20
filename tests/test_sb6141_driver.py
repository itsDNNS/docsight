"""Tests for Arris/Motorola SB6141 modem driver."""

import pytest
from unittest.mock import patch, MagicMock
from app.drivers.sb6141 import SB6141Driver


# -- Sample HTML from SB6141 HAR capture --

SAMPLE_SIGNAL_HTML = """
<HTML><HEAD></HEAD>
<BODY>
  <CENTER>
      <TABLE align=center border=1 cellPadding=8 cellSpacing=0>
      <TBODY>
      <TR>
      <TH><FONT color=#ffffff>Downstream </FONT></TH>
      <TH colspan=8><FONT color=#ffffff>Bonding Channel Value</FONT></TH></TR>
<TR><TD>Channel ID</TD>
<TD>1&nbsp; </TD><TD>3&nbsp; </TD><TD>4&nbsp; </TD><TD>5&nbsp; </TD><TD>6&nbsp; </TD><TD>7&nbsp; </TD><TD>8&nbsp; </TD><TD>9&nbsp; </TD></TR>
<TR><TD>Frequency</TD>
<TD>465000000 Hz&nbsp;</TD><TD>477000000 Hz&nbsp;</TD><TD>483000000 Hz&nbsp;</TD><TD>489000000 Hz&nbsp;</TD><TD>495000000 Hz&nbsp;</TD><TD>501000000 Hz&nbsp;</TD><TD>507000000 Hz&nbsp;</TD><TD>513000000 Hz&nbsp;</TD></TR>
<TR><TD>Signal to Noise Ratio</TD>
<TD>35 dB&nbsp;</TD><TD>36 dB&nbsp;</TD><TD>36 dB&nbsp;</TD><TD>36 dB&nbsp;</TD><TD>36 dB&nbsp;</TD><TD>36 dB&nbsp;</TD><TD>36 dB&nbsp;</TD><TD>36 dB&nbsp;</TD></TR>
<TR><TD>Downstream Modulation</TD>
<TD>QAM256&nbsp;</TD><TD>QAM256&nbsp;</TD><TD>QAM256&nbsp;</TD><TD>QAM256&nbsp;</TD><TD>QAM256&nbsp;</TD><TD>QAM256&nbsp;</TD><TD>QAM256&nbsp;</TD><TD>QAM256&nbsp;</TD></TR>
<TR><TD>Power Level<TABLE border=0 cellPadding=0 cellSpacing=0 width=300>
  <TBODY><TR><TD align=left><SMALL>The Downstream Power Level reading is a
  snapshot taken at the time this page was requested.</SMALL></TD></TR></TBODY></TABLE></TD>
<TD>3 dBmV
&nbsp;</TD><TD>2 dBmV
&nbsp;</TD><TD>2 dBmV
&nbsp;</TD><TD>2 dBmV
&nbsp;</TD><TD>2 dBmV
&nbsp;</TD><TD>2 dBmV
&nbsp;</TD><TD>2 dBmV
&nbsp;</TD><TD>2 dBmV
&nbsp;</TD></TR>
</TBODY></TABLE></CENTER>

<P></P>

  <CENTER>
      <TABLE align=center border=1 cellPadding=8 cellSpacing=0>
      <TBODY>
      <TR>
      <TH><FONT color=#ffffff>Upstream </FONT></TH>
      <TH colspan=1><FONT color=#ffffff>Bonding Channel Value</FONT></TH></TR>
<TR><TD>Channel ID</TD>
<TD>2&nbsp; </TD></TR>
<TR><TD>Frequency</TD>
<TD>24600000 Hz&nbsp;</TD></TR>
<TR><TD>Ranging Service ID</TD>
<TD>10367&nbsp;</TD></TR>
<TR><TD>Symbol Rate</TD>
<TD>5.120 Msym/sec&nbsp;</TD></TR>
<TR><TD>Power Level</TD>
<TD>51 dBmV&nbsp;</TD></TR>
<TR><TD>Upstream Modulation</TD>
<TD>[3] QPSK
[3] 64QAM
&nbsp;</TD></TR>
<TR><TD>Ranging Status </TD>
<TD>Success&nbsp;</TD></TR>
</TBODY></TABLE></CENTER>

<P></P>

  <CENTER>
      <TABLE align=center border=1 cellPadding=8 cellSpacing=0>
      <TBODY>
      <TR>
      <TH><FONT color=#ffffff>Signal Status (Codewords)</FONT></TH>
      <TH colspan=8><FONT color=#ffffff>Bonding Channel Value</FONT></TH></TR>
<TR><TD>Channel ID</TD>
<TD>1&nbsp; </TD><TD>3&nbsp; </TD><TD>4&nbsp; </TD><TD>5&nbsp; </TD><TD>6&nbsp; </TD><TD>7&nbsp; </TD><TD>8&nbsp; </TD><TD>9&nbsp; </TD></TR>
<TR><TD>Total Unerrored Codewords</TD>
<TD>37104250894&nbsp;</TD><TD>37104280575&nbsp;</TD><TD>37104264303&nbsp;</TD><TD>37104272631&nbsp;</TD><TD>37104246245&nbsp;</TD><TD>37104249663&nbsp;</TD><TD>37104251389&nbsp;</TD><TD>37104249627&nbsp;</TD></TR>
<TR><TD>Total Correctable Codewords</TD>
<TD>441&nbsp;</TD><TD>428&nbsp;</TD><TD>247&nbsp;</TD><TD>192&nbsp;</TD><TD>70&nbsp;</TD><TD>31&nbsp;</TD><TD>31&nbsp;</TD><TD>27&nbsp;</TD></TR>
<TR><TD>Total Uncorrectable Codewords</TD>
<TD>1635&nbsp;</TD><TD>1424&nbsp;</TD><TD>1529&nbsp;</TD><TD>1434&nbsp;</TD><TD>1474&nbsp;</TD><TD>1604&nbsp;</TD><TD>1490&nbsp;</TD><TD>1513&nbsp;</TD></TR>
</TBODY></TABLE></CENTER>
</BODY>
</HTML>
"""

SAMPLE_HELP_HTML = """
<HTML><HEAD></HEAD>
<BODY>
<TABLE align=center border=0 cellPadding=5 cellSpacing=0 width="100%">
  <TBODY>
  <TR>
    <TD>
      Model Name: SB6141<BR>
      Vendor Name: ARRIS Group, Inc. <BR>
      Firmware Name: SB_KOMODO-1.0.7.3-SCM02-NOSH<BR>
      Boot Version: PSPU-Boot(25CLK) 1.0.12.18m3<BR>
      Hardware Version: 7.0<BR>
      Serial Number: ABC123<BR>
      Firmware Build Time: Apr 22 2019 15:16:24<BR>
    </TD></TR>
  </TBODY>
</TABLE>
</BODY>
</HTML>
"""


def serve_html(driver, text, method="get"):
    """Patch driver._session.<method> to answer every request with text."""
    response = MagicMock()
    response.text = text
    return patch.object(driver._session, method, return_value=response)


@pytest.fixture
def driver():
    return SB6141Driver("http://192.168.100.1", "", "")


@pytest.fixture(params=[
    SAMPLE_SIGNAL_HTML,
    # Headings split across inline elements must still identify their tables.
    SAMPLE_SIGNAL_HTML.replace(">Downstream <", ">Down<span>stream</span> <"),
    SAMPLE_SIGNAL_HTML.replace(">Upstream <", ">Up<span>stream</span> <"),
    SAMPLE_SIGNAL_HTML.replace(">Signal Status (Codewords)<", ">Code<span>words</span><"),
], ids=["captured", "split-downstream", "split-upstream", "split-codewords"])
def mock_signal(driver, request):
    """Patch session.get to return sample signal HTML."""
    with serve_html(driver, request.param):
        yield driver


# -- Driver instantiation --

class TestDriverInit:
    def test_stores_url(self):
        d = SB6141Driver("http://192.168.100.1", "", "")
        assert d._url == "http://192.168.100.1"

    def test_load_via_registry(self):
        from app.drivers import load_driver
        d = load_driver("sb6141", "http://192.168.100.1", "", "")
        assert isinstance(d, SB6141Driver)


# -- Login --

class TestLogin:
    def test_login_verifies_reachability(self, driver):
        with serve_html(driver, SAMPLE_SIGNAL_HTML) as mock_get:
            driver.login()
            url = mock_get.call_args[0][0]
            assert "cmSignalData.htm" in url

    def test_login_raises_on_connection_error(self, driver):
        import requests
        with patch.object(driver._session, "get", side_effect=requests.ConnectionError("refused")):
            with pytest.raises(RuntimeError, match="SB6141 connection failed"):
                driver.login()


# -- Downstream --

class TestDownstream:
    def test_channel_count(self, mock_signal):
        data = mock_signal.get_docsis_data()
        assert len(data["channelDs"]["docsis30"]) == 8

    def test_docsis31_empty(self, mock_signal):
        data = mock_signal.get_docsis_data()
        assert data["channelDs"]["docsis31"] == []

    def test_channel_ids(self, mock_signal):
        data = mock_signal.get_docsis_data()
        ids = [ch["channelID"] for ch in data["channelDs"]["docsis30"]]
        assert ids == [1, 3, 4, 5, 6, 7, 8, 9]

    def test_first_channel_fields(self, mock_signal):
        data = mock_signal.get_docsis_data()
        ch = data["channelDs"]["docsis30"][0]
        assert ch["channelID"] == 1
        assert ch["frequency"] == "465 MHz"
        assert ch["powerLevel"] == 3.0
        assert ch["mer"] == 35.0
        assert ch["mse"] == -35.0
        assert ch["modulation"] == "QAM256"

    def test_error_counts_from_codewords_table(self, mock_signal):
        data = mock_signal.get_docsis_data()
        ch = data["channelDs"]["docsis30"][0]
        assert ch["corrErrors"] == 441
        assert ch["nonCorrErrors"] == 1635

    def test_last_channel_errors(self, mock_signal):
        data = mock_signal.get_docsis_data()
        ch = data["channelDs"]["docsis30"][-1]
        assert ch["corrErrors"] == 27
        assert ch["nonCorrErrors"] == 1513

    def test_frequency_conversion(self, mock_signal):
        data = mock_signal.get_docsis_data()
        freqs = [ch["frequency"] for ch in data["channelDs"]["docsis30"]]
        assert freqs[0] == "465 MHz"
        assert freqs[1] == "477 MHz"
        assert all("MHz" in f for f in freqs)


# -- Upstream --

class TestUpstream:
    def test_channel_count(self, mock_signal):
        data = mock_signal.get_docsis_data()
        assert len(data["channelUs"]["docsis30"]) == 1

    def test_docsis31_empty(self, mock_signal):
        data = mock_signal.get_docsis_data()
        assert data["channelUs"]["docsis31"] == []

    def test_channel_fields(self, mock_signal):
        data = mock_signal.get_docsis_data()
        ch = data["channelUs"]["docsis30"][0]
        assert ch["channelID"] == 2
        assert ch["frequency"] == "24.6 MHz"
        assert ch["powerLevel"] == 51.0
        assert ch["multiplex"] == "SC-QAM"

    def test_upstream_modulation_extracts_highest(self, mock_signal):
        """Upstream modulation may have multiple entries, take the last one."""
        data = mock_signal.get_docsis_data()
        ch = data["channelUs"]["docsis30"][0]
        assert ch["modulation"] == "64QAM"


# -- Device info --

class TestDeviceInfo:
    def test_parses_help_page(self, driver):
        with serve_html(driver, SAMPLE_HELP_HTML):
            info = driver.get_device_info()

        assert info["manufacturer"] == "ARRIS Group, Inc."
        assert info["model"] == "SB6141"
        assert info["sw_version"] == "SB_KOMODO-1.0.7.3-SCM02-NOSH"

    def test_fallback_on_error(self, driver):
        import requests
        with patch.object(driver._session, "get", side_effect=requests.ConnectionError()):
            info = driver.get_device_info()
            assert info["model"] == "SB6141"

    def test_connection_info_empty(self, driver):
        assert driver.get_connection_info() == {}


# -- Value helpers --

class TestValueHelpers:
    def test_parse_freq_hz_integer(self):
        assert SB6141Driver._parse_freq_hz("465000000 Hz") == "465 MHz"

    def test_parse_freq_hz_decimal(self):
        assert SB6141Driver._parse_freq_hz("24600000 Hz") == "24.6 MHz"

    def test_parse_freq_hz_empty(self):
        assert SB6141Driver._parse_freq_hz("") == ""

    def test_parse_number_with_unit(self):
        assert SB6141Driver._parse_number("35 dB") == 35.0

    def test_parse_number_dbmv(self):
        assert SB6141Driver._parse_number("3 dBmV") == 3.0

    def test_parse_number_decimal(self):
        assert SB6141Driver._parse_number("5.120 Msym/sec") == 5.12

    def test_parse_number_empty(self):
        assert SB6141Driver._parse_number("") == 0.0

    def test_extract_upstream_modulation_multi(self):
        assert SB6141Driver._extract_upstream_modulation("[3] QPSK\n[3] 64QAM") == "64QAM"

    def test_extract_upstream_modulation_single(self):
        assert SB6141Driver._extract_upstream_modulation("[2] QAM16") == "QAM16"

    def test_extract_upstream_modulation_empty(self):
        assert SB6141Driver._extract_upstream_modulation("") == ""


# -- Edge cases --

class TestEdgeCases:
    def test_no_tables(self, driver):
        with serve_html(driver, "<html><body></body></html>"):
            data = driver.get_docsis_data()
            assert data["channelDs"]["docsis30"] == []
            assert data["channelUs"]["docsis30"] == []

    def test_no_codewords_table(self, driver):
        """If codewords table is missing, errors default to 0."""
        html = """<html><body>
        <table><tr><th>Downstream</th><th colspan=2>Bonding Channel Value</th></tr>
        <tr><td>Channel ID</td><td>1</td><td>2</td></tr>
        <tr><td>Frequency</td><td>465000000 Hz</td><td>471000000 Hz</td></tr>
        <tr><td>Signal to Noise Ratio</td><td>35 dB</td><td>36 dB</td></tr>
        <tr><td>Downstream Modulation</td><td>QAM256</td><td>QAM256</td></tr>
        <tr><td>Power Level</td><td>3 dBmV</td><td>2 dBmV</td></tr>
        </table>
        </body></html>"""

        with serve_html(driver, html):
            data = driver.get_docsis_data()
            assert len(data["channelDs"]["docsis30"]) == 2
            assert data["channelDs"]["docsis30"][0]["corrErrors"] == 0
            assert data["channelDs"]["docsis30"][0]["nonCorrErrors"] == 0


# -- Analyzer integration --

class TestAnalyzerIntegration:
    def test_full_pipeline(self, mock_signal):
        from app.analyzer import analyze
        data = mock_signal.get_docsis_data()
        result = analyze(data)

        assert result["summary"]["ds_total"] == 8
        assert result["summary"]["us_total"] == 1
        assert result["summary"]["health"] in ("good", "tolerated", "marginal", "poor", "critical")
        assert len(result["ds_channels"]) == 8
        assert len(result["us_channels"]) == 1

    def test_all_channels_labeled_docsis30(self, mock_signal):
        from app.analyzer import analyze
        data = mock_signal.get_docsis_data()
        result = analyze(data)

        for ch in result["ds_channels"]:
            assert ch["docsis_version"] == "3.0"
        for ch in result["us_channels"]:
            assert ch["docsis_version"] == "3.0"
