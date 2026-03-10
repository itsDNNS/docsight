"""Tests for Netgear CM3000 modem driver."""

import pytest
from unittest.mock import patch, MagicMock
from app.drivers.cm3000 import CM3000Driver


# -- Embedded tagValueList strings from real CM3000 HAR capture --

TAG_DS_QAM = (
    "32"
    "|1|Locked|QAM256|20|495000000 Hz|-0.2|42.7|23958|32851"
    "|2|Locked|QAM256|1|381000000 Hz|0.4|43.2|34797|40892"
    "|3|Locked|QAM256|2|387000000 Hz|0.3|43.2|37561|42672"
    "|4|Locked|QAM256|3|393000000 Hz|0.4|43.2|33953|38043"
    "|5|Locked|QAM256|4|399000000 Hz|0.6|43.3|32673|39451"
    "|6|Locked|QAM256|5|405000000 Hz|0.6|43.3|34399|40741"
    "|7|Locked|QAM256|6|411000000 Hz|0.8|43.4|30699|36293"
    "|8|Locked|QAM256|7|417000000 Hz|0.9|43.5|31511|40767"
    "|9|Locked|QAM256|8|423000000 Hz|0.9|43.5|31578|37965"
    "|10|Locked|QAM256|9|429000000 Hz|0.9|43.5|28646|34787"
    "|11|Locked|QAM256|10|435000000 Hz|0.9|43.4|30226|39108"
    "|12|Locked|QAM256|11|441000000 Hz|0.8|43.4|29801|36278"
    "|13|Locked|QAM256|12|447000000 Hz|0.9|43.4|27612|34802"
    "|14|Locked|QAM256|13|453000000 Hz|0.6|43.3|28482|37959"
    "|15|Locked|QAM256|14|459000000 Hz|0.4|43.1|27508|34822"
    "|16|Locked|QAM256|15|465000000 Hz|0.2|43|25607|35509"
    "|17|Locked|QAM256|16|471000000 Hz|0.1|42.9|28004|37911"
    "|18|Locked|QAM256|17|477000000 Hz|0|42.8|25903|33855"
    "|19|Locked|QAM256|18|483000000 Hz|0.1|42.8|24603|36215"
    "|20|Locked|QAM256|19|489000000 Hz|-0.1|42.7|26094|37436"
    "|21|Locked|QAM256|21|501000000 Hz|-0.3|42.6|23903|37227"
    "|22|Locked|QAM256|22|507000000 Hz|-0.4|42.5|24970|36407"
    "|23|Locked|QAM256|23|513000000 Hz|-0.5|42.5|22567|32480"
    "|24|Locked|QAM256|24|519000000 Hz|-0.5|42.5|23552|36964"
    "|25|Locked|QAM256|25|525000000 Hz|-0.7|42.3|23301|34549"
    "|26|Locked|QAM256|26|531000000 Hz|-0.7|42.3|21309|33618"
    "|27|Locked|QAM256|27|537000000 Hz|-0.8|42.2|21981|36864"
    "|28|Locked|QAM256|28|543000000 Hz|-0.7|42.3|21435|33439"
    "|29|Locked|QAM256|29|549000000 Hz|-0.6|42.4|19350|33607"
    "|30|Locked|QAM256|30|555000000 Hz|-0.6|42.3|21320|37292"
    "|31|Locked|QAM256|31|561000000 Hz|-0.6|42.3|19305|32935"
    "|32|Locked|QAM256|32|567000000 Hz|-0.7|42.3|18550|34892|"
)

TAG_US_ATDMA = (
    "8"
    "|1|Locked|ATDMA|2|5120 Ksym/sec|22800000 Hz|43.3 dBmV"
    "|2|Locked|ATDMA|3|5120 Ksym/sec|29200000 Hz|43.5 dBmV"
    "|3|Locked|ATDMA|4|5120 Ksym/sec|35600000 Hz|43.8 dBmV"
    "|4|Locked|ATDMA|1|5120 Ksym/sec|16400000 Hz|43.5 dBmV"
    "|5|Not Locked|Unknown|0|0|0|0.0"
    "|6|Not Locked|Unknown|0|0|0|0.0"
    "|7|Not Locked|Unknown|0|0|0|0.0"
    "|8|Not Locked|Unknown|0|0|0|0.0|"
)

