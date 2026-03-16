"""Tests for configuration management."""

import json
import os
import pytest
from app.config import ConfigManager, DEFAULTS, SECRET_KEYS, HASH_KEYS, PASSWORD_MASK, URL_KEYS


@pytest.fixture
def tmp_data_dir(tmp_path):
    return str(tmp_path / "data")


@pytest.fixture
def config(tmp_data_dir):
    return ConfigManager(tmp_data_dir)


class TestConfigDefaults:
    def test_defaults_applied(self, config):
        assert config.get("modem_url") == "http://192.168.178.1"
        assert config.get("poll_interval") == 900
        assert config.get("web_port") == 8765
        assert config.get("theme") == "dark"
        assert config.get("language") == "en"

    def test_custom_default(self, config):
        assert config.get("nonexistent", "fallback") == "fallback"

    def test_not_configured_initially(self, config):
        assert config.is_configured() is False

    def test_mqtt_not_configured_initially(self, config):
        assert config.is_mqtt_configured() is False

    def test_smokeping_module_disabled_by_default(self, config):
        assert config.get("disabled_modules") == "docsight.smokeping"


class TestConfigSaveLoad:
    def test_save_and_load(self, tmp_data_dir):
        config = ConfigManager(tmp_data_dir)
        config.save({"modem_user": "admin", "poll_interval": 120})

        # Reload from disk
        config2 = ConfigManager(tmp_data_dir)
        assert config2.get("modem_user") == "admin"
        assert config2.get("poll_interval") == 120

    def test_save_creates_file(self, config, tmp_data_dir):
        config.save({"modem_user": "test"})
        assert os.path.exists(os.path.join(tmp_data_dir, "config.json"))

    def test_int_keys_cast(self, tmp_data_dir):
        config = ConfigManager(tmp_data_dir)
        config.save({"poll_interval": "180"})
        config2 = ConfigManager(tmp_data_dir)
        assert config2.get("poll_interval") == 180
        assert isinstance(config2.get("poll_interval"), int)

    @pytest.mark.parametrize("value,expected", [
        ("true", True), ("True", True), ("TRUE", True),
        ("1", True), ("yes", True), ("on", True), ("On", True),
        ("false", False), ("False", False), ("0", False), ("no", False),
        ("off", False), ("", False),
    ])
    def test_bool_keys_cast(self, tmp_data_dir, value, expected):
        config = ConfigManager(tmp_data_dir)
        config.save({"demo_mode": value})
        config2 = ConfigManager(tmp_data_dir)
        assert config2.get("demo_mode") is expected


class TestConfigSecrets:
    def test_password_encrypted_at_rest(self, config, tmp_data_dir):
        config.save({"modem_password": "secret123"})

        # Read raw file - password should not be plaintext
        with open(os.path.join(tmp_data_dir, "config.json")) as f:
            raw = json.load(f)
        assert raw["modem_password"] != "secret123"
        assert raw["modem_password"] != ""

    def test_password_decrypted_on_read(self, tmp_data_dir):
        config = ConfigManager(tmp_data_dir)
        config.save({"modem_password": "secret123"})

        config2 = ConfigManager(tmp_data_dir)
        assert config2.get("modem_password") == "secret123"

    def test_mask_not_saved(self, tmp_data_dir):
        config = ConfigManager(tmp_data_dir)
        config.save({"modem_password": "original"})
        config.save({"modem_password": PASSWORD_MASK, "modem_user": "updated"})

        config2 = ConfigManager(tmp_data_dir)
        assert config2.get("modem_password") == "original"
        assert config2.get("modem_user") == "updated"

    def test_get_all_masks_secrets(self, config):
        config.save({"modem_password": "secret"})
        all_config = config.get_all(mask_secrets=True)
        assert all_config["modem_password"] == PASSWORD_MASK

    def test_get_all_shows_secrets(self, config):
        config.save({"modem_password": "secret"})
        all_config = config.get_all(mask_secrets=False)
        assert all_config["modem_password"] == "secret"

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
        config.save({"admin_password": PASSWORD_MASK, "modem_user": "updated"})
        assert config.get("admin_password") == hash1

    def test_admin_password_masked_in_get_all(self, config):
        config.save({"admin_password": "secret"})
        all_config = config.get_all(mask_secrets=True)
        assert all_config["admin_password"] == PASSWORD_MASK

    def test_bqm_password_encrypted_at_rest(self, config, tmp_data_dir):
        config.save({"bqm_password": "secret123"})
        with open(os.path.join(tmp_data_dir, "config.json")) as f:
            raw = json.load(f)
        assert raw["bqm_password"] != "secret123"
        assert config.get("bqm_password") == "secret123"


