"""Security boundaries for opt-in community module secrets."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from flask import Flask

from app import config as config_module
from app.collectors import _ModuleConfigProxy
from app.config import ConfigManager, PASSWORD_MASK
from app.doctor import _is_sensitive_key
from app.module_loader import ModuleLoader, register_module_config


def _manifest(module_id: str, secret_key: str | None = None) -> dict:
    config = {f"{module_id.replace('.', '_')}_enabled": False}
    manifest = {
        "id": module_id,
        "name": module_id,
        "description": "Test module",
        "version": "1.0.0",
        "author": "Test",
        "minAppVersion": "2026.2",
        "type": "integration",
        "contributes": {},
        "config": config,
    }
    if secret_key is not None:
        config[secret_key] = ""
        manifest["config_secrets"] = [secret_key]
    return manifest


def _write_module(root: Path, directory: str, manifest: dict) -> None:
    module_dir = root / directory
    module_dir.mkdir()
    (module_dir / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


@pytest.fixture(autouse=True)
def restore_config_registry():
    defaults = dict(config_module.DEFAULTS)
    bool_keys = set(config_module.BOOL_KEYS)
    int_keys = set(config_module.INT_KEYS)
    private_keys = set(config_module.PRIVATE_KEYS)
    module_secret_keys = set(config_module.MODULE_SECRET_KEYS)
    module_secret_owners = dict(config_module.MODULE_SECRET_OWNERS)
    yield
    config_module.DEFAULTS.clear()
    config_module.DEFAULTS.update(defaults)
    config_module.BOOL_KEYS.clear()
    config_module.BOOL_KEYS.update(bool_keys)
    config_module.INT_KEYS.clear()
    config_module.INT_KEYS.update(int_keys)
    config_module.PRIVATE_KEYS.clear()
    config_module.PRIVATE_KEYS.update(private_keys)
    config_module.set_module_secret_registry(module_secret_keys, module_secret_owners)


def test_module_secret_encrypts_masks_decrypts_and_preserves_mask(tmp_path):
    key = "community_weather_token"
    config_module.DEFAULTS[key] = ""
    config_module.set_module_secret_registry({key}, {key: "community.weather"})
    manager = ConfigManager(str(tmp_path / "data"))

    manager.save({key: "token-value"})
    raw = json.loads(Path(manager.config_path).read_text(encoding="utf-8"))

    assert raw[key] != "token-value"
    assert manager.get(key) == "token-value"
    assert manager.get_all(mask_secrets=True)[key] == PASSWORD_MASK

    manager.save({key: PASSWORD_MASK})
    assert manager.get(key) == "token-value"
    assert json.loads(Path(manager.config_path).read_text(encoding="utf-8"))[key] == raw[key]
    assert _is_sensitive_key(key)


def test_non_manifest_secret_registration_never_enables_scalar_coercion(tmp_path):
    key = "community_defense_in_depth_token"
    config_module.BOOL_KEYS.add(key)
    config_module.INT_KEYS.add(key)
    config_module.set_module_secret_registry({key}, {key: "community.defense"})

    assert key not in config_module.INT_KEYS
    assert key not in config_module.BOOL_KEYS
    register_module_config(
        {key: 0}, module_id="community.defense", builtin=False
    )

    assert key not in config_module.INT_KEYS
    assert key not in config_module.BOOL_KEYS
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({key: "token-value"})
    assert manager.get(key) == "token-value"
    assert manager.get_all(mask_secrets=True)[key] == PASSWORD_MASK


def test_proxy_reads_only_its_owned_secret_and_normal_config(tmp_path):
    owned = "community_weather_token"
    other = "community_other_token"
    private = "report_customer_name"
    config_module.DEFAULTS.update({owned: "", other: "", private: "", "plain_module_value": ""})
    config_module.PRIVATE_KEYS.add(private)
    config_module.set_module_secret_registry(
        {owned, other},
        {owned: "community.weather", other: "community.other"},
    )
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save(
        {
            owned: "owned-value",
            other: "other-value",
            private: "private-value",
            "modem_password": "core-value",
            "admin_password": "hash-value",
            "plain_module_value": "plain-value",
        }
    )

    proxy = _ModuleConfigProxy(manager, "community.weather")

    assert proxy.get(owned) == "owned-value"
    assert proxy.get("plain_module_value") == "plain-value"
    assert proxy.get(other) is None
    assert proxy.get(private) is None
    assert proxy.get("modem_password") is None
    assert proxy.get("admin_password") is None
    visible = proxy.get_all()
    assert visible[owned] == "owned-value"
    assert visible["plain_module_value"] == "plain-value"
    assert other not in visible
    assert private not in visible
    assert "modem_password" not in visible
    assert "admin_password" not in visible


def test_duplicate_claims_fail_both_modules_even_when_one_is_disabled(tmp_path, caplog):
    key = "shared_credential"
    _write_module(tmp_path, "a", _manifest("community.alpha", key))
    _write_module(tmp_path, "b", _manifest("community.beta", key))
    loader = ModuleLoader(
        Flask(__name__),
        search_paths=[str(tmp_path)],
        disabled_ids={"community.alpha"},
    )

    modules = loader.load_all()

    assert {module.id for module in modules if module.error} == {
        "community.alpha",
        "community.beta",
    }
    assert key in config_module.MODULE_SECRET_KEYS
    assert key not in config_module.MODULE_SECRET_OWNERS
    assert _ModuleConfigProxy(ConfigManager(str(tmp_path / "data")), "community.alpha").get(key) is None
    assert _ModuleConfigProxy(ConfigManager(str(tmp_path / "data2")), "community.beta").get(key) is None
    assert key not in caplog.text


def test_secret_claim_cannot_take_over_another_modules_plain_config(tmp_path, caplog):
    key = "shared_module_setting"
    victim = _manifest("community.victim")
    victim["config"][key] = "victim-default"
    _write_module(tmp_path, "victim", victim)
    _write_module(tmp_path, "claimant", _manifest("community.claimant", key))
    loader = ModuleLoader(
        Flask(__name__),
        search_paths=[str(tmp_path)],
        disabled_ids={"community.claimant"},
    )

    modules = loader.load_all()

    assert {module.id for module in modules if module.error} == {
        "community.claimant",
        "community.victim",
    }
    assert key in config_module.MODULE_SECRET_KEYS
    assert key not in config_module.MODULE_SECRET_OWNERS
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({key: "existing-value"})
    assert _ModuleConfigProxy(manager, "community.claimant").get(key) is None
    assert _ModuleConfigProxy(manager, "community.victim").get(key) is None
    assert key not in caplog.text


def test_disabled_module_reserves_secret_against_other_modules(tmp_path):
    key = "disabled_owner_credential"
    _write_module(tmp_path, "owner", _manifest("community.owner", key))
    _write_module(tmp_path, "observer", _manifest("community.observer"))
    loader = ModuleLoader(
        Flask(__name__),
        search_paths=[str(tmp_path)],
        disabled_ids={"community.owner"},
    )

    modules = loader.load_all()

    assert not any(module.error for module in modules)
    assert config_module.MODULE_SECRET_OWNERS[key] == "community.owner"
    manager = ConfigManager(str(tmp_path / "data"))
    manager.save({key: "reserved-value"})
    assert _ModuleConfigProxy(manager, "community.observer").get(key) is None


@pytest.mark.parametrize("protected_key", ["modem_password", "admin_password", "report_customer_name"])
def test_community_module_cannot_claim_any_core_protected_class(tmp_path, protected_key):
    if protected_key == "report_customer_name":
        config_module.PRIVATE_KEYS.add(protected_key)
    _write_module(tmp_path, "claimant", _manifest("community.claimant", protected_key))

    modules = ModuleLoader(Flask(__name__), search_paths=[str(tmp_path)]).load_all()

    assert modules[0].error
    assert protected_key not in config_module.MODULE_SECRET_OWNERS