TAG_DS_OFDM = (
    "2"
    "|1|Locked|0 ,1 ,2 ,3|193|690000000 Hz|-0.32 dBmV|41.8 dB"
    "|388 ~ 3707|21375387957|10237586972|18675397"
    "|2|Locked|0 ,1 ,2 ,3|194|957000000 Hz|-5.92 dBmV|38.6 dB"
    "|148 ~ 3947|21728350102|19395421307|378|"
)

TAG_US_OFDMA = (
    "2"
    "|1|Locked|12 ,13|41|36200000 Hz|36.5 dBmV"
    "|2|Not Locked|0|0|0 Hz|0 dBmV"
)

TAG_SYS_INFO = (
    "495000000|Locked|OK|Operational|OK|Operational"
    "|&nbsp;|&nbsp;|Enabled|BPI+"
    "|Fri Mar 06 18:26:39 2026|0|0|0"
    "|23 days 09:26:24|3|1|"
)


def _build_status_html(
    ds_qam=TAG_DS_QAM,
    us_atdma=TAG_US_ATDMA,
    ds_ofdm=TAG_DS_OFDM,
    us_ofdma=TAG_US_OFDMA,
    sys_info=TAG_SYS_INFO,
):
    """Build a minimal DocsisStatus.htm with embedded tagValueList strings.

    Mirrors the real CM3000 JavaScript structure: each function has an
    optional commented-out example, then the live single-quoted assignment.
    """
    return f"""<html><head><title>NETGEAR - Cable Modem CM3000</title>
<script language='javascript' type='text/javascript'>
function InitCableDiagTagValue()
{{
    var tagValueList = "0|0|0|0|0|0|0|1||diag text";
    return tagValueList.split("|");
}}

function InitTagValue()
{{
/*
  Acquire Downstream Channel (text) | Connectivity State (text)
*/
    var tagValueList = '{sys_info}';
    return tagValueList.split("|");
}}

function InitUpdateView(tagValues)
{{
    // update code here
}}

function InitUsTableTagValue()
{{
/*
  Channel (text) | Lock Status (text) | US Channel Type (text) | Channel ID (text) | Symbol Rate (text) | Frequency (text) | Power (text)
*/
/*
    var tagValueList = "4"
        + "|1|Not Locked|Unknown|0|0|0|0.0"
        + "|2|Not Locked|Unknown|0|0|0|0.0";
*/
    var tagValueList = '{us_atdma}';
    return tagValueList.split("|");
}}

function onAddUsRowCB(rowNumber, numRows, tagValues, startIdx)
{{
    // row callback
}}

function InitDsTableTagValue()
{{
/*
  Channel (text) | Lock Status (text) | Modulation (text) | Channel ID (text) | Frequency (text) | Power (text) | SNR (text) | Correctables (text) | Uncorrectables (text)
*/
/*
    var tagValueList = "8"
        + "|1|Locked|Unknown|0|809500000|-61.6|0.0|11|0";
*/
    var tagValueList = '{ds_qam}';
    return tagValueList.split("|");
}}

function InitCmIpProvModeTag()
{{
    var tagValueList = '1|Honor MDD|IPv6 only|';
    return tagValueList.split("|");
}}

function InitUsOfdmaTableTagValue()
{{
    /*
    var tagValueList = '2'
        + '|1||Success|1300000 Hz|74~1673|18|30.8 dBmV'
        + '|2||Success|41300000 Hz|74~1673|18|30.5 dBmV';
    */
    var tagValueList = '{us_ofdma}';
    return tagValueList.split("|");
}}

function InitDsOfdmTableTagValue()
{{
    /*
    var tagValueList = '2'
        + '|1|66|Primary|297600000 Hz|148~3947|0|0'
        + '|2|99|Backup Primary|495600000 Hz|148~3947|0|0';
    */
    var tagValueList = '{ds_ofdm}';
    return tagValueList.split("|");
}}

function InitMsgTagValue()
{{
    var tagValueList = "All good";
    return tagValueList.split("|");
}}
</script>
</head><body></body></html>"""


STATUS_HTML = _build_status_html()


@pytest.fixture
def driver():
    return CM3000Driver("http://192.168.100.1", "admin", "password")


@pytest.fixture
def mock_status(driver):
    """Patch _fetch_status_page to return sample HTML."""
    with patch.object(driver, "_fetch_status_page", return_value=STATUS_HTML):
        yield driver


# -- Driver instantiation --

