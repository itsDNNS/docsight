"""Tests for Vodafone Station driver."""

from unittest.mock import Mock, patch
from app.drivers.vodafone import VodafoneStationDriver
from app.drivers.interface import Driver


class TestVodafoneStationDriver:
    """Test VodafoneStationDriver implementation."""

    def test_vodafone_driver_implements_interface(self):
        """VodafoneStationDriver implements Driver interface."""
        driver = VodafoneStationDriver()
        assert isinstance(driver, Driver)

    def test_vodafone_driver_has_required_methods(self):
        """VodafoneStationDriver has all required methods."""
        driver = VodafoneStationDriver()
        assert hasattr(driver, 'login')
        assert hasattr(driver, 'get_docsis_data')
        assert hasattr(driver, 'get_device_info')
        assert hasattr(driver, 'get_connection_info')
        assert callable(driver.login)
        assert callable(driver.get_docsis_data)
        assert callable(driver.get_device_info)
        assert callable(driver.get_connection_info)

    @patch('app.drivers.vodafone.AES')
    @patch('app.drivers.vodafone.requests.Session')
    def test_login_success(self, mock_session_class, mock_aes):
        """Vodafone Station login succeeds with valid credentials."""
        # Mock session instance
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        # Mock AES cipher for encryption
        mock_cipher_encrypt = Mock()
        mock_cipher_encrypt.encrypt.return_value = b'encrypted_payload'
        mock_cipher_encrypt.digest.return_value = b'auth_tag_16bytes'
        
        # Mock AES cipher for decryption - return 32 bytes of ASCII-safe data
        mock_cipher_decrypt = Mock()
        mock_cipher_decrypt.decrypt.return_value = b'a' * 32  # 32 ASCII bytes for CSRF nonce
        
        # AES.new returns different cipher instances
        mock_aes.new.side_effect = [mock_cipher_encrypt, mock_cipher_decrypt]
        mock_aes.MODE_CCM = 9  # Actual value doesn't matter for mock
        
        # Mock login page response
        login_page_response = Mock()
        login_page_response.text = """
        <script>
        var currentSessionId = 'abc123session';
        var myIv = '0123456789abcdef';
        var mySalt = 'fedcba9876543210';
        </script>
        """
        login_page_response.raise_for_status = Mock()
        
        # Mock password post response
        password_response = Mock()
        password_response.text = '{"p_status":"AdminMatch", "encryptData": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}'
        password_response.json.return_value = {
            "p_status": "AdminMatch",
            "encryptData": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        }
        password_response.raise_for_status = Mock()
        
        # Mock session set response
        session_response = Mock()
        session_response.raise_for_status = Mock()
        
        # Configure mock session methods
        mock_session.get.return_value = login_page_response
        mock_session.post.side_effect = [password_response, session_response]
        mock_session.headers = {}
        
        driver = VodafoneStationDriver()
        result = driver.login("http://192.168.0.1", "admin", "password")
        
        # Should return the session object
        assert result is not None
        assert result == mock_session
        assert mock_session.get.called
        assert mock_session.post.call_count == 2

    @patch('app.drivers.vodafone.requests.Session')
    def test_login_failure_no_admin_match(self, mock_session_class):
        """Vodafone Station login fails when AdminMatch not in response."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        login_page_response = Mock()
        login_page_response.text = """
        <script>
        var currentSessionId = 'abc123';
        var myIv = '0123456789abcdef01234567';
        var mySalt = 'fedcba9876543210';
        </script>
        """
        login_page_response.raise_for_status = Mock()
        
        password_response = Mock()
        password_response.text = '{"error": "invalid"}'
        password_response.raise_for_status = Mock()
        
        mock_session.get.return_value = login_page_response
        mock_session.post.return_value = password_response
        
        driver = VodafoneStationDriver()
        result = driver.login("http://192.168.0.1", "admin", "wrong_password")
        
        assert result is None

    @patch('app.drivers.vodafone.requests.Session')
    def test_login_handles_connection_error(self, mock_session_class):
        """Vodafone Station login handles connection errors."""
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        mock_session.get.side_effect = Exception("Connection refused")
        
        driver = VodafoneStationDriver()
        result = driver.login("http://192.168.0.1", "admin", "password")
        
        assert result is None

    def test_get_docsis_data_transforms_format(self):
        """get_docsis_data transforms Vodafone format to DOCSight format."""
        mock_session = Mock()
        mock_response = Mock()
        # Use single-line format to match regex pattern
        mock_response.text = '<script>var json_dsData = [{"ChannelID": "1", "ChannelType": "SC-QAM", "Frequency": "602000000", "PowerLevel": "3.2 dBmV / 320 dBuV", "SNRLevel": "37.5", "Modulation": "256QAM", "LockStatus": "Locked"}, {"ChannelID": "33", "ChannelType": "OFDM", "Frequency": "602~698", "PowerLevel": "5.1 dBmV / 510 dBuV", "SNRLevel": "40.2", "Modulation": "4096QAM", "LockStatus": "ACTIVE"}]; var json_usData = [{"ChannelID": "1", "ChannelType": "SC-QAM", "Frequency": "37000000", "PowerLevel": "42.0 dBmV / 4200 dBuV", "Modulation": "64QAM", "LockStatus": "SUCCESS"}];</script>'
        mock_response.raise_for_status = Mock()
        mock_session.get.return_value = mock_response
        
        driver = VodafoneStationDriver()
        data = driver.get_docsis_data(mock_session, "http://192.168.0.1")
        
        # Check structure
        assert "channelDs" in data
        assert "channelUs" in data
        assert "docsis30" in data["channelDs"]
        assert "docsis31" in data["channelDs"]
        assert "docsis30" in data["channelUs"]
        assert "docsis31" in data["channelUs"]
        
        # Check DOCSIS 3.0 downstream channel
        ds30 = data["channelDs"]["docsis30"]
        assert len(ds30) == 1
        assert ds30[0]["channelID"] == 1
        assert ds30[0]["frequency"] == "602 MHz"
        assert ds30[0]["powerLevel"] == 3.2
        assert ds30[0]["modulation"] == "256QAM"
        assert ds30[0]["mse"] == -37.5  # Negative SNR for DOCSIS 3.0
        
        # Check DOCSIS 3.1 downstream channel
        ds31 = data["channelDs"]["docsis31"]
        assert len(ds31) == 1
        assert ds31[0]["channelID"] == 33
        assert ds31[0]["frequency"] == "602 MHz"  # First part of range
        assert ds31[0]["powerLevel"] == 5.1
        assert ds31[0]["modulation"] == "4096QAM"
        assert ds31[0]["mer"] == 40.2  # MER for DOCSIS 3.1
        
        # Check upstream channel
        us30 = data["channelUs"]["docsis30"]
        assert len(us30) == 1
        assert us30[0]["channelID"] == 1
        assert us30[0]["frequency"] == "37 MHz"
        assert us30[0]["powerLevel"] == 42.0
        assert us30[0]["modulation"] == "64QAM"
        assert us30[0]["multiplex"] == "ATDMA"

    def test_get_docsis_data_handles_missing_data(self):
        """get_docsis_data handles missing or malformed data."""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.text = "<html>No DOCSIS data here</html>"
        mock_response.raise_for_status = Mock()
        mock_session.get.return_value = mock_response
        
        driver = VodafoneStationDriver()
        data = driver.get_docsis_data(mock_session, "http://192.168.0.1")
        
        # Should return empty structure
        assert data["channelDs"]["docsis30"] == []
        assert data["channelDs"]["docsis31"] == []
        assert data["channelUs"]["docsis30"] == []
        assert data["channelUs"]["docsis31"] == []

    def test_get_docsis_data_handles_connection_error(self):
        """get_docsis_data handles connection errors."""
        mock_session = Mock()
        mock_session.get.side_effect = Exception("Connection error")
        
        driver = VodafoneStationDriver()
        data = driver.get_docsis_data(mock_session, "http://192.168.0.1")
        
        # Should return empty structure
        assert data["channelDs"]["docsis30"] == []

    def test_get_device_info(self):
        """get_device_info returns device information."""
        mock_session = Mock()
        mock_response = Mock()
        mock_response.json.return_value = {
            "model": "ARRIS TG3442DE",
            "sw_version": "9.1.1803.311",
            "uptime": 123456
        }
        mock_response.headers = {"content-type": "application/json"}
        mock_response.raise_for_status = Mock()
        mock_session.get.return_value = mock_response
        
        driver = VodafoneStationDriver()
        info = driver.get_device_info(mock_session, "http://192.168.0.1")
        
        assert info["model"] == "ARRIS TG3442DE"
        assert info["sw_version"] == "9.1.1803.311"
        assert info["uptime_seconds"] == 123456

    def test_get_device_info_handles_error(self):
        """get_device_info returns defaults on error."""
        mock_session = Mock()
        mock_session.get.side_effect = Exception("Connection error")
        
        driver = VodafoneStationDriver()
        info = driver.get_device_info(mock_session, "http://192.168.0.1")
        
        assert info["model"] == "Vodafone Station"
        assert info["sw_version"] == ""

    def test_get_connection_info_returns_none(self):
        """get_connection_info returns None (not supported)."""
        mock_session = Mock()
        driver = VodafoneStationDriver()
        info = driver.get_connection_info(mock_session, "http://192.168.0.1")
        
        assert info is None

    def test_transform_handles_ofdma_upstream(self):
        """Transform correctly identifies OFDMA upstream channels as DOCSIS 3.1."""
        driver = VodafoneStationDriver()
        
        upstream_data = [{
            "ChannelID": "5",
            "ChannelType": "OFDMA",
            "Frequency": "23700000",
            "PowerLevel": "45.0 dBmV / 4500 dBuV",
            "Modulation": "1024QAM",
            "LockStatus": "ACTIVE"
        }]
        
        result = driver._transform_to_docsight_format([], upstream_data)
        
        us31 = result["channelUs"]["docsis31"]
        assert len(us31) == 1
        assert us31[0]["channelID"] == 5
        assert us31[0]["multiplex"] == "OFDMA"
        assert us31[0]["type"] == "OFDMA"

    def test_transform_handles_invalid_frequency(self):
        """Transform handles invalid frequency values gracefully."""
        driver = VodafoneStationDriver()
        
        downstream_data = [{
            "ChannelID": "1",
            "ChannelType": "SC-QAM",
            "Frequency": "invalid",
            "PowerLevel": "3.2 dBmV / 320 dBuV",
            "SNRLevel": "37.5",
            "Modulation": "256QAM",
            "LockStatus": "Locked"
        }]
        
        result = driver._transform_to_docsight_format(downstream_data, [])
        
        ds30 = result["channelDs"]["docsis30"]
        assert len(ds30) == 1
        assert ds30[0]["frequency"] == "invalid"  # Falls back to original string

    def test_transform_handles_invalid_power(self):
        """Transform handles invalid power level values gracefully."""
        driver = VodafoneStationDriver()
        
        downstream_data = [{
            "ChannelID": "1",
            "ChannelType": "SC-QAM",
            "Frequency": "602000000",
            "PowerLevel": "invalid",
            "SNRLevel": "37.5",
            "Modulation": "256QAM",
            "LockStatus": "Locked"
        }]
        
        result = driver._transform_to_docsight_format(downstream_data, [])
        
        ds30 = result["channelDs"]["docsis30"]
        assert len(ds30) == 1
        assert ds30[0]["powerLevel"] == 0.0  # Falls back to 0.0
