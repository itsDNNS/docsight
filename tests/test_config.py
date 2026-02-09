"""Tests for configuration management."""

import json
import os
import pytest
from app.config import ConfigManager, DEFAULTS, SECRET_KEYS, HASH_KEYS, PASSWORD_MASK


@pytest.fixture
def tmp_data_dir(tmp_path):
    return str(tmp_path / "data")


@pytest.fixture
def config(tmp_data_dir):
    return ConfigManager(tmp_data_dir)


class TestConfigDefaults:
    def test_defaults_applied(self, config):
        assert config.get("fritz_url") == "http://192.168.178.1"
        assert config.get("poll_interval") == 300
        assert config.get("web_port") == 8765
        assert config.get("theme") == "dark"
        assert config.get("language") == "en"

    def test_custom_default(self, config):
        assert config.get("nonexistent", "fallback") == "fallback"

    def test_not_configured_initially(self, config):
        assert config.is_configured() is False

    def test_mqtt_not_configured_initially(self, config):
        assert config.is_mqtt_configured() is False


class TestConfigSaveLoad:
    def test_save_and_load(self, tmp_data_dir):
        config = ConfigManager(tmp_data_dir)
        config.save({"fritz_user": "admin", "poll_interval": 120})

        # Reload from disk
        config2 = ConfigManager(tmp_data_dir)
        assert config2.get("fritz_user") == "admin"
        assert config2.get("poll_interval") == 120

    def test_save_creates_file(self, config, tmp_data_dir):
        config.save({"fritz_user": "test"})
        assert os.path.exists(os.path.join(tmp_data_dir, "config.json"))

    def test_int_keys_cast(self, tmp_data_dir):
        config = ConfigManager(tmp_data_dir)
        config.save({"poll_interval": "180"})
        config2 = ConfigManager(tmp_data_dir)
        assert config2.get("poll_interval") == 180
        assert isinstance(config2.get("poll_interval"), int)


class TestConfigSecrets:
    def test_password_encrypted_at_rest(self, config, tmp_data_dir):
        config.save({"fritz_password": "secret123"})

        # Read raw file - password should not be plaintext
        with open(os.path.join(tmp_data_dir, "config.json")) as f:
            raw = json.load(f)
        assert raw["fritz_password"] != "secret123"
        assert raw["fritz_password"] != ""

    def test_password_decrypted_on_read(self, tmp_data_dir):
        config = ConfigManager(tmp_data_dir)
        config.save({"fritz_password": "secret123"})

        config2 = ConfigManager(tmp_data_dir)
        assert config2.get("fritz_password") == "secret123"

    def test_mask_not_saved(self, tmp_data_dir):
        config = ConfigManager(tmp_data_dir)
        config.save({"fritz_password": "original"})
        config.save({"fritz_password": PASSWORD_MASK, "fritz_user": "updated"})

        config2 = ConfigManager(tmp_data_dir)
        assert config2.get("fritz_password") == "original"
        assert config2.get("fritz_user") == "updated"

    def test_get_all_masks_secrets(self, config):
        config.save({"fritz_password": "secret", "mqtt_password": "mqttpass"})
        all_config = config.get_all(mask_secrets=True)
        assert all_config["fritz_password"] == PASSWORD_MASK
        assert all_config["mqtt_password"] == PASSWORD_MASK

    def test_get_all_shows_secrets(self, config):
        config.save({"fritz_password": "secret"})
        all_config = config.get_all(mask_secrets=False)
        assert all_config["fritz_password"] == "secret"

    def test_admin_password_hashed_at_rest(self, config, tmp_data_dir):
        config.save({"admin_password": "admin123"})
        with open(os.path.join(tmp_data_dir, "config.json")) as f:
            raw = json.load(f)
        assert raw["admin_password"] != "admin123"
        assert raw["admin_password"].startswith(("scrypt:", "pbkdf2:"))

    def test_admin_password_hash_returned(self, config):
        config.save({"admin_password": "admin123"})
        stored = config.get("admin_password")
        assert stored.startswith(("scrypt:", "pbkdf2:"))

    def test_admin_password_mask_not_saved(self, tmp_data_dir):
        config = ConfigManager(tmp_data_dir)
        config.save({"admin_password": "original"})
        hash1 = config.get("admin_password")
        config.save({"admin_password": PASSWORD_MASK, "fritz_user": "updated"})
        assert config.get("admin_password") == hash1

    def test_admin_password_masked_in_get_all(self, config):
        config.save({"admin_password": "secret"})
        all_config = config.get_all(mask_secrets=True)
        assert all_config["admin_password"] == PASSWORD_MASK


class TestConfigEnvOverride:
    def test_env_overrides_file(self, tmp_data_dir, monkeypatch):
        config = ConfigManager(tmp_data_dir)
        config.save({"fritz_url": "http://from-file"})

        monkeypatch.setenv("FRITZ_URL", "http://from-env")
        assert config.get("fritz_url") == "http://from-env"

    def test_env_overrides_default(self, tmp_data_dir, monkeypatch):
        monkeypatch.setenv("POLL_INTERVAL", "600")
        config = ConfigManager(tmp_data_dir)
        assert config.get("poll_interval") == 600

    def test_empty_env_ignored(self, tmp_data_dir, monkeypatch):
        monkeypatch.setenv("FRITZ_USER", "")
        config = ConfigManager(tmp_data_dir)
        assert config.get("fritz_user") == ""  # falls through to default


class TestConfigState:
    def test_is_configured_with_password(self, config):
        config.save({"fritz_password": "pass123"})
        assert config.is_configured() is True

    def test_is_mqtt_configured(self, config):
        config.save({"mqtt_host": "broker.local"})
        assert config.is_mqtt_configured() is True

    def test_theme_validation(self, config):
        assert config.get_theme() == "dark"
        config.save({"theme": "light"})
        assert config.get_theme() == "light"
        config.save({"theme": "invalid"})
        assert config.get_theme() == "dark"
