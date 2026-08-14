import os
import stat

from app.runtime import AuthStateStore


def test_auth_state_store_persists_private_key_and_fingerprint(tmp_path):
    store = AuthStateStore(str(tmp_path / "data"))
    first = store.load_or_create_session_key()
    assert len(first) == 32
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(store.key_path).st_mode) == 0o600
    assert store.load_or_create_session_key() == first

    fingerprint = "a" * 64
    store.write_fingerprint(fingerprint)
    assert store.read_fingerprint() == fingerprint
    if os.name != "nt":
        assert stat.S_IMODE(os.stat(store.auth_state_path).st_mode) == 0o600

    rotated = store.rotate_session_key()
    assert rotated != first
    assert store.load_or_create_session_key() == rotated