class TestDriverInit:
    def test_stores_credentials(self):
        d = CM3000Driver("http://192.168.100.1", "admin", "pass123")
        assert d._url == "http://192.168.100.1"
        assert d._user == "admin"
        assert d._password == "pass123"

    def test_session_has_basic_auth(self):
        d = CM3000Driver("http://192.168.100.1", "admin", "pass123")
        assert d._session.auth == ("admin", "pass123")

    def test_load_via_registry(self):
        from app.drivers import load_driver
        d = load_driver("cm3000", "http://192.168.100.1", "admin", "pass")
        assert isinstance(d, CM3000Driver)


# -- Login --

class TestLogin:
    def test_login_fetches_status_page_with_auth(self, driver):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.text = STATUS_HTML

        with patch.object(driver._session, "get", return_value=mock_response) as mock_get:
            driver.login()
            mock_get.assert_called_once_with("http://192.168.100.1/DocsisStatus.htm", timeout=30)
            assert driver._status_html == STATUS_HTML

    def test_login_failure_raises(self, driver):
        import requests as req
        with patch.object(
            driver._session, "get",
            side_effect=req.RequestException("401 Unauthorized"),
        ):
            with pytest.raises(RuntimeError, match="CM3000 authentication failed"):
                driver.login()

    def test_login_retries_on_connection_error(self, driver):
        import requests as req
        mock_ok = MagicMock()
        mock_ok.raise_for_status = MagicMock()
        mock_ok.text = STATUS_HTML

        # First call on old session raises ConnectionError.
        # Driver creates a new session for retry, so we patch
        # requests.Session to return a mock whose .get() succeeds.
        mock_new_session = MagicMock()
        mock_new_session.get.return_value = mock_ok

        with patch.object(
            driver._session, "get",
            side_effect=req.ConnectionError("reset"),
        ), patch("app.drivers.cm3000.requests.Session", return_value=mock_new_session):
            driver.login()  # Should succeed on retry
            mock_new_session.get.assert_called_once()

    def test_login_rejects_login_page_false_positive(self, driver):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = """
            <html><body>
            <script>
            if (sessionStorage.getItem('PrivateKey') === null) {
                window.location.replace('../Login.htm');
            }
            </script>
            </body></html>
        """

        with patch.object(driver._session, "get", return_value=mock_response):
            with pytest.raises(RuntimeError, match="returned a login page"):
                driver.login()


# -- DOCSIS data: structure --

class TestDocsisDataStructure:
    def test_returns_pre_split_format(self, mock_status):
        data = mock_status.get_docsis_data()
        assert "channelDs" in data
        assert "channelUs" in data
        assert "docsis30" in data["channelDs"]
        assert "docsis31" in data["channelDs"]
        assert "docsis30" in data["channelUs"]
        assert "docsis31" in data["channelUs"]


# -- Downstream SC-QAM --

class TestDownstreamQAM:
    def test_channel_count(self, mock_status):
        data = mock_status.get_docsis_data()
        assert len(data["channelDs"]["docsis30"]) == 32

    def test_first_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelDs"]["docsis30"][0]
        assert ch["channelID"] == 20
        assert ch["frequency"] == "495 MHz"
        assert ch["powerLevel"] == -0.2
        assert ch["mer"] == 42.7
        assert ch["mse"] == -42.7
        assert ch["modulation"] == "QAM256"
        assert ch["corrErrors"] == 23958
        assert ch["nonCorrErrors"] == 32851

    def test_last_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelDs"]["docsis30"][-1]
        assert ch["channelID"] == 32
        assert ch["frequency"] == "567 MHz"
        assert ch["powerLevel"] == -0.7

    def test_frequency_conversion(self, mock_status):
        """Hz values are converted to MHz."""
        data = mock_status.get_docsis_data()
        freqs = [ch["frequency"] for ch in data["channelDs"]["docsis30"]]
        assert all("MHz" in f for f in freqs)
        assert "495 MHz" in freqs
        assert "381 MHz" in freqs


# -- Upstream ATDMA --

class TestUpstreamATDMA:
    def test_locked_count(self, mock_status):
        """4 locked channels, 4 unlocked skipped."""
        data = mock_status.get_docsis_data()
        assert len(data["channelUs"]["docsis30"]) == 4

    def test_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelUs"]["docsis30"][0]
        assert ch["channelID"] == 2
        assert ch["frequency"] == "22.8 MHz"
        assert ch["powerLevel"] == 43.3
        assert ch["modulation"] == "ATDMA"
        assert ch["multiplex"] == "ATDMA"

    def test_unlocked_channels_skipped(self, mock_status):
        """Channels 5-8 are 'Not Locked' and should not appear."""
        data = mock_status.get_docsis_data()
        channel_ids = [ch["channelID"] for ch in data["channelUs"]["docsis30"]]
        assert 0 not in channel_ids  # Not Locked channels have channelID 0


