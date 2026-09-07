"""Tests for the Sagemcom F@st 3896 driver."""

import hashlib
import json
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.drivers.sagemcom import SagemcomDriver


# -- Fixtures --

@pytest.fixture
def driver():
    return SagemcomDriver("http://192.168.100.1", "admin", "password123")


def _login_response(session_id=12345, nonce="9876543210"):
    return {
        "reply": {
            "uid": 0,
            "id": 0,
            "error": {"code": 16777216, "description": "XMO_REQUEST_NO_ERR"},
            "actions": [{
                "uid": 1,
                "id": 0,
                "error": {"code": 16777238, "description": "XMO_NO_ERR"},
                "callbacks": [{
                    "uid": 1,
                    "result": {"code": 16777238, "description": "XMO_NO_ERR"},
                    "xpath": "Device/UserAccounts/Users/User[@uid='1']",
                    "parameters": {
                        "id": session_id,
                        "nonce": nonce,
                    },
                }],
            }],
            "events": [],
        }
    }


def _docsis_response(ds_channels=None, us_channels=None):
    return {
        "reply": {
            "uid": 0,
            "id": 1,
            "error": {"code": 16777216, "description": "XMO_REQUEST_NO_ERR"},
            "actions": [
                {
                    "uid": 1,
                    "id": 0,
                    "error": {"code": 16777238, "description": "XMO_NO_ERR"},
                    "callbacks": [{
                        "uid": 1,
                        "result": {"code": 16777238, "description": "XMO_NO_ERR"},
                        "xpath": "Device/Docsis/CableModem/Downstreams",
                        "parameters": {"value": ds_channels or []},
                    }],
                },
                {
                    "uid": 2,
                    "id": 1,
                    "error": {"code": 16777238, "description": "XMO_NO_ERR"},
                    "callbacks": [{
                        "uid": 2,
                        "result": {"code": 16777238, "description": "XMO_NO_ERR"},
                        "xpath": "Device/Docsis/CableModem/Upstreams",
                        "parameters": {"value": us_channels or []},
                    }],
                },
            ],
            "events": [],
        }
    }


def _device_info_response(model="FAST3896_WIFIHUBC4", sw_version="sw18.83.17.18n-12"):
    return {
        "reply": {
            "uid": 0,
            "id": 2,
            "error": {"code": 16777216, "description": "XMO_REQUEST_NO_ERR"},
            "actions": [
                {
                    "uid": 1,
                    "id": 0,
                    "error": {"code": 16777238, "description": "XMO_NO_ERR"},
                    "callbacks": [{
                        "uid": 1,
                        "result": {"code": 16777238, "description": "XMO_NO_ERR"},
                        "xpath": "Device/DeviceInfo/ModelName",
                        "parameters": {"value": model},
                    }],
                },
                {
                    "uid": 2,
                    "id": 1,
                    "error": {"code": 16777238, "description": "XMO_NO_ERR"},
                    "callbacks": [{
                        "uid": 2,
                        "result": {"code": 16777238, "description": "XMO_NO_ERR"},
                        "xpath": "Device/DeviceInfo/SoftwareVersion",
                        "parameters": {"value": sw_version},
                    }],
                },
            ],
            "events": [],
        }
    }


def _mock_post(responses):
    """Create a mock post function that returns responses in order."""
    call_count = [0]

    def mock_post(*args, **kwargs):
        idx = min(call_count[0], len(responses) - 1)
        call_count[0] += 1
        resp = MagicMock()
        resp.ok = True
        resp.status_code = 200
        resp.json.return_value = responses[idx]
        return resp

    return mock_post


# -- Authentication tests --

