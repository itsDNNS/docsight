"""Tests for modem driver interface and loader."""

import pytest
from unittest.mock import Mock, patch
from app.drivers.interface import Driver
from app.drivers.loader import load_driver, get_available_drivers, AVAILABLE_DRIVERS
from app.drivers.fritzbox import FritzBoxDriver


class TestDriverInterface:
    """Test the abstract Driver interface."""

    def test_driver_is_abstract(self):
        """Driver interface cannot be instantiated directly."""
        with pytest.raises(TypeError):
            Driver()

    def test_driver_requires_login_implementation(self):
        """Driver subclass must implement login()."""
        class IncompleteDriver(Driver):
            def get_docsis_data(self, session, url):
                pass
            def get_device_info(self, session, url):
                pass

        with pytest.raises(TypeError):
            IncompleteDriver()

    def test_driver_requires_get_docsis_data_implementation(self):
        """Driver subclass must implement get_docsis_data()."""
        class IncompleteDriver(Driver):
            def login(self, url, username, password, timeout=10):
                pass
            def get_device_info(self, session, url):
                pass

        with pytest.raises(TypeError):
            IncompleteDriver()

    def test_driver_requires_get_device_info_implementation(self):
        """Driver subclass must implement get_device_info()."""
        class IncompleteDriver(Driver):
            def login(self, url, username, password, timeout=10):
                pass
            def get_docsis_data(self, session, url):
                pass

        with pytest.raises(TypeError):
            IncompleteDriver()

    def test_complete_driver_can_be_instantiated(self):
        """Driver with all required methods can be instantiated."""
        class CompleteDriver(Driver):
            def login(self, url, username, password, timeout=10):
                return "session"
            def get_docsis_data(self, session, url):
                return {}
            def get_device_info(self, session, url):
                return {}

        driver = CompleteDriver()
        assert isinstance(driver, Driver)

    def test_get_connection_info_is_optional(self):
        """get_connection_info() has default implementation returning None."""
        class MinimalDriver(Driver):
            def login(self, url, username, password, timeout=10):
                return "session"
            def get_docsis_data(self, session, url):
                return {}
            def get_device_info(self, session, url):
                return {}

        driver = MinimalDriver()
        result = driver.get_connection_info("session", "http://example.com")
        assert result is None


class TestDriverLoader:
    """Test the driver loader functionality."""

    def test_load_fritzbox_driver(self):
        """load_driver('fritzbox') returns FritzBoxDriver instance."""
        driver = load_driver("fritzbox")
        assert driver is not None
        assert isinstance(driver, FritzBoxDriver)
        assert isinstance(driver, Driver)

    def test_load_driver_case_insensitive(self):
        """Driver loading is case-insensitive."""
        driver1 = load_driver("fritzbox")
        driver2 = load_driver("FRITZBOX")
        driver3 = load_driver("FritzBox")
        
        assert driver1 is not None
        assert driver2 is not None
        assert driver3 is not None
        assert type(driver1) == type(driver2) == type(driver3)

    def test_load_unknown_driver_returns_none(self):
        """load_driver() returns None for unknown modem type."""
        driver = load_driver("unknown_modem")
        assert driver is None

    def test_load_driver_empty_string_returns_none(self):
        """load_driver('') returns None."""
        driver = load_driver("")
        assert driver is None

    def test_load_driver_none_returns_none(self):
        """load_driver(None) returns None."""
        driver = load_driver(None)
        assert driver is None

    def test_load_vodafone_driver(self):
        """load_driver('vodafone') returns VodafoneStationDriver instance."""
        driver = load_driver("vodafone")
        assert driver is not None
        assert isinstance(driver, Driver)
        assert driver.__class__.__name__ == "VodafoneStationDriver"

    def test_get_available_drivers(self):
        """get_available_drivers() returns list of driver names."""
        drivers = get_available_drivers()
        assert isinstance(drivers, list)
        assert "fritzbox" in drivers
        assert "vodafone" in drivers
        assert len(drivers) >= 2

    def test_available_drivers_registry(self):
        """AVAILABLE_DRIVERS contains fritzbox and vodafone entries."""
        assert "fritzbox" in AVAILABLE_DRIVERS
        assert AVAILABLE_DRIVERS["fritzbox"] == "app.drivers.fritzbox.FritzBoxDriver"
        assert "vodafone" in AVAILABLE_DRIVERS
        assert AVAILABLE_DRIVERS["vodafone"] == "app.drivers.vodafone.VodafoneStationDriver"

    @patch('app.drivers.loader.importlib.import_module')
    def test_load_driver_handles_import_error(self, mock_import):
        """load_driver() handles import errors gracefully."""
        mock_import.side_effect = ImportError("Module not found")
        driver = load_driver("fritzbox")
        assert driver is None

    @patch('app.drivers.loader.importlib.import_module')
    def test_load_driver_handles_attribute_error(self, mock_import):
        """load_driver() handles missing class attribute."""
        mock_module = Mock()
        del mock_module.FritzBoxDriver  # Simulate missing class
        mock_import.return_value = mock_module
        
        driver = load_driver("fritzbox")
        assert driver is None

    @patch('app.drivers.loader.importlib.import_module')
    def test_load_driver_handles_instantiation_error(self, mock_import):
        """load_driver() handles driver instantiation errors."""
        mock_module = Mock()
        mock_module.FritzBoxDriver.side_effect = Exception("Init failed")
        mock_import.return_value = mock_module
        
        driver = load_driver("fritzbox")
        assert driver is None