# -- Downstream OFDM --

class TestDownstreamOFDM:
    def test_channel_count(self, mock_status):
        data = mock_status.get_docsis_data()
        assert len(data["channelDs"]["docsis31"]) == 2

    def test_first_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelDs"]["docsis31"][0]
        assert ch["channelID"] == 193
        assert ch["type"] == "OFDM"
        assert ch["frequency"] == "690 MHz"
        assert ch["powerLevel"] == -0.32
        assert ch["mer"] == 41.8
        assert ch["mse"] is None
        assert ch["corrErrors"] == 21375387957
        assert ch["nonCorrErrors"] == 10237586972

    def test_second_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelDs"]["docsis31"][1]
        assert ch["channelID"] == 194
        assert ch["frequency"] == "957 MHz"
        assert ch["powerLevel"] == -5.92
        assert ch["mer"] == 38.6


# -- Upstream OFDMA --

class TestUpstreamOFDMA:
    def test_locked_count(self, mock_status):
        """1 locked, 1 unlocked skipped."""
        data = mock_status.get_docsis_data()
        assert len(data["channelUs"]["docsis31"]) == 1

    def test_channel_fields(self, mock_status):
        data = mock_status.get_docsis_data()
        ch = data["channelUs"]["docsis31"][0]
        assert ch["channelID"] == 41
        assert ch["type"] == "OFDMA"
        assert ch["frequency"] == "36.2 MHz"
        assert ch["powerLevel"] == 36.5
        assert ch["modulation"] == "OFDMA"


# -- Device info --

class TestDeviceInfo:
    def test_device_info(self, mock_status):
        info = mock_status.get_device_info()
        assert info["manufacturer"] == "Netgear"
        assert info["model"] == "CM3000"

    def test_uptime_parsed(self, mock_status):
        info = mock_status.get_device_info()
        # 23 days, 9 hours, 26 minutes, 24 seconds
        expected = 23 * 86400 + 9 * 3600 + 26 * 60 + 24
        assert info["uptime_seconds"] == expected

    def test_connection_info_empty(self, driver):
        """Standalone modem returns empty dict."""
        assert driver.get_connection_info() == {}


# -- Value parsers --

class TestValueParsers:
    def test_hz_to_mhz_integer(self):
        assert CM3000Driver._hz_to_mhz("495000000 Hz") == "495 MHz"

    def test_hz_to_mhz_decimal(self):
        assert CM3000Driver._hz_to_mhz("22800000 Hz") == "22.8 MHz"

    def test_hz_to_mhz_zero(self):
        assert CM3000Driver._hz_to_mhz("0") == "0 MHz"

    def test_parse_number_with_unit(self):
        assert CM3000Driver._parse_number("43.3 dBmV") == 43.3

    def test_parse_number_negative(self):
        assert CM3000Driver._parse_number("-0.32 dBmV") == -0.32

    def test_parse_number_plain(self):
        assert CM3000Driver._parse_number("41.8 dB") == 41.8

    def test_parse_number_empty(self):
        assert CM3000Driver._parse_number("") == 0.0

    def test_parse_uptime(self):
        assert CM3000Driver._parse_uptime("23 days 09:26:24") == (
            23 * 86400 + 9 * 3600 + 26 * 60 + 24
        )

    def test_parse_uptime_single_day(self):
        assert CM3000Driver._parse_uptime("1 day 00:05:00") == 86700

    def test_parse_uptime_invalid(self):
        assert CM3000Driver._parse_uptime("invalid") is None

    def test_split_channels(self):
        raw = "2|a|b|c|d|e|f"
        channels = CM3000Driver._split_channels(raw, 3)
        assert len(channels) == 2
        assert channels[0] == ["a", "b", "c"]
        assert channels[1] == ["d", "e", "f"]

    def test_split_channels_trailing_pipe(self):
        raw = "1|a|b|c|"
        channels = CM3000Driver._split_channels(raw, 3)
        assert len(channels) == 1
        assert channels[0] == ["a", "b", "c"]

    def test_fetch_status_page_rejects_missing_docsis_blocks(self, driver):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_response.text = "<html><body><h1>Welcome</h1></body></html>"

        with patch.object(driver._session, "get", return_value=mock_response):
            with pytest.raises(RuntimeError, match="expected DOCSIS data blocks"):
                driver._fetch_status_page()

    def test_fetch_status_page_uses_cached_login_html(self, driver):
        driver._status_html = STATUS_HTML

        with patch.object(driver._session, "get") as mock_get:
            assert driver._fetch_status_page() == STATUS_HTML
            mock_get.assert_not_called()
            # Cache persists for the entire collect cycle
            assert driver._status_html == STATUS_HTML