class TestAuthentication:
    def test_login_computes_credential_hash(self, driver):
        driver._session.post = _mock_post([_login_response()])
        driver._do_login()

        expected_pw_hash = hashlib.sha512(b"password123").hexdigest()
        expected_cred = hashlib.sha512(
            f"admin:9876543210:{expected_pw_hash}".encode()
        ).hexdigest()

        assert driver._credential_hash == expected_cred
        assert driver._session_id == 12345
        assert driver._server_nonce == "9876543210"

    def test_initial_login_sends_auth_key(self, driver):
        """First login request must include auth-key computed with empty nonce."""
        captured_bodies = []

        def capture_post(*args, **kwargs):
            captured_bodies.append(kwargs.get("data", {}).get("req", ""))
            resp = MagicMock()
            resp.ok = True
            resp.status_code = 200
            resp.json.return_value = _login_response()
            return resp

        driver._session.post = capture_post
        driver._do_login()

        import json
        body = json.loads(captured_bodies[0])
        auth_key = body["request"]["auth-key"]
        assert auth_key != "", "Initial login must send a non-empty auth-key"
        assert len(auth_key) == 128, "SHA-512 hex digest should be 128 chars"

    def test_login_sets_logged_in(self, driver):
        driver._session.post = _mock_post([_login_response()])
        driver.login()
        assert driver._logged_in is True

    def test_login_skipped_when_logged_in(self, driver):
        driver._logged_in = True
        driver._session.post = MagicMock()
        driver.login()
        driver._session.post.assert_not_called()

    def test_login_retries_on_connection_error(self, driver):
        call_count = [0]
        original_reset = driver._reset_session

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise requests.ConnectionError("refused")
            resp = MagicMock()
            resp.ok = True
            resp.status_code = 200
            resp.json.return_value = _login_response()
            return resp

        def patched_reset():
            original_reset()
            driver._session.post = side_effect

        with patch("app.drivers.sagemcom.time"):
            driver._session.post = side_effect
            driver._reset_session = patched_reset
            driver.login()
            assert driver._logged_in is True
            assert call_count[0] == 2

    def test_login_fails_after_max_retries(self, driver):
        def side_effect(*args, **kwargs):
            raise requests.ConnectionError("refused")

        original_reset = driver._reset_session

        def patched_reset():
            original_reset()
            driver._session.post = side_effect

        with patch("app.drivers.sagemcom.time"):
            driver._session.post = side_effect
            driver._reset_session = patched_reset
            with pytest.raises(RuntimeError, match="connection refused"):
                driver.login()

    def test_login_error_no_session(self, driver):
        bad_response = {
            "reply": {
                "uid": 0,
                "id": 0,
                "error": {"code": 16777216, "description": "XMO_REQUEST_NO_ERR"},
                "actions": [{
                    "uid": 1,
                    "id": 0,
                    "error": {"code": 16777238, "description": "XMO_NO_ERR"},
                    "callbacks": [{
                        "uid": 1,
                        "result": {"code": 16777238, "description": "XMO_NO_ERR"},
                        "xpath": "",
                        "parameters": {"id": 0, "nonce": ""},
                    }],
                }],
                "events": [],
            }
        }
        driver._session.post = _mock_post([bad_response])
        with pytest.raises(RuntimeError, match="missing session_id or nonce"):
            driver.login()

    def test_auth_key_computed_per_request(self, driver):
        driver._session.post = _mock_post([_login_response()])
        driver._do_login()

        driver._request_id = 5
        cnonce = 12345
        expected = hashlib.sha512(
            f"{driver._credential_hash}:5:{cnonce}:JSON:/cgi/json-req".encode()
        ).hexdigest()

        with patch("app.drivers.sagemcom.random") as mock_random:
            mock_random.randint.return_value = cnonce
            body = driver._build_request([{"id": 0, "method": "getValue", "xpath": "test"}])
            assert body["request"]["auth-key"] == expected


# -- Downstream parsing --