class TestConfigEnvOverride:
    def test_env_overrides_file(self, tmp_data_dir, monkeypatch):
        config = ConfigManager(tmp_data_dir)
        config.save({"modem_url": "http://from-file"})

        monkeypatch.setenv("MODEM_URL", "http://from-env")
        assert config.get("modem_url") == "http://from-env"

    def test_env_overrides_default(self, tmp_data_dir, monkeypatch):
        monkeypatch.setenv("POLL_INTERVAL", "600")
        config = ConfigManager(tmp_data_dir)
        assert config.get("poll_interval") == 600

    def test_empty_env_ignored(self, tmp_data_dir, monkeypatch):
        monkeypatch.setenv("MODEM_USER", "")
        config = ConfigManager(tmp_data_dir)
        assert config.get("modem_user") == ""  # falls through to default

    def test_legacy_fritz_env_fallback(self, tmp_data_dir, monkeypatch):
        """Deprecated FRITZ_* env vars still work as fallback."""
        monkeypatch.setenv("FRITZ_URL", "http://legacy-fritz")
        config = ConfigManager(tmp_data_dir)
        assert config.get("modem_url") == "http://legacy-fritz"

    def test_modem_env_takes_priority_over_fritz(self, tmp_data_dir, monkeypatch):
        """MODEM_* env vars take priority over deprecated FRITZ_*."""
        monkeypatch.setenv("MODEM_URL", "http://new-modem")
        monkeypatch.setenv("FRITZ_URL", "http://old-fritz")
        config = ConfigManager(tmp_data_dir)
        assert config.get("modem_url") == "http://new-modem"


class TestConfigMigration:
    def test_legacy_fritz_keys_migrated(self, tmp_data_dir):
        """Old config.json with fritz_* keys should be auto-migrated to modem_*."""
        os.makedirs(tmp_data_dir, exist_ok=True)
        # Write a legacy config.json with fritz_* keys
        legacy_config = {"fritz_url": "http://old-box", "fritz_user": "legacy"}
        with open(os.path.join(tmp_data_dir, "config.json"), "w") as f:
            json.dump(legacy_config, f)
        # ConfigManager should migrate on load
        config = ConfigManager(tmp_data_dir)
        assert config.get("modem_url") == "http://old-box"
        assert config.get("modem_user") == "legacy"
        # Old keys should be gone from the file
        with open(os.path.join(tmp_data_dir, "config.json")) as f:
            raw = json.load(f)
        assert "fritz_url" not in raw
        assert "modem_url" in raw


class TestConfigState:
    def test_is_configured_with_modem_type(self, config):
        config.save({"modem_type": "fritzbox"})
        assert config.is_configured() is True

    def test_is_configured_without_password(self, config):
        config.save({"modem_type": "generic"})
        assert config.is_configured() is True

    def test_not_configured_without_modem_type(self, config):
        config.save({"modem_password": "pass123"})
        assert config.is_configured() is False

    def test_is_mqtt_configured(self, config):
        config.save({"mqtt_host": "broker.local"})
        assert config.is_mqtt_configured() is True

    def test_theme_validation(self, config):
        assert config.get_theme() == "dark"
        config.save({"theme": "light"})
        assert config.get_theme() == "light"
        config.save({"theme": "invalid"})
        assert config.get_theme() == "dark"

    def test_segment_utilization_enabled_defaults_true(self, config):
        assert config.is_segment_utilization_enabled() is True

    def test_segment_utilization_enabled_can_be_disabled(self, config):
        config.save({"segment_utilization_enabled": False})
        assert config.is_segment_utilization_enabled() is False

    def test_existing_smokeping_config_keeps_module_enabled(self, config):
        config.save({
            "smokeping_url": "https://smokeping.example.com/smokeping",
            "smokeping_targets": "InternetSites.Google",
        })
        assert config.get("disabled_modules") == ""

    def test_explicit_disabled_modules_override_is_preserved(self, config):
        config.save({"disabled_modules": "docsight.smokeping,test.integration"})
        assert config.get("disabled_modules") == "docsight.smokeping,test.integration"

    def test_bqm_requires_credentials(self, config):
        assert config.is_bqm_configured() is False
        config.save({"bqm_username": "user", "bqm_password": "pass"})
        assert config.is_bqm_configured() is False
        config.save({"bqm_username": "user", "bqm_password": "pass", "bqm_monitor_id": "12345"})
        assert config.is_bqm_configured() is True


class TestConfigUrlValidation:
    @pytest.mark.parametrize("url", [
        "http://192.168.1.1",
        "https://example.com",
        "http://modem.local:8080/status",
        "https://speedtest.example.com/api",
    ])
    def test_valid_urls_accepted(self, config, url):
        for key in URL_KEYS:
            config.save({key: url})
            assert config.get(key) == url

    @pytest.mark.parametrize("url", [
        "file:///etc/passwd",
        "gopher://evil.com",
        "ftp://files.local/data",
        "javascript:alert(1)",
        "data:text/html,<h1>hi</h1>",
    ])
    def test_forbidden_schemes_rejected(self, config, url):
        for key in URL_KEYS:
            with pytest.raises(ValueError, match="Only http and https are allowed"):
                config.save({key: url})

    def test_empty_url_allowed(self, config):
        for key in URL_KEYS:
            config.save({key: ""})

    def test_valid_data_alongside_bad_url_not_saved(self, config):
        config.save({"modem_user": "before"})
        with pytest.raises(ValueError):
            config.save({"modem_user": "after", "modem_url": "file:///etc/passwd"})
        assert config.get("modem_user") == "before"
