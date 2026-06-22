import base64
import json
from unittest.mock import MagicMock, patch

from cryptography.hazmat.primitives.ciphers.aead import AESCCM

from app.drivers.ultrahub7 import UltraHub7Driver
from app.drivers.utils import pbkdf2_sha256


def test_ultrahub_pbkdf2_helper_matches_sha256_contract():
    # Reference vector generated with hashlib.pbkdf2_hmac("sha256", ...).
    derived = pbkdf2_sha256(b"webuisalt1", b"router-salt")

    assert derived.hex() == "62931075f8d4029ba615fa270e1e4d97"


def test_ultrahub_login_uses_stdlib_pbkdf2_key_for_aesccm_payload():
    driver = UltraHub7Driver(url="http://dummy", user="admin", password="admin")
    fixed_iv = bytes.fromhex("0102030405060708090a0b0c0d0e0f10")

    init_response = MagicMock()
    init_response.raise_for_status = MagicMock()
    init_response.json.return_value = {
        "X_INTERNAL_ID": "7",
        "csrf_token": "csrf-initial",
    }

    secret_response = MagicMock()
    secret_response.raise_for_status = MagicMock()
    secret_response.json.return_value = {
        "X_VODAFONE_WebUISecret": "webuisalt1router-salt",
    }

    login_response = MagicMock()
    login_response.raise_for_status = MagicMock()
    login_response.json.return_value = {"csrf_token": "csrf-after-login"}

    with patch.object(driver._session, "get", side_effect=[init_response, secret_response]), \
         patch.object(driver._session, "post", return_value=login_response) as mock_post, \
         patch("app.drivers.ultrahub7.os.urandom", return_value=fixed_iv):
        driver.login()

    login_payload = mock_post.call_args.kwargs["data"]
    encrypted_password_json = login_payload["X_VODAFONE_Password"]
    encrypted_password = json.loads(encrypted_password_json)

    assert login_payload["__id"] == "7"
    assert login_payload["csrf_token"] == "csrf-initial"
    assert encrypted_password["iv"] == base64.b64encode(fixed_iv).decode("ascii")
    assert encrypted_password["mode"] == "ccm"
    assert encrypted_password["ts"] == 64

    key = pbkdf2_sha256(b"webuisalt1", b"router-salt")
    nonce = driver._truncate_iv(fixed_iv, len(driver._password) * 8, 8)
    decrypted = AESCCM(key, tag_length=8).decrypt(
        nonce,
        base64.b64decode(encrypted_password["ct"]),
        None,
    )

    assert decrypted == b"admin"
    assert driver._csrf_token == "csrf-after-login"