class TestDownstreamParsing:
    def test_parse_scqam_channel(self, driver):
        channels = [{
            "uid": 1,
            "ChannelID": 13,
            "LockStatus": True,
            "Frequency": 546000000.0,
            "SNR": 44.0,
            "PowerLevel": 7.9,
            "Modulation": "Qam256",
            "BandWidth": 8000000,
            "UnerroredCodewords": 1000,
            "CorrectableCodewords": 10,
            "UncorrectableCodewords": 2,
            "SymbolRate": 6952,
        }]
        ds30, ds31 = driver._parse_downstream(channels)

        assert len(ds30) == 1
        assert len(ds31) == 0
        ch = ds30[0]
        assert ch["channelID"] == 13
        assert ch["frequency"] == "546 MHz"
        assert ch["powerLevel"] == 7.9
        assert ch["mer"] == 44.0
        assert ch["mse"] == -44.0
        assert ch["modulation"] == "256QAM"
        assert ch["corrErrors"] == 10
        assert ch["nonCorrErrors"] == 2

    def test_parse_ofdm_channel(self, driver):
        channels = [{
            "uid": 25,
            "ChannelID": 193,
            "LockStatus": True,
            "Frequency": 666000000.0,
            "SNR": 44.0,
            "PowerLevel": 7.9,
            "Modulation": "256-QAM1K-QAM2K-QA",
            "BandWidth": 128000000,
            "UnerroredCodewords": 2000,
            "CorrectableCodewords": 100,
            "UncorrectableCodewords": 0,
            "SymbolRate": 0,
        }]
        ds30, ds31 = driver._parse_downstream(channels)

        assert len(ds30) == 0
        assert len(ds31) == 1
        ch = ds31[0]
        assert ch["channelID"] == 193
        assert ch["type"] == "OFDM"
        assert ch["frequency"] == "666 MHz"
        assert ch["mer"] == 44.0
        assert ch["mse"] is None
        assert ch["corrErrors"] == 100

    def test_unlocked_channels_skipped(self, driver):
        channels = [{
            "uid": 1, "ChannelID": 1, "LockStatus": False,
            "Frequency": 100000000.0, "SNR": 0, "PowerLevel": 0,
            "Modulation": "Qam256", "BandWidth": 8000000,
            "UnerroredCodewords": 0, "CorrectableCodewords": 0,
            "UncorrectableCodewords": 0, "SymbolRate": 0,
        }]
        ds30, ds31 = driver._parse_downstream(channels)
        assert len(ds30) == 0
        assert len(ds31) == 0

    def test_mixed_channels(self, driver):
        channels = [
            {"uid": 1, "ChannelID": 1, "LockStatus": True,
             "Frequency": 300000000.0, "SNR": 40.0, "PowerLevel": 5.0,
             "Modulation": "Qam256", "BandWidth": 8000000,
             "UnerroredCodewords": 0, "CorrectableCodewords": 0,
             "UncorrectableCodewords": 0, "SymbolRate": 6952},
            {"uid": 2, "ChannelID": 193, "LockStatus": True,
             "Frequency": 666000000.0, "SNR": 44.0, "PowerLevel": 7.0,
             "Modulation": "256-QAM1K-QAM2K-QA", "BandWidth": 128000000,
             "UnerroredCodewords": 0, "CorrectableCodewords": 0,
             "UncorrectableCodewords": 0, "SymbolRate": 0},
        ]
        ds30, ds31 = driver._parse_downstream(channels)
        assert len(ds30) == 1
        assert len(ds31) == 1

    def test_empty_channels(self, driver):
        ds30, ds31 = driver._parse_downstream([])
        assert ds30 == []
        assert ds31 == []


# -- Upstream parsing --

class TestUpstreamParsing:
    def test_parse_atdma_channel(self, driver):
        channels = [{
            "uid": 1,
            "ChannelID": 1,
            "LockStatus": True,
            "Frequency": 38000000.0,
            "SymbolRate": 5120,
            "PowerLevel": 41.8,
            "Modulation": "atdma",
            "ProfileID31": "",
            "Modulation31": "",
            "Frequency31": "",
        }]
        us30, us31 = driver._parse_upstream(channels)

        assert len(us30) == 1
        assert len(us31) == 0
        ch = us30[0]
        assert ch["channelID"] == 1
        assert ch["frequency"] == "38 MHz"
        assert ch["powerLevel"] == 41.8
        assert ch["modulation"] == "ATDMA"
        assert ch["multiplex"] == "ATDMA"

    def test_parse_ofdma_channel(self, driver):
        channels = [{
            "uid": 4,
            "ChannelID": 41,
            "LockStatus": True,
            "Frequency": 104800000.0,
            "SymbolRate": 0,
            "PowerLevel": 88.0,
            "Modulation": "ofdma",
            "ProfileID31": "3, 4, 5",
            "Modulation31": "qam1024(profile5)",
            "Frequency31": "108.500Mhz - 203.250Mhz",
        }]
        us30, us31 = driver._parse_upstream(channels)

        assert len(us30) == 0
        assert len(us31) == 1
        ch = us31[0]
        assert ch["channelID"] == 41
        assert ch["type"] == "OFDMA"
        assert ch["frequency"] == "104.8 MHz"
        assert ch["powerLevel"] == 88.0

    def test_mixed_upstream(self, driver):
        channels = [
            {"uid": 1, "ChannelID": 1, "LockStatus": True,
             "Frequency": 38000000.0, "SymbolRate": 5120, "PowerLevel": 41.8,
             "Modulation": "atdma", "ProfileID31": "", "Modulation31": "", "Frequency31": ""},
            {"uid": 4, "ChannelID": 41, "LockStatus": True,
             "Frequency": 104800000.0, "SymbolRate": 0, "PowerLevel": 88.0,
             "Modulation": "ofdma", "ProfileID31": "3", "Modulation31": "", "Frequency31": ""},
        ]
        us30, us31 = driver._parse_upstream(channels)
        assert len(us30) == 1
        assert len(us31) == 1


