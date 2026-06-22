import json
from unittest.mock import patch, MagicMock

import requests
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from app.drivers.vodafone_station import (
    VodafoneStationDriver,
    _aes_ccm_decrypt_hex,
    _aes_ccm_encrypt_hex,
)

# ===== Embedded fixture HTML =====
# Two pages are fetched per call:
#   status_data  -> /php/status_status_data.php  (js_* markers)
#   status_status -> /?status_status             (_ga.* markers)
FIXTURES = {

"happy_path": {
    "status_data": """
<script>
js_HWTypeVersion = 'HW1';
js_FWVersion = 'SW1';
js_ipv4addr = '192.168.1.2';
js_ipv6addr = 'fe80::1';
js_UptimeSinceReboot = '0,3,25';
</script>
""",
    "status_status": """
<script>
_ga.modemConnectionStatus = 'DOCSIS Online';
_ga.lastRebootReason = 'Power On';
</script>
""",
},

"empty_fields": {
    "status_data": """
<script>
js_HWTypeVersion = '';
js_FWVersion = '';
js_ipv4addr = '';
js_ipv6addr = '';
js_UptimeSinceReboot = '';
</script>
""",
    "status_status": """
<script>
_ga.modemConnectionStatus = '';
_ga.lastRebootReason = '';
</script>
""",
},

"missing_markers": {
    "status_data": """
<script>
</script>
""",
    "status_status": """
<script>
</script>
""",
},

"unknown_input": {
    "status_data": """
<script>
js_HWTypeVersion = 'HW1';
js_FWVersion = 'SW1';
js_ipv4addr = '192.168.1.2';
js_ipv6addr = 'fe80::1';
js_UptimeSinceReboot = '0,3,25';
</script>
""",
    "status_status": """
<script>
_ga.modemConnectionStatus = 'Scanning Frequencies';
_ga.lastRebootReason = 'Firmware Update';
</script>
""",
},

"malformed_input": {
    "status_data": """
<script>
js_HWTypeVersion = 'HW1';
js_FWVersion = 'SW1';
js_ipv4addr = '192.168.1.2';
js_ipv6addr = 'fe80::1';
js_UptimeSinceReboot = 'a-b-c';
</script>
""",
    "status_status": """
<script>
_ga.modemConnectionStatus = 'DOCSIS Online';
_ga.lastRebootReason = 'Power On';
</script>
""",
},
}

# ===== Helper to mock router responses =====
def mock_router_responses(driver, section_id):
    fixture = FIXTURES[section_id]

    with patch.object(driver._session, "get") as mock_get:
        mock_resp1 = MagicMock()
        mock_resp1.text = fixture["status_data"]
        mock_resp1.raise_for_status = MagicMock()

        mock_resp2 = MagicMock()
        mock_resp2.text = fixture["status_status"]
        mock_resp2.raise_for_status = MagicMock()

        mock_get.side_effect = [mock_resp1, mock_resp2]
        return driver._get_device_info_tg()

# ===== Global driver =====
driver = VodafoneStationDriver(url="http://dummy", user="admin", password="admin")

# ===== Tests =====
def test_tg_aes_ccm_helpers_match_retained_contract():
    """Vodafone TG AES-CCM keeps ciphertext+tag hex and authenticated data semantics."""
    key = bytes.fromhex("00112233445566778899aabbccddeeff")
    nonce = bytes.fromhex("0102030405060708")
    plaintext = b"docsight-vodafone-tg-login-payload"

    encrypted_hex = _aes_ccm_encrypt_hex(
        key,
        nonce,
        plaintext,
        b"loginPassword",
    )

    assert encrypted_hex == (
        "bbba77827b9992510b03321a8444dfe82d50c9b32c2f029dacf968c084c4e76d"
        "ab0f0ce154fb9276354a741f45afcfbaa085"
    )
    assert _aes_ccm_decrypt_hex(key, nonce, encrypted_hex, b"loginPassword") == plaintext


def test_tg_login_posts_decryptable_aes_ccm_payload_from_cryptography():
    driver = VodafoneStationDriver(url="http://dummy", user="admin", password="admin")
    html = """
    <script>
    var currentSessionId = '0123456789abcdef0123456789abcdef';
    var myIv = '0102030405060708';
    var mySalt = '0011223344556677';
    </script>
    """

    page_response = MagicMock(status_code=200, text=html)
    page_response.raise_for_status = MagicMock()
    credential_response = MagicMock(
        status_code=200,
        text='createCookie("credential", "credential-cookie-value", 1);',
    )

    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=16,
        salt=bytes.fromhex("0011223344556677"),
        iterations=1000,
    )
    key = kdf.derive(driver._password.encode("utf-8"))
    encrypted_nonce = _aes_ccm_encrypt_hex(
        key,
        bytes.fromhex("0102030405060708"),
        b"0123456789abcdef0123456789abcdef-extra",
        b"nonce",
    )

    login_response = MagicMock()
    login_response.raise_for_status = MagicMock()
    login_response.json.return_value = {"p_status": "OK", "encryptData": encrypted_nonce}
    session_response = MagicMock(status_code=200)

    with patch.object(driver._session, "get", side_effect=[page_response, credential_response]), \
         patch.object(driver._session, "post", side_effect=[login_response, session_response]) as mock_post:
        driver._login_tg()

    login_payload = json.loads(mock_post.call_args_list[0].kwargs["data"])
    assert login_payload["Name"] == "admin"
    assert login_payload["AuthData"] == "loginPassword"
    assert "EncryptData" in login_payload

    assert driver._tg_key is not None
    assert driver._tg_iv is not None
    decrypted = _aes_ccm_decrypt_hex(
        driver._tg_key,
        driver._tg_iv,
        login_payload["EncryptData"],
        b"loginPassword",
    )
    assert json.loads(decrypted.decode("utf-8")) == {
        "Password": driver._password,
        "Nonce": "0123456789abcdef0123456789abcdef",
    }
    assert driver._tg_nonce == "0123456789abcdef0123456789abcdef"
    assert driver._session.cookies.get("credential") == "credential-cookie-value"