# -- Regex patterns --

class TestRegexPatterns:
    def test_skips_commented_out_tagValueList(self):
        """The regex must match the live assignment, not the /* */ comment."""
        data = mock_status_data = _build_status_html()
        from app.drivers.cm3000 import _RE_DS_QAM
        m = _RE_DS_QAM.search(data)
        assert m is not None
        # The live data starts with "32|" (32 channels)
        assert m.group(1).startswith("32|")
        # Not the commented-out example starting with "8|"
        assert not m.group(1).startswith("8|")

    def test_all_patterns_match(self):
        html = _build_status_html()
        from app.drivers.cm3000 import (
            _RE_DS_QAM, _RE_US_ATDMA, _RE_DS_OFDM, _RE_US_OFDMA, _RE_SYS_INFO,
        )
        assert _RE_DS_QAM.search(html) is not None
        assert _RE_US_ATDMA.search(html) is not None
        assert _RE_DS_OFDM.search(html) is not None
        assert _RE_US_OFDMA.search(html) is not None
        assert _RE_SYS_INFO.search(html) is not None


# -- Collect cycle (cache reuse) --

class TestCollectCycle:
    def test_device_info_and_docsis_data_share_cached_html(self, driver):
        """Both get_device_info() and get_docsis_data() must use the same
        cached HTML from login(), without a second HTTP fetch."""
        driver._status_html = STATUS_HTML

        with patch.object(driver._session, "get") as mock_get:
            info = driver.get_device_info()
            data = driver.get_docsis_data()
            mock_get.assert_not_called()

        assert info["model"] == "CM3000"
        assert len(data["channelDs"]["docsis30"]) == 32
        assert len(data["channelUs"]["docsis30"]) == 4

    def test_regex_handles_nested_braces(self, driver):
        """Functions with nested braces (if-blocks) must still parse."""
        html = _build_status_html().replace(
            "function InitDsTableTagValue()\n{",
            "function InitDsTableTagValue()\n{\n    if (true) { console.log('ok'); }",
        )
        driver._status_html = html
        data = driver.get_docsis_data()
        assert len(data["channelDs"]["docsis30"]) == 32


# -- Analyzer integration --

class TestAnalyzerIntegration:
    def test_full_pipeline(self, mock_status):
        """Verify CM3000 output feeds cleanly into the analyzer."""
        from app.analyzer import analyze
        data = mock_status.get_docsis_data()
        result = analyze(data)

        # 32 QAM + 2 OFDM = 34 downstream
        assert result["summary"]["ds_total"] == 34
        # 4 ATDMA + 1 OFDMA = 5 upstream
        assert result["summary"]["us_total"] == 5
        assert result["summary"]["health"] in ("good", "marginal", "poor", "critical")
        assert len(result["ds_channels"]) == 34
        assert len(result["us_channels"]) == 5

    def test_qam_channels_labeled_docsis30(self, mock_status):
        """QAM channels (from docsis30 bucket) must be DOCSIS 3.0."""
        from app.analyzer import analyze
        data = mock_status.get_docsis_data()
        result = analyze(data)

        # CM3000 OFDM channel IDs (193, 194) are < 200, so filter by
        # known QAM channel IDs from the test data (1-32)
        qam_ids = {ch["channelID"] for ch in data["channelDs"]["docsis30"]}
        qam_ds = [c for c in result["ds_channels"] if c["channel_id"] in qam_ids]
        assert len(qam_ds) == 32
        for ch in qam_ds:
            assert ch["docsis_version"] == "3.0", f"DS QAM ch {ch['channel_id']} should be 3.0"

    def test_ofdm_channels_labeled_docsis31(self, mock_status):
        """OFDM channels (from docsis31 bucket) must be DOCSIS 3.1."""
        from app.analyzer import analyze
        data = mock_status.get_docsis_data()
        result = analyze(data)

        ofdm_ids = {ch["channelID"] for ch in data["channelDs"]["docsis31"]}
        ofdm_ds = [c for c in result["ds_channels"] if c["channel_id"] in ofdm_ids]
        assert len(ofdm_ds) == 2
        for ch in ofdm_ds:
            assert ch["docsis_version"] == "3.1", f"DS OFDM ch {ch['channel_id']} should be 3.1"