# -- OFDM detection --

class TestOfdmDetection:
    def test_by_bandwidth(self, driver):
        assert driver._is_ofdm_downstream("Qam256", 128000000) is True
        assert driver._is_ofdm_downstream("Qam256", 8000000) is False

    def test_by_modulation_string(self, driver):
        assert driver._is_ofdm_downstream("256-QAM1K-QAM2K-QA", 0) is True
        assert driver._is_ofdm_downstream("Qam256", 0) is False


# -- Modulation normalization --

class TestModulationNormalization:
    def test_qam256(self, driver):
        assert driver._normalize_modulation("Qam256") == "256QAM"

    def test_qam64(self, driver):
        assert driver._normalize_modulation("Qam64") == "64QAM"

    def test_empty(self, driver):
        assert driver._normalize_modulation("") == ""

    def test_passthrough(self, driver):
        assert driver._normalize_modulation("something") == "something"

    def test_us_atdma(self, driver):
        assert driver._normalize_us_modulation("atdma") == "ATDMA"

    def test_us_ofdma(self, driver):
        assert driver._normalize_us_modulation("ofdma") == "OFDMA"


# -- Frequency conversion --

class TestFrequencyConversion:
    def test_whole_mhz(self, driver):
        assert driver._hz_to_mhz(546000000) == "546 MHz"

    def test_fractional_mhz(self, driver):
        assert driver._hz_to_mhz(104800000) == "104.8 MHz"

    def test_zero(self, driver):
        assert driver._hz_to_mhz(0) == ""


# -- Full data flow --

