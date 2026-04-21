import copy

from app import config as cfg
from app.module_loader import register_module_config, validate_manifest


def test_validate_manifest_accepts_config_secrets(tmp_path):
    raw = {
        "id": "community.example_secret_module",
        "name": "Example",
        "description": "Example module",
        "version": "0.1.0",
        "author": "itsDNNS",
        "minAppVersion": "2026.2",
        "type": "integration",
        "contributes": {"routes": "routes.py"},
        "config": {"example_enabled": False, "example_password": ""},
        "config_secrets": ["example_password"],
    }
    mod = validate_manifest(raw, str(tmp_path / "example"))
    assert mod.config_secrets == ["example_password"]
    assert mod.config["example_password"] == ""


def test_register_module_config_registers_secret_keys():
    old_defaults = copy.deepcopy(cfg.DEFAULTS)
    old_secret_keys = set(cfg.SECRET_KEYS)
    old_bool_keys = set(cfg.BOOL_KEYS)
    old_int_keys = set(cfg.INT_KEYS)
    try:
        register_module_config(
            {"example_enabled": False, "example_password": "", "example_interval": 30},
            secret_keys=["example_password"],
        )
        assert cfg.DEFAULTS["example_password"] == ""
        assert "example_password" in cfg.SECRET_KEYS
        assert "example_enabled" in cfg.BOOL_KEYS
        assert "example_interval" in cfg.INT_KEYS
    finally:
        cfg.DEFAULTS.clear()
        cfg.DEFAULTS.update(old_defaults)
        cfg.SECRET_KEYS.clear()
        cfg.SECRET_KEYS.update(old_secret_keys)
        cfg.BOOL_KEYS.clear()
        cfg.BOOL_KEYS.update(old_bool_keys)
        cfg.INT_KEYS.clear()
        cfg.INT_KEYS.update(old_int_keys)


def test_validate_manifest_rejects_core_config_key_collision(tmp_path):
    raw = {
        "id": "community.example_collision",
        "name": "Example",
        "description": "Example module",
        "version": "0.1.0",
        "author": "itsDNNS",
        "minAppVersion": "2026.2",
        "type": "integration",
        "contributes": {"routes": "routes.py"},
        "config": {"modem_password": "stealme"},
    }
    try:
        validate_manifest(raw, str(tmp_path / "example"))
    except Exception as exc:
        assert 'conflict with existing core keys' in str(exc)
    else:
        raise AssertionError('expected config key collision to be rejected')
