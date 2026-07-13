"""Tests for Hitron CODA modem driver."""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.drivers.hitron import HitronDriver, _DS_MODULATION


# -- Real data from HAR capture (Hitron CODA-56) --

DS_SCQAM_DATA = [
    {"portId": "1", "frequency": "591000000", "modulation": "2",
     "signalStrength": "4.600", "snr": "36.387", "dsoctets": "3134003928",
     "correcteds": "3", "uncorrect": "30", "channelId": "7"},
    {"portId": "2", "frequency": "597000000", "modulation": "2",
     "signalStrength": "4.500", "snr": "36.610", "dsoctets": "3133346060",
     "correcteds": "0", "uncorrect": "0", "channelId": "8"},
    {"portId": "10", "frequency": "279000000", "modulation": "2",
     "signalStrength": "2.900", "snr": "37.356", "dsoctets": "3133401832",
     "correcteds": "30", "uncorrect": "0", "channelId": "1"},
]

US_SCQAM_DATA = [
    {"portId": "1", "frequency": "25900000", "bandwidth": "6400000",
     "modtype": "64QAM", "scdmaMode": "ATDMA", "signalStrength": "35.000",
     "channelId": "6"},
    {"portId": "2", "frequency": "38700000", "bandwidth": "6400000",
     "modtype": "64QAM", "scdmaMode": "ATDMA", "signalStrength": "36.250",
     "channelId": "8"},
]

DS_OFDM_DATA = [
    {"receive": "0", "ffttype": "4K", "Subcarr0freqFreq": " 275600000",
     "plclock": "YES", "ncplock": "YES", "mdc1lock": "YES",
     "plcpower": "3.200001", "SNR": "38", "dsoctets": "40196797211",
     "correcteds": "652068075", "uncorrect": "19"},
    {"receive": "1", "ffttype": "4K", "Subcarr0freqFreq": " 827600000",
     "plclock": "YES", "ncplock": "YES", "mdc1lock": "YES",
     "plcpower": "7.800003", "SNR": "35", "dsoctets": "71640259267",
     "correcteds": "1206776386", "uncorrect": "19"},
]

US_OFDMA_DATA = [
    {"uschindex": "0", "state": "   OPERATE", "frequency": "42000000",
     "digAtten": "    0.1848", "digAttenBo": "    5.6486",
     "channelBw": "   39.2000", "repPower": "   51.6417",
     "repPower1_6": "   37.7500", "fftVal": "2K"},
    {"uschindex": "1", "state": "  DISABLED", "frequency": "0",
     "digAtten": "    0.0000", "digAttenBo": "    0.0000",
     "channelBw": "    0.0000", "repPower": "    0.0000",
     "repPower1_6": "    0.0000", "fftVal": "2K"},
]

INIT_DATA = [
    {"hwInit": "Success", "findDownstream": "Success", "ranging": "Success",
     "dhcp": "Success", "timeOfday": "Success", "downloadCfg": "Success",
     "registration": "Success", "eaeStatus": "Disable",
     "bpiStatus": "AUTH:authorized, TEK:operational",
     "networkAccess": "Permitted", "trafficStatus": "Enable"}
]


@pytest.fixture
def driver():
    return HitronDriver("http://192.168.100.1", "", "")


class TestLogin:
    def test_login_success(self, driver):
        resp = MagicMock(status_code=200)
        resp.json.return_value = INIT_DATA
        with patch.object(driver._session, "get", return_value=resp):
            driver.login()

    def test_login_connection_error(self, driver):
        import requests as req
        with patch.object(driver._session, "get", side_effect=req.ConnectionError("timeout")):
            with pytest.raises(RuntimeError, match="Hitron connection failed"):
                driver.login()


class TestDownstreamSCQAM:
    def test_parse_channels(self, driver):
        resp = MagicMock(status_code=200)
        resp.json.return_value = DS_SCQAM_DATA
        with patch.object(driver._session, "get", return_value=resp):
            channels = driver._fetch_ds_scqam()

        assert len(channels) == 3
        ch = channels[0]
        assert ch["channelID"] == 7
        assert ch["frequency"] == "591 MHz"
        assert ch["powerLevel"] == 4.6
        assert ch["modulation"] == "256QAM"
        assert ch["mer"] == 36.387
        assert ch["mse"] == -36.387
        assert ch["corrErrors"] == 3
        assert ch["nonCorrErrors"] == 30

    def test_modulation_mapping(self):
        assert _DS_MODULATION[0] == "16QAM"
        assert _DS_MODULATION[1] == "64QAM"
        assert _DS_MODULATION[2] == "256QAM"
        assert _DS_MODULATION[3] == "1024QAM"
        assert _DS_MODULATION[6] == "QPSK"


class TestUpstreamSCQAM:
    def test_parse_channels(self, driver):
        resp = MagicMock(status_code=200)
        resp.json.return_value = US_SCQAM_DATA
        with patch.object(driver._session, "get", return_value=resp):
            channels = driver._fetch_us_scqam()

        assert len(channels) == 2
        ch = channels[0]
        assert ch["channelID"] == 6
        assert ch["frequency"] == "25.9 MHz"
        assert ch["powerLevel"] == 35.0
        assert ch["modulation"] == "64QAM"
        assert ch["multiplex"] == "ATDMA"