class TestFullDataFlow:
    def test_get_docsis_data(self, driver):
        ds = [{
            "uid": 1, "ChannelID": 1, "LockStatus": True,
            "Frequency": 300000000.0, "SNR": 40.0, "PowerLevel": 5.0,
            "Modulation": "Qam256", "BandWidth": 8000000,
            "UnerroredCodewords": 0, "CorrectableCodewords": 0,
            "UncorrectableCodewords": 0, "SymbolRate": 6952,
        }]
        us = [{
            "uid": 1, "ChannelID": 1, "LockStatus": True,
            "Frequency": 38000000.0, "SymbolRate": 5120, "PowerLevel": 41.8,
            "Modulation": "atdma", "ProfileID31": "", "Modulation31": "", "Frequency31": "",
        }]

        driver._session.post = _mock_post([
            _login_response(),
            _docsis_response(ds, us),
        ])
        driver.login()
        result = driver.get_docsis_data()

        assert len(result["channelDs"]["docsis30"]) == 1
        assert len(result["channelUs"]["docsis30"]) == 1

    def test_get_device_info(self, driver):
        driver._session.post = _mock_post([
            _login_response(),
            _device_info_response(),
        ])
        driver.login()
        info = driver.get_device_info()

        assert info["manufacturer"] == "Sagemcom"
        assert info["model"] == "FAST3896_WIFIHUBC4"
        assert info["sw_version"] == "sw18.83.17.18n-12"

    def test_device_info_error_returns_fallback(self, driver):
        driver._session.post = _mock_post([_login_response()])
        driver.login()

        driver._session.post = MagicMock(side_effect=Exception("fail"))
        info = driver.get_device_info()

        assert info["manufacturer"] == "Sagemcom"
        assert info["model"] == ""
        assert driver._logged_in is False

    def test_docsis_retry_on_failure(self, driver):
        ds = [{"uid": 1, "ChannelID": 1, "LockStatus": True,
               "Frequency": 300000000.0, "SNR": 40.0, "PowerLevel": 5.0,
               "Modulation": "Qam256", "BandWidth": 8000000,
               "UnerroredCodewords": 0, "CorrectableCodewords": 0,
               "UncorrectableCodewords": 0, "SymbolRate": 6952}]
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                resp = MagicMock()
                resp.ok = False
                resp.status_code = 401
                resp.raise_for_status.side_effect = requests.HTTPError(response=resp)
                return resp
            resp = MagicMock()
            resp.ok = True
            resp.status_code = 200
            # Return login response first, then docsis data
            if call_count[0] == 2:
                resp.json.return_value = _login_response()
            else:
                resp.json.return_value = _docsis_response(ds, [])
            return resp

        driver._logged_in = True
        driver._credential_hash = "fake"
        driver._session_id = 1
        driver._server_nonce = "1"
        driver._session.post = side_effect
        result = driver.get_docsis_data()
        assert len(result["channelDs"]["docsis30"]) == 1

    def test_docsis_retry_on_xmo_session_error(self, driver):
        """When modem returns HTTP 200 with XMO error (e.g. after manual login
        invalidates DOCSight's session), driver must re-authenticate and retry."""
        ds = [{"uid": 1, "ChannelID": 1, "LockStatus": True,
               "Frequency": 300000000.0, "SNR": 40.0, "PowerLevel": 5.0,
               "Modulation": "Qam256", "BandWidth": 8000000,
               "UnerroredCodewords": 0, "CorrectableCodewords": 0,
               "UncorrectableCodewords": 0, "SymbolRate": 6952}]
        xmo_error_response = {
            "reply": {
                "uid": 0, "id": 1,
                "error": {"code": 16777242, "description": "XMO_UNKNOWN_PATH_ERR"},
                "actions": [{
                    "uid": 1, "id": 0,
                    "error": {"code": 16777242, "description": "XMO_UNKNOWN_PATH_ERR"},
                    "callbacks": [],
                }],
                "events": [],
            }
        }
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            resp.ok = True
            resp.status_code = 200
            if call_count[0] == 1:
                resp.json.return_value = xmo_error_response
            elif call_count[0] == 2:
                resp.json.return_value = _login_response()
            else:
                resp.json.return_value = _docsis_response(ds, [])
            return resp

        driver._logged_in = True
        driver._credential_hash = "fake"
        driver._session_id = 1
        driver._server_nonce = "1"
        driver._session.post = side_effect
        result = driver.get_docsis_data()
        assert len(result["channelDs"]["docsis30"]) == 1
        assert call_count[0] == 3  # error + re-login + successful fetch

    def test_xmo_error_raises_runtime_error(self, driver):
        """Any non-success XMO error in _raw_post must raise RuntimeError."""
        xmo_error_response = {
            "reply": {
                "uid": 0, "id": 1,
                "error": {"code": 16777242, "description": "XMO_UNKNOWN_PATH_ERR"},
                "actions": [],
                "events": [],
            }
        }
        driver._session.post = _mock_post([xmo_error_response])
        with pytest.raises(RuntimeError, match="XMO_UNKNOWN_PATH_ERR"):
            driver._raw_post({"request": {}})

    @patch("app.drivers.sagemcom.time")
    def test_login_recovers_from_session_error(self, mock_time, driver):
        """Login must reset session and retry when modem returns XMO_INVALID_SESSION_ERR."""
        session_error = {
            "reply": {
                "uid": 0, "id": 1,
                "error": {"code": 16777219, "description": "XMO_INVALID_SESSION_ERR"},
                "actions": [],
                "events": [],
            }
        }
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            resp = MagicMock()
            resp.ok = True
            resp.status_code = 200
            if call_count[0] == 1:
                resp.json.return_value = session_error
            else:
                resp.json.return_value = _login_response()
            return resp

        with patch.object(driver, "_reset_session", wraps=driver._reset_session) as mock_reset:
            driver._session.post = side_effect
            original_raw_post = driver._raw_post

            def patched_raw_post(body):
                driver._session.post = side_effect
                return original_raw_post(body)

            driver._raw_post = patched_raw_post
            driver.login()
            mock_reset.assert_called_once()
        assert driver._logged_in is True
        assert call_count[0] == 2  # session error + successful re-login


# -- Connection info --

class TestConnectionInfo:
    def test_returns_empty(self, driver):
        assert driver.get_connection_info() == {}


# -- Driver registration --

class TestRegistration:
    def test_sagemcom_registered(self):
        from app.drivers import driver_registry
        assert driver_registry.has_driver("sagemcom")

    def test_sagemcom_loads(self):
        from app.drivers import driver_registry
        d = driver_registry.load_driver("sagemcom", "http://192.168.100.1", "admin", "pass")
        assert isinstance(d, SagemcomDriver)