def test_happy_path():
    result = mock_router_responses(driver, "happy_path")
    assert result["hw_version"] == "HW1"
    assert result["sw_version"] == "SW1"
    assert result["docsis_status"].lower() == "online"
    assert result["uptime_seconds"] == 3*3600 + 25*60
    assert result["wan_ipv4"] == "192.168.1.2"
    assert result["wan_ipv6"] == "fe80::1"
    assert result["reboot_reason"].lower() == "power on"

def test_empty_fields():
    result = mock_router_responses(driver, "empty_fields")
    assert result.get("sw_version", "") == ""
    assert result.get("hw_version", "") == ""
    assert result.get("reboot_reason", "") == ""
    assert result.get("docsis_status", "") == ""
    assert result.get("uptime_seconds", "") == 0
    assert result.get("wan_ipv4", "") == ""
    assert result.get("wan_ipv6", "") == ""

def test_missing_marker():
    result = mock_router_responses(driver, "missing_markers")
    assert result.get("sw_version", "") == ""
    assert result.get("hw_version", "") == ""
    assert result.get("reboot_reason", "") == ""
    assert result.get("docsis_status", "") == ""
    assert result.get("uptime_seconds", "") == 0
    assert result.get("wan_ipv4", "") == ""
    assert result.get("wan_ipv6", "") == ""

def test_unknown_input():
    result = mock_router_responses(driver, "unknown_input")
    assert result["docsis_status"] == "scanning frequencies"
    assert result["reboot_reason"] == "firmware update"

def test_malformed_input():
    result = mock_router_responses(driver, "malformed_input")
    assert result["uptime_seconds"] == 0

def test_http_failure_returns_fallback():
    """A non-auth network error (e.g. 5xx, timeout) falls back to the
    hardcoded manufacturer/model dict instead of crashing the collector."""
    with patch.object(driver._session, "get") as mock_get:
        err = requests.HTTPError(response=MagicMock(status_code=500))
        mock_get.side_effect = err

        result = driver._get_device_info_tg()

        assert result == {
            "manufacturer": "CommScope/ARRIS",
            "model": "Vodafone Station (TG6442VF/TG3442DE)",
        }


def test_auth_error_triggers_reauth_and_retry():
    """On a 401/403 the session is invalidated, re-login is attempted,
    and the pair of status requests is retried once."""
    fixture = FIXTURES["happy_path"]

    ok_resp1 = MagicMock()
    ok_resp1.text = fixture["status_data"]
    ok_resp1.raise_for_status = MagicMock()

    ok_resp2 = MagicMock()
    ok_resp2.text = fixture["status_status"]
    ok_resp2.raise_for_status = MagicMock()

    auth_err = requests.HTTPError(response=MagicMock(status_code=401))

    # Record every interaction the code under test makes so the full
    # sequence (first GET, invalidate, login, retry GETs) can be asserted.
    call_log = []
    responses = iter([auth_err, ok_resp1, ok_resp2])

    def fake_get(url, *args, **kwargs):
        call_log.append(f"get:{url}")
        nxt = next(responses)
        if isinstance(nxt, Exception):
            raise nxt
        return nxt

    with patch.object(driver._session, "get", side_effect=fake_get) as mock_get, \
         patch.object(driver, "_login_tg",
                      side_effect=lambda: call_log.append("login")) as mock_login, \
         patch.object(driver, "_invalidate_tg_session",
                      side_effect=lambda: call_log.append("invalidate")) as mock_invalidate:
        result = driver._get_device_info_tg()

    mock_invalidate.assert_called_once()
    mock_login.assert_called_once()
    assert mock_get.call_count == 3
    # Full ordered sequence: failing GET, session invalidate, re-login,
    # then both retry GETs.
    assert [entry.split(":", 1)[0] for entry in call_log] == [
        "get", "invalidate", "login", "get", "get",
    ]
    assert result["hw_version"] == "HW1"
    assert result["docsis_status"] == "online"
    assert result["reboot_reason"] == "power on"