class TestDownstreamOFDM:
    def test_parse_locked_channels(self, driver):
        resp = MagicMock(status_code=200)
        resp.json.return_value = DS_OFDM_DATA
        with patch.object(driver._session, "get", return_value=resp):
            channels = driver._fetch_ds_ofdm()

        assert len(channels) == 2
        ch = channels[0]
        assert ch["channelID"] == 0
        assert ch["type"] == "OFDM"
        assert ch["frequency"] == "275.6 MHz"
        assert ch["powerLevel"] == pytest.approx(3.200001)
        assert ch["mer"] == 38.0
        assert ch["corrErrors"] == 652068075
        assert ch["nonCorrErrors"] == 19

    def test_skip_unlocked_ofdm(self, driver):
        unlocked = [dict(DS_OFDM_DATA[0], plclock="NO")]
        resp = MagicMock(status_code=200)
        resp.json.return_value = unlocked
        with patch.object(driver._session, "get", return_value=resp):
            channels = driver._fetch_ds_ofdm()
        assert len(channels) == 0


class TestUpstreamOFDMA:
    def test_parse_operating_channels(self, driver):
        resp = MagicMock(status_code=200)
        resp.json.return_value = US_OFDMA_DATA
        with patch.object(driver._session, "get", return_value=resp):
            channels = driver._fetch_us_ofdma()

        # Only OPERATE state, DISABLED is skipped
        assert len(channels) == 1
        ch = channels[0]
        assert ch["channelID"] == 0
        assert ch["type"] == "OFDMA"
        assert ch["frequency"] == "42 MHz"
        assert ch["powerLevel"] == pytest.approx(37.75)

    def test_missing_1_6_mhz_report_power_stays_unsupported(self, driver, caplog):
        operating = [dict(US_OFDMA_DATA[0])]
        del operating[0]["repPower1_6"]
        resp = MagicMock(status_code=200)
        resp.json.return_value = operating

        with patch.object(driver._session, "get", return_value=resp):
            channels = driver._fetch_us_ofdma()

        assert channels[0]["powerLevel"] is None
        assert "missing repPower1_6" in caplog.text

    @pytest.mark.parametrize("value", [None, "", "N/A", "nan", "inf", "-inf", []])
    def test_invalid_1_6_mhz_report_power_stays_unsupported(self, driver, value):
        operating = [dict(US_OFDMA_DATA[0], repPower1_6=value)]
        resp = MagicMock(status_code=200)
        resp.json.return_value = operating

        with patch.object(driver._session, "get", return_value=resp):
            channels = driver._fetch_us_ofdma()

        assert channels[0]["powerLevel"] is None

    def test_skip_disabled_ofdma(self, driver):
        disabled = [dict(US_OFDMA_DATA[1])]
        resp = MagicMock(status_code=200)
        resp.json.return_value = disabled
        with patch.object(driver._session, "get", return_value=resp):
            channels = driver._fetch_us_ofdma()
        assert len(channels) == 0


class TestGetDocsisData:
    def test_full_structure(self, driver):
        def mock_get(url, **kwargs):
            resp = MagicMock(status_code=200)
            if "dsinfo" in url:
                resp.json.return_value = DS_SCQAM_DATA
            elif "usinfo" in url:
                resp.json.return_value = US_SCQAM_DATA
            elif "dsofdminfo" in url:
                resp.json.return_value = DS_OFDM_DATA
            elif "usofdminfo" in url:
                resp.json.return_value = US_OFDMA_DATA
            else:
                resp.json.return_value = []
            return resp

        with patch.object(driver._session, "get", side_effect=mock_get):
            data = driver.get_docsis_data()

        assert len(data["channelDs"]["docsis30"]) == 3
        assert len(data["channelDs"]["docsis31"]) == 2
        assert len(data["channelUs"]["docsis30"]) == 2
        assert len(data["channelUs"]["docsis31"]) == 1


class TestDeviceInfo:
    def test_returns_hitron_info(self, driver):
        info = driver.get_device_info()
        assert info["manufacturer"] == "Hitron"
        assert info["model"] == "CODA-56"


class TestConnectionInfo:
    def test_returns_empty(self, driver):
        assert driver.get_connection_info() == {}


class TestHelpers:
    def test_hz_to_mhz_integer(self):
        assert HitronDriver._hz_to_mhz("591000000") == "591 MHz"

    def test_hz_to_mhz_decimal(self):
        assert HitronDriver._hz_to_mhz("275600000") == "275.6 MHz"

    def test_hz_to_mhz_with_whitespace(self):
        assert HitronDriver._hz_to_mhz(" 275600000") == "275.6 MHz"

    def test_hz_to_mhz_invalid(self):
        assert HitronDriver._hz_to_mhz("invalid") == "invalid"

    def test_empty_endpoint_returns_empty_list(self, driver):
        resp = MagicMock(status_code=200)
        resp.json.return_value = []
        with patch.object(driver._session, "get", return_value=resp):
            assert driver._fetch_ds_scqam() == []

    def test_malformed_row_skipped(self, driver):
        bad_data = [{"portId": "1", "frequency": "bad"}]  # missing fields
        resp = MagicMock(status_code=200)
        resp.json.return_value = bad_data
        with patch.object(driver._session, "get", return_value=resp):
            channels = driver._fetch_ds_scqam()
        assert len(channels) == 0