@pytest.mark.parametrize('fault', ['action', 'callback', 'missing', 'malformed', 'empty', 'unlocked'])
def test_rejects_unusable_channel_response(driver, fault):
    row = {'ChannelID': 1, 'LockStatus': True, 'SNR': 40, 'Modulation': 'Qam256'}
    response = _docsis_response([row], [])
    action = response['reply']['actions'][0]
    if fault == 'action':
        action['error']['description'] = 'XMO_UNKNOWN_PATH_ERR'
    elif fault == 'callback':
        action['callbacks'][0]['result']['description'] = 'XMO_UNKNOWN_PATH_ERR'
    elif fault == 'missing':
        response['reply']['actions'].pop()
    elif fault == 'malformed':
        action['callbacks'][0]['parameters']['value'] = 'invalid'
    elif fault == 'empty':
        action['callbacks'][0]['parameters']['value'] = []
    else:
        row['LockStatus'] = False
    driver._session.post = _mock_post([response])
    with pytest.raises(RuntimeError, match='Sagemcom'):
        driver._fetch_docsis_data()


def _metadata_response(uptime, status):
    response = _device_info_response()
    for index, (path, value) in enumerate([
        ('Device/DeviceInfo/UpTime', uptime),
        ('Device/Docsis/CableModem/Status', status),
    ], start=2):
        response['reply']['actions'].append({
            'id': index, 'error': {'description': 'XMO_NO_ERR'},
            'callbacks': [{'result': {'description': 'XMO_NO_ERR'},
                           'xpath': path, 'parameters': {'value': value}}],
        })
    return response


@pytest.mark.parametrize('uptime,expected', [(170015, 170015), ('170015', 170015), (0, 0),
                                            (-1, None), (True, None), ('bad', None), (1.5, None)])
def test_uptime_normalization(driver, uptime, expected):
    driver._session.post = _mock_post([_metadata_response(uptime, 'OPERATIONAL')])
    assert driver.get_device_info().get('uptime_seconds') == expected


@pytest.mark.parametrize('status,expected', [('OPERATIONAL', 'online'), ('ONLINE', 'online'),
    ('FORWARDING_DISABLED', 'offline'), ('UNRECOGNIZED', None), (None, None), ([], None)])
def test_docsis_status_normalization(driver, status, expected):
    driver._session.post = _mock_post([_metadata_response(170015, status)])
    assert driver.get_device_info().get('docsis_status') == expected


def test_metadata_reboot_and_missing_values_are_not_cached(driver):
    driver._session.post = _mock_post([
        _metadata_response(170015, 'OPERATIONAL'), _metadata_response(2, 'FORWARDING_DISABLED'),
        _device_info_response(),
    ])
    assert driver.get_device_info()['uptime_seconds'] == 170015
    info = driver.get_device_info()
    assert info['uptime_seconds'] == 2
    assert info['docsis_status'] == 'offline'
    info = driver.get_device_info()
    assert 'uptime_seconds' not in info
    assert 'docsis_status' not in info
    assert info['model'] == 'FAST3896_WIFIHUBC4'


def test_failed_optional_action_preserves_other_metadata(driver):
    response = _metadata_response(170015, 'OPERATIONAL')
    response['reply']['actions'][2]['error']['description'] = 'XMO_UNKNOWN_PATH_ERR'
    driver._session.post = _mock_post([response])
    info = driver.get_device_info()
    assert 'uptime_seconds' not in info
    assert info['docsis_status'] == 'online'
    assert info['model'] == 'FAST3896_WIFIHUBC4'


@pytest.mark.parametrize('snr,valid', [(0, False), (None, False), ('bad', False),
                                      (float('nan'), False), (True, False), (40, True), ('40', True)])
@pytest.mark.parametrize('bandwidth', [8000000, 96000000])
def test_snr_validity_keeps_channel_and_counters(driver, snr, valid, bandwidth):
    from app.analyzer import analyze
    from app.prometheus import format_metrics

    ds30, ds31 = driver._parse_downstream([{
        'ChannelID': 21, 'LockStatus': True, 'Frequency': 562000000,
        'PowerLevel': 2.3, 'SNR': snr, 'Modulation': 'Qam256', 'BandWidth': bandwidth,
        'CorrectableCodewords': 123, 'UncorrectableCodewords': 4,
    }])
    analysis = analyze({'channelDs': {'docsis30': ds30, 'docsis31': ds31}, 'channelUs': {}})
    channel = analysis['ds_channels'][0]
    assert channel['correctable_errors'] == 123
    assert channel['uncorrectable_errors'] == 4
    assert (channel['snr'] is not None) == valid
    if not valid:
        assert channel['health'] != 'good'
        assert 'unavailable' in channel['health_detail']
    output = format_metrics(analysis, {}, {}, 1000)
    assert f'docsight_downstream_snr_valid{{channel_id="21",frequency="562"}} {int(valid)}' in output