class TestFritzBoxDriver:
    """Test FritzBoxDriver implementation."""

    def test_fritzbox_driver_implements_interface(self):
        """FritzBoxDriver implements Driver interface."""
        driver = FritzBoxDriver()
        assert isinstance(driver, Driver)

    def test_fritzbox_driver_has_required_methods(self):
        """FritzBoxDriver has all required methods."""
        driver = FritzBoxDriver()
        assert hasattr(driver, 'login')
        assert hasattr(driver, 'get_docsis_data')
        assert hasattr(driver, 'get_device_info')
        assert hasattr(driver, 'get_connection_info')
        assert callable(driver.login)
        assert callable(driver.get_docsis_data)
        assert callable(driver.get_device_info)
        assert callable(driver.get_connection_info)

    @patch('app.drivers.fritzbox.requests.get')
    def test_login_success_pbkdf2(self, mock_get):
        """FritzBox login succeeds with PBKDF2 challenge."""
        # Mock challenge response
        challenge_xml = '''<?xml version="1.0"?>
        <SessionInfo>
            <Challenge>2$60000$abc123$60000$def456</Challenge>
        </SessionInfo>'''
        
        # Mock SID response
        sid_xml = '''<?xml version="1.0"?>
        <SessionInfo>
            <SID>1234567890abcdef</SID>
        </SessionInfo>'''
        
        mock_response1 = Mock()
        mock_response1.text = challenge_xml
        mock_response1.raise_for_status = Mock()
        
        mock_response2 = Mock()
        mock_response2.text = sid_xml
        mock_response2.raise_for_status = Mock()
        
        mock_get.side_effect = [mock_response1, mock_response2]
        
        driver = FritzBoxDriver()
        sid = driver.login("http://192.168.178.1", "admin", "password")
        
        assert sid == "1234567890abcdef"
        assert mock_get.call_count == 2

    @patch('app.drivers.fritzbox.requests.get')
    def test_login_success_md5(self, mock_get):
        """FritzBox login succeeds with MD5 challenge (legacy)."""
        # Mock challenge response (no "2$" prefix = MD5)
        challenge_xml = '''<?xml version="1.0"?>
        <SessionInfo>
            <Challenge>abc123def456</Challenge>
        </SessionInfo>'''
        
        # Mock SID response
        sid_xml = '''<?xml version="1.0"?>
        <SessionInfo>
            <SID>fedcba0987654321</SID>
        </SessionInfo>'''
        
        mock_response1 = Mock()
        mock_response1.text = challenge_xml
        mock_response1.raise_for_status = Mock()
        
        mock_response2 = Mock()
        mock_response2.text = sid_xml
        mock_response2.raise_for_status = Mock()
        
        mock_get.side_effect = [mock_response1, mock_response2]
        
        driver = FritzBoxDriver()
        sid = driver.login("http://192.168.178.1", "admin", "password")
        
        assert sid == "fedcba0987654321"

    @patch('app.drivers.fritzbox.requests.get')
    def test_login_failure_invalid_sid(self, mock_get):
        """FritzBox login fails with invalid SID (all zeros)."""
        challenge_xml = '''<?xml version="1.0"?>
        <SessionInfo>
            <Challenge>abc123</Challenge>
        </SessionInfo>'''
        
        sid_xml = '''<?xml version="1.0"?>
        <SessionInfo>
            <SID>0000000000000000</SID>
        </SessionInfo>'''
        
        mock_response1 = Mock()
        mock_response1.text = challenge_xml
        mock_response1.raise_for_status = Mock()
        
        mock_response2 = Mock()
        mock_response2.text = sid_xml
        mock_response2.raise_for_status = Mock()
        
        mock_get.side_effect = [mock_response1, mock_response2]
        
        driver = FritzBoxDriver()
        sid = driver.login("http://192.168.178.1", "admin", "wrong_password")
        
        assert sid is None

    @patch('app.drivers.fritzbox.requests.get')
    def test_login_handles_connection_error(self, mock_get):
        """FritzBox login handles connection errors."""
        mock_get.side_effect = Exception("Connection refused")
        
        driver = FritzBoxDriver()
        sid = driver.login("http://192.168.178.1", "admin", "password")
        
        assert sid is None

    @patch('app.drivers.fritzbox.requests.post')
    def test_get_docsis_data(self, mock_post):
        """FritzBox get_docsis_data returns channel data."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "ds_channels": [{"channel_id": 1}],
                "us_channels": [{"channel_id": 1}]
            }
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        driver = FritzBoxDriver()
        data = driver.get_docsis_data("test_sid", "http://192.168.178.1")
        
        assert "ds_channels" in data
        assert "us_channels" in data
        assert mock_post.called

    @patch('app.drivers.fritzbox.requests.post')
    def test_get_device_info(self, mock_post):
        """FritzBox get_device_info returns device information."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "fritzos": {
                    "Productname": "FRITZ!Box 6591 Cable",
                    "nspver": "7.57",
                    "Uptime": "123456"
                }
            }
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        driver = FritzBoxDriver()
        info = driver.get_device_info("test_sid", "http://192.168.178.1")
        
        assert info["model"] == "FRITZ!Box 6591 Cable"
        assert info["sw_version"] == "7.57"
        assert info["uptime_seconds"] == 123456

    @patch('app.drivers.fritzbox.requests.post')
    def test_get_device_info_handles_error(self, mock_post):
        """FritzBox get_device_info returns defaults on error."""
        mock_post.side_effect = Exception("Connection error")
        
        driver = FritzBoxDriver()
        info = driver.get_device_info("test_sid", "http://192.168.178.1")
        
        assert info["model"] == "FRITZ!Box"
        assert info["sw_version"] == ""

    @patch('app.drivers.fritzbox.requests.post')
    def test_get_connection_info(self, mock_post):
        """FritzBox get_connection_info returns connection data."""
        mock_response = Mock()
        mock_response.json.return_value = {
            "data": {
                "connections": [{
                    "downstream": 1000000,
                    "upstream": 50000,
                    "medium": "cable"
                }]
            }
        }
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        driver = FritzBoxDriver()
        info = driver.get_connection_info("test_sid", "http://192.168.178.1")
        
        assert info["max_downstream_kbps"] == 1000000
        assert info["max_upstream_kbps"] == 50000
        assert info["connection_type"] == "cable"

    @patch('app.drivers.fritzbox.requests.post')
    def test_get_connection_info_no_connections(self, mock_post):
        """FritzBox get_connection_info returns None when no connections."""
        mock_response = Mock()
        mock_response.json.return_value = {"data": {"connections": []}}
        mock_response.raise_for_status = Mock()
        mock_post.return_value = mock_response
        
        driver = FritzBoxDriver()
        info = driver.get_connection_info("test_sid", "http://192.168.178.1")
        
        assert info is None

    @patch('app.drivers.fritzbox.requests.post')
    def test_get_connection_info_handles_error(self, mock_post):
        """FritzBox get_connection_info returns None on error."""
        mock_post.side_effect = Exception("Connection error")
        
        driver = FritzBoxDriver()
        info = driver.get_connection_info("test_sid", "http://192.168.178.1")
        
        assert info is None
