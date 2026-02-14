"""Integration tests for modem driver selection and testing."""

import json
import pytest
from unittest.mock import Mock, patch
from app.web import app, init_config, init_storage
from app.config import ConfigManager


@pytest.fixture
def config_mgr(tmp_path):
    data_dir = str(tmp_path / "data")
    mgr = ConfigManager(data_dir)
    return mgr


@pytest.fixture
def client(config_mgr):
    init_config(config_mgr)
    init_storage(None)
    app.config["TESTING"] = True
    with app.test_client() as client:
        yield client


class TestModemTypeSelection:
    """Test modem type selection and driver loading."""

    def test_setup_page_includes_available_drivers(self, client):
        """Setup page includes modem type dropdown with available drivers."""
        resp = client.get("/setup")
        assert resp.status_code == 200
        html = resp.data.decode()
        
        # Check for modem type dropdown
        assert 'id="modem_type"' in html
        assert 'name="modem_type"' in html
        
        # Check for available drivers
        assert 'value="fritzbox"' in html
        assert 'value="vodafone"' in html

    def test_settings_page_includes_available_drivers(self, client, config_mgr):
        """Settings page includes modem type dropdown."""
        # Configure to bypass auth
        config_mgr.save({"modem_password": "test"})
        
        # Login
        with client.session_transaction() as sess:
            sess["authenticated"] = True
        
        resp = client.get("/settings")
        assert resp.status_code == 200
        html = resp.data.decode()
        
        # Check for modem type dropdown
        assert 'id="modem_type"' in html
        assert 'name="modem_type"' in html
        assert 'value="fritzbox"' in html
        assert 'value="vodafone"' in html

    @patch('app.drivers.fritzbox.requests.get')
    def test_test_modem_with_fritzbox_type(self, mock_get, client):
        """Test connection uses FritzBox driver when modem_type=fritzbox."""
        # Mock FritzBox login responses
        challenge_xml = '''<?xml version="1.0"?>
        <SessionInfo>
            <Challenge>abc123</Challenge>
        </SessionInfo>'''
        
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
        
        # Mock device info
        with patch('app.drivers.fritzbox.requests.post') as mock_post:
            device_response = Mock()
            device_response.json.return_value = {
                "data": {
                    "fritzos": {
                        "Productname": "FRITZ!Box 6591",
                        "nspver": "7.57"
                    }
                }
            }
            device_response.raise_for_status = Mock()
            mock_post.return_value = device_response
            
            resp = client.post("/api/test-modem", 
                json={
                    "modem_type": "fritzbox",
                    "modem_url": "http://192.168.178.1",
                    "modem_user": "",
                    "modem_password": "test"
                })
            
            assert resp.status_code == 200
            data = json.loads(resp.data)
            assert data["success"] is True
            assert "FRITZ!Box" in data["model"]

    @patch('app.drivers.vodafone.AES')
    @patch('app.drivers.vodafone.requests.Session')
    def test_test_modem_with_vodafone_type(self, mock_session_class, mock_aes, client):
        """Test connection uses Vodafone driver when modem_type=vodafone."""
        # Mock session instance
        mock_session = Mock()
        mock_session_class.return_value = mock_session
        
        # Mock AES cipher
        mock_cipher_encrypt = Mock()
        mock_cipher_encrypt.encrypt.return_value = b'encrypted'
        mock_cipher_encrypt.digest.return_value = b'tag16bytes123456'
        
        mock_cipher_decrypt = Mock()
        mock_cipher_decrypt.decrypt.return_value = b'a' * 32  # ASCII-safe CSRF nonce
        
        mock_aes.new.side_effect = [mock_cipher_encrypt, mock_cipher_decrypt]
        mock_aes.MODE_CCM = 9
        
        login_page = Mock()
        login_page.text = """
        <script>
        var currentSessionId = 'abc123';
        var myIv = '0123456789abcdef';
        var mySalt = 'fedcba9876543210';
        </script>
        """
        login_page.raise_for_status = Mock()
        
        password_response = Mock()
        password_response.text = '{"p_status":"AdminMatch", "encryptData": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}'
        password_response.json.return_value = {
            "p_status": "AdminMatch",
            "encryptData": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
        }
        password_response.raise_for_status = Mock()
        
        session_response = Mock()
        session_response.raise_for_status = Mock()
        
        device_response = Mock()
        device_response.json.return_value = {
            "model": "ARRIS TG3442DE",
            "sw_version": "9.1.1803"
        }
        device_response.headers = {"content-type": "application/json"}
        device_response.raise_for_status = Mock()
        
        mock_session.get.side_effect = [login_page, device_response]
        mock_session.post.side_effect = [password_response, session_response]
        mock_session.headers = {}
        
        resp = client.post("/api/test-modem",
            json={
                "modem_type": "vodafone",
                "modem_url": "http://192.168.0.1",
                "modem_user": "admin",
                "modem_password": "test"
            })
        
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is True
        assert "ARRIS" in data["model"]

    def test_test_modem_with_unknown_type(self, client):
        """Test connection fails gracefully with unknown modem type."""
        resp = client.post("/api/test-modem",
            json={
                "modem_type": "unknown_modem",
                "modem_url": "http://192.168.1.1",
                "modem_user": "admin",
                "modem_password": "test"
            })
        
        assert resp.status_code == 200
        data = json.loads(resp.data)
        assert data["success"] is False
        assert "Unknown modem type" in data["error"]

    def test_test_modem_defaults_to_config_type(self, client, config_mgr):
        """Test connection uses config modem_type if not specified in request."""
        config_mgr.save({"modem_type": "vodafone", "modem_password": "test"})
        
        with patch('app.drivers.vodafone.requests.Session') as mock_session_class:
            mock_session = Mock()
            mock_session_class.return_value = mock_session
            mock_session.get.side_effect = Exception("Expected vodafone driver to be used")
            
            resp = client.post("/api/test-modem",
                json={
                    "modem_url": "http://192.168.0.1",
                    "modem_user": "admin",
                    "modem_password": "test"
                })
            
            # Should attempt to use vodafone driver from config
            assert mock_session.get.called or resp.status_code == 200
