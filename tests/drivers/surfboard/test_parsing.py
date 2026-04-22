"""Tests for SURFboard channel parsing and derived values."""

import pytest
from unittest.mock import patch, MagicMock
from app.drivers.surfboard import SurfboardDriver
from ._data import HNAP_LOGIN_PHASE1, HNAP_LOGIN_PHASE2

class TestDownstreamSCQAM:
    def test_channel_count(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        assert len(data["channelDs"]["docsis30"]) == 32

    def test_first_channel_fields(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        ch = data["channelDs"]["docsis30"][0]
        assert ch["channelID"] == 43
        assert ch["frequency"] == "705 MHz"
        assert ch["powerLevel"] == 0.0
        assert ch["mer"] == 40.9
        assert ch["mse"] == -40.9
        assert ch["modulation"] == "256QAM"
        assert ch["corrErrors"] == 31
        assert ch["nonCorrErrors"] == 0

    def test_leading_space_power_parsed(self, mock_hnap):
        """Power values with leading space (' 0.0') parse correctly."""
        data = mock_hnap.get_docsis_data()
        ch = data["channelDs"]["docsis30"][0]
        assert ch["powerLevel"] == 0.0

    def test_negative_power(self, mock_hnap):
        """Channels with negative power values."""
        data = mock_hnap.get_docsis_data()
        # Channel 17 (index 16) has power -0.1
        ch = data["channelDs"]["docsis30"][16]
        assert ch["powerLevel"] == -0.1

    def test_frequency_conversion(self, mock_hnap):
        """Hz values are converted to MHz."""
        data = mock_hnap.get_docsis_data()
        ch = data["channelDs"]["docsis30"][0]
        assert ch["frequency"] == "705 MHz"
        # 29.2 MHz would be fractional
        freqs = [ch["frequency"] for ch in data["channelDs"]["docsis30"]]
        assert all("MHz" in f for f in freqs)

    def test_last_channel(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        ch = data["channelDs"]["docsis30"][-1]
        assert ch["channelID"] == 42
        assert ch["frequency"] == "645 MHz"


# -- Downstream OFDM --

class TestDownstreamOFDM:
    def test_ofdm_in_docsis31(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        assert len(data["channelDs"]["docsis31"]) == 1

    def test_ofdm_channel_fields(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        ch = data["channelDs"]["docsis31"][0]
        assert ch["channelID"] == 193
        assert ch["type"] == "OFDM"
        assert ch["frequency"] == "957 MHz"
        assert ch["powerLevel"] == 0.1
        assert ch["mer"] == 43.0
        assert ch["mse"] is None
        assert ch["corrErrors"] == 2467857853
        assert ch["nonCorrErrors"] == 7894


# -- Upstream SC-QAM --

class TestUpstreamSCQAM:
    def test_locked_count(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        assert len(data["channelUs"]["docsis30"]) == 4

    def test_first_channel_fields(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        ch = data["channelUs"]["docsis30"][0]
        assert ch["channelID"] == 3
        assert ch["frequency"] == "29.2 MHz"
        assert ch["powerLevel"] == 46.5
        assert ch["modulation"] == "SC-QAM"
        assert ch["multiplex"] == "SC-QAM"

    def test_all_upstream_channel_ids(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        ids = [ch["channelID"] for ch in data["channelUs"]["docsis30"]]
        assert ids == [3, 4, 2, 1]


# -- Upstream OFDMA --

class TestUpstreamOFDMA:
    def test_ofdma_in_docsis31(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        assert len(data["channelUs"]["docsis31"]) == 1

    def test_ofdma_channel_fields(self, mock_hnap):
        data = mock_hnap.get_docsis_data()
        ch = data["channelUs"]["docsis31"][0]
        assert ch["channelID"] == 41
        assert ch["type"] == "OFDMA"
        assert ch["frequency"] == "36.2 MHz"
        assert ch["powerLevel"] == 43.8
        assert ch["modulation"] == "OFDMA"
        assert ch["multiplex"] == ""


# -- Device info --

class TestDeviceInfo:
    def test_model_name(self, mock_hnap):
        info = mock_hnap.get_device_info()
        assert info["manufacturer"] == "Arris"
        assert info["model"] == "S34"

    def test_sw_version(self, mock_hnap):
        info = mock_hnap.get_device_info()
        assert info["sw_version"] == "2.5.0.1-2-GA"

    def test_connection_info_empty(self, driver):
        assert driver.get_connection_info() == {}

    def test_device_info_fallback_on_error(self, driver):
        with patch.object(driver, "_hnap_post", side_effect=Exception("network")):
            info = driver.get_device_info()
            assert info["manufacturer"] == "Arris"
            assert info["model"] == ""

    def test_device_info_error_preserves_session(self, driver):
        """get_device_info failure does not kill the session so get_docsis_data can still work."""
        driver._logged_in = True
        with patch.object(driver, "_hnap_post", side_effect=Exception("500")):
            driver.get_device_info()
        assert driver._logged_in is True


class TestDataFetchRetry:
    def test_retry_on_http_500(self, driver):
        """get_docsis_data retries with fresh login on HTTP 500."""
        import requests as req

        calls = []

        def mock_fetch():
            calls.append(1)
            if len(calls) == 1:
                resp = MagicMock()
                resp.status_code = 500
                raise req.HTTPError(response=resp)
            return {
                "channelDs": {"docsis30": [], "docsis31": []},
                "channelUs": {"docsis30": [], "docsis31": []},
            }

        def mock_login_post(action, body, **kwargs):
            if body.get("Login", {}).get("Action") == "request":
                return HNAP_LOGIN_PHASE1
            return HNAP_LOGIN_PHASE2

        with patch.object(driver, "_fetch_docsis_data", side_effect=mock_fetch), \
             patch.object(driver, "_hnap_post", side_effect=mock_login_post):
            data = driver.get_docsis_data()

        assert len(calls) == 2
        assert "channelDs" in data

    def test_no_retry_on_success(self, mock_hnap):
        """Successful data fetch does not trigger retry logic."""
        data = mock_hnap.get_docsis_data()
        assert len(data["channelDs"]["docsis30"]) == 32


# -- Value helpers --

class TestValueHelpers:
    def test_hz_to_mhz_integer(self):
        assert SurfboardDriver._hz_to_mhz(705000000) == "705 MHz"

    def test_hz_to_mhz_decimal(self):
        assert SurfboardDriver._hz_to_mhz(29200000) == "29.2 MHz"

    def test_hz_to_mhz_zero(self):
        assert SurfboardDriver._hz_to_mhz(0) == "0 MHz"

    def test_hz_to_mhz_fractional(self):
        assert SurfboardDriver._hz_to_mhz(36200000) == "36.2 MHz"

    def test_normalize_modulation(self):
        assert SurfboardDriver._normalize_modulation("256QAM") == "256QAM"
        assert SurfboardDriver._normalize_modulation(" OFDM PLC ") == "OFDM PLC"
        assert SurfboardDriver._normalize_modulation("") == ""


# -- Empty / edge cases --

class TestEdgeCases:
    def test_empty_downstream(self, driver):
        with patch.object(driver, "_hnap_post", return_value={
            "GetMultipleHNAPsResponse": {
                "GetCustomerStatusDownstreamChannelInfoResponse": {"CustomerConnDownstreamChannel": ""},
                "GetCustomerStatusUpstreamChannelInfoResponse": {"CustomerConnUpstreamChannel": ""},
            }
        }):
            data = driver.get_docsis_data()
            assert data["channelDs"]["docsis30"] == []
            assert data["channelDs"]["docsis31"] == []
            assert data["channelUs"]["docsis30"] == []
            assert data["channelUs"]["docsis31"] == []

    def test_unlocked_channels_skipped(self, driver):
        raw = "1^Not Locked^256QAM^99^705000000^0.0^40.9^0^0^"
        with patch.object(driver, "_hnap_post", return_value={
            "GetMultipleHNAPsResponse": {
                "GetCustomerStatusDownstreamChannelInfoResponse": {"CustomerConnDownstreamChannel": raw},
                "GetCustomerStatusUpstreamChannelInfoResponse": {"CustomerConnUpstreamChannel": ""},
            }
        }):
            data = driver.get_docsis_data()
            assert len(data["channelDs"]["docsis30"]) == 0

    def test_malformed_channel_skipped(self, driver):
        raw = "1^Locked^256QAM^43^"  # Too few fields
        with patch.object(driver, "_hnap_post", return_value={
            "GetMultipleHNAPsResponse": {
                "GetCustomerStatusDownstreamChannelInfoResponse": {"CustomerConnDownstreamChannel": raw},
                "GetCustomerStatusUpstreamChannelInfoResponse": {"CustomerConnUpstreamChannel": ""},
            }
        }):
            data = driver.get_docsis_data()
            assert len(data["channelDs"]["docsis30"]) == 0


# -- Analyzer integration --

class TestAnalyzerIntegration:
    def test_full_pipeline(self, mock_hnap):
        """Verify SURFboard output feeds cleanly into the analyzer."""
        from app.analyzer import analyze
        data = mock_hnap.get_docsis_data()
        result = analyze(data)

        # 32 SC-QAM + 1 OFDM = 33 downstream
        assert result["summary"]["ds_total"] == 33
        # 4 SC-QAM + 1 OFDMA = 5 upstream
        assert result["summary"]["us_total"] == 5
        assert result["summary"]["health"] in ("good", "tolerated", "marginal", "poor", "critical")
        assert len(result["ds_channels"]) == 33
        assert len(result["us_channels"]) == 5

    def test_qam_channels_labeled_docsis30(self, mock_hnap):
        from app.analyzer import analyze
        data = mock_hnap.get_docsis_data()
        result = analyze(data)

        qam_ids = {ch["channelID"] for ch in data["channelDs"]["docsis30"]}
        qam_ds = [c for c in result["ds_channels"] if c["channel_id"] in qam_ids]
        assert len(qam_ds) == 32
        for ch in qam_ds:
            assert ch["docsis_version"] == "3.0"

    def test_ofdm_channels_labeled_docsis31(self, mock_hnap):
        from app.analyzer import analyze
        data = mock_hnap.get_docsis_data()
        result = analyze(data)

        ofdm_ids = {ch["channelID"] for ch in data["channelDs"]["docsis31"]}
        ofdm_ds = [c for c in result["ds_channels"] if c["channel_id"] in ofdm_ids]
        assert len(ofdm_ds) == 1
        for ch in ofdm_ds:
            assert ch["docsis_version"] == "3.1"


# -- Session lifecycle (RELOAD handling) --

class TestSessionLifecycle:
    def test_reload_retry_without_fresh_session(self, driver):
        """First RELOAD retries on same session object (no _fresh_session)."""
        session_before = driver._session
        calls = []

        def mock_do_login():
            calls.append(1)
            if len(calls) == 1:
                raise RuntimeError("SURFboard login failed: no challenge received")

        with patch.object(driver, "_do_login", side_effect=mock_do_login), \
             patch("app.drivers.surfboard.time"):
            driver.login()

        assert len(calls) == 2
        assert driver._session is session_before
        assert driver._logged_in is True

    def test_reload_fresh_session_on_second_attempt(self, driver):
        """Second RELOAD creates a fresh session before retrying."""
        session_before = driver._session
        calls = []

        def mock_do_login():
            calls.append(1)
            if len(calls) <= 2:
                raise RuntimeError("SURFboard login failed: no challenge received")

        with patch.object(driver, "_do_login", side_effect=mock_do_login), \
             patch("app.drivers.surfboard.time"):
            driver.login()

        assert len(calls) == 3
        assert driver._session is not session_before
        assert driver._logged_in is True

    def test_reload_all_attempts_exhausted(self, driver):
        """Three RELOADs raises RuntimeError."""
        def mock_do_login():
            raise RuntimeError("SURFboard login failed: no challenge received")

        with patch.object(driver, "_do_login", side_effect=mock_do_login), \
             patch("app.drivers.surfboard.time"):
            with pytest.raises(RuntimeError, match="no challenge received"):
                driver.login()

    def test_session_reused_across_polls(self, driver):
        """login() no-op when already logged in, session object unchanged."""
        driver._logged_in = True
        session_before = driver._session
        calls = []

        with patch.object(driver, "_do_login", side_effect=lambda: calls.append(1)):
            driver.login()

        assert calls == []
        assert driver._session is session_before


# -- Multi-firmware namespace --

