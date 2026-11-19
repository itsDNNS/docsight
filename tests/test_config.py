"""Tests for configuration management."""

import json
import os
import pytest
from app.config import (
    ConfigManager,
    DEFAULTS,
    ENV_MAP,
    PASSWORD_MASK,
    URL_KEYS,
    parse_config_bool,
)
from app.doctor import _check_admin_password, _check_backup, _check_configured_mode, _check_integrations
from app.smart_capture.engine import SmartCaptureEngine
from app.web_auth import auth_disabled_requested


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

    def test_default_value_is_not_reported_as_stored(self, config):
        assert config.get("language") == "en"
        assert config.has_stored_value("language") is False


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (True, True),
        (False, False),
        (None, False),
        ("  TRUE  ", True),
        ("1", True),
        ("yes", True),
        ("On", True),
        (1, True),
        ("false", False),
        ("0", False),
        ("off", False),
        ("", False),
        (object(), False),
    ],
)
def test_parse_config_bool_preserves_config_payload_semantics(value, expected):
    assert parse_config_bool(value) is expected


@pytest.mark.parametrize(
    ("value", "enabled", "tls_insecure"),
    [("on", True, True), (" yes ", True, True), ("off", False, False), (1, True, True), (0, False, False),
     (None, False, False), (2, True, False), (1.0, True, False), ([1], True, False)],
)
def test_stored_bool_readers_keep_their_meaning(tmp_data_dir, monkeypatch, value, enabled, tls_insecure):
    stored = {"demo_mode": value, "update_check_enabled": value, "sc_enabled": value, "notify_apprise_enabled": value,
              "notify_apprise_url": "x", "backup_enabled": value, "backup_path": tmp_data_dir,
              "metrics_require_token": value, "speedtest_tls_insecure": value}
    for key in stored.keys() & ENV_MAP.keys():
        monkeypatch.delenv(ENV_MAP[key], raising=False)
    os.makedirs(tmp_data_dir)
    with open(os.path.join(tmp_data_dir, "config.json"), "w") as f:
        json.dump(stored, f)
    config = ConfigManager(tmp_data_dir)

    assert config.is_demo_mode() is enabled
    assert config.is_update_check_enabled() is enabled
    assert config.is_backup_configured() is enabled
    assert bool(config.get("metrics_require_token")) is enabled
    assert SmartCaptureEngine(None, config)._is_enabled() is enabled
    assert _check_configured_mode(stored, {}).details["demo_mode"] is enabled
    assert _check_backup(stored, {}).details["enabled"] is enabled
    apprise = next(check for check in _check_integrations(stored, {}) if check.id == "integration.apprise")
    assert apprise.details["enabled"] is enabled
    assert (_check_admin_password(stored, {}).status == "skipped") is enabled
    assert parse_config_bool(config.get("speedtest_tls_insecure")) is tls_insecure


@pytest.mark.parametrize(("value", "expected"), [("on", True), (" yes ", True), ("off", False), ("2", False)])
def test_bool_env_values_follow_parse_config_bool(config, monkeypatch, value, expected):
    monkeypatch.setenv("DEMO_MODE", value)

    assert config.get("demo_mode") is expected
    assert config.is_demo_mode_forced() is expected
    assert auth_disabled_requested({"AUTH_DISABLED": value}) is expected


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

    def test_saved_value_is_reported_as_stored_after_reload(self, tmp_data_dir):
        config = ConfigManager(tmp_data_dir)
        config.save({"language": "de"})

        reloaded = ConfigManager(tmp_data_dir)

        assert reloaded.has_stored_value("language") is True

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
        ("off", False), ("", False), ("  yes  ", True),
    ])
    def test_bool_keys_cast(self, tmp_data_dir, value, expected):
        ConfigManager(tmp_data_dir).save({"demo_mode": value})
        with open(os.path.join(tmp_data_dir, "config.json")) as f:
            assert json.load(f)["demo_mode"] is expected


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

    @pytest.mark.parametrize("key", ["notify_apprise_key", "notify_apprise_token", "notify_pwa_push_vapid_private_key"])
    def test_notification_secret_mask_not_saved(self, tmp_data_dir, key):
        config = ConfigManager(tmp_data_dir)
        config.save({key: "original"})
        config.save({key: PASSWORD_MASK, "modem_user": "updated"})

        config2 = ConfigManager(tmp_data_dir)
        assert config2.get(key) == "original"
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

    def test_speedtest_token_encrypted_at_rest(self, config, tmp_data_dir):
        config.save({"speedtest_tracker_token": "secret123"})
        with open(os.path.join(tmp_data_dir, "config.json")) as f:
            raw = json.load(f)
        assert raw["speedtest_tracker_token"] != "secret123"
        assert config.get("speedtest_tracker_token") == "secret123"

    @pytest.mark.parametrize("key", ["notify_apprise_key", "notify_apprise_token", "notify_pwa_push_vapid_private_key"])
    def test_notification_secrets_encrypted_at_rest(self, config, tmp_data_dir, key):
        config.save({key: "secret123"})
        with open(os.path.join(tmp_data_dir, "config.json")) as f:
            raw = json.load(f)
        assert raw[key] != "secret123"
        assert config.get(key) == "secret123"

    def test_apprise_configured_when_enabled_with_url(self, config):
        config.save({"notify_apprise_enabled": "true", "notify_apprise_url": "http://apprise:8000"})
        assert config.is_notify_configured() is True

    def test_apprise_not_configured_without_url(self, config):
        config.save({"notify_apprise_enabled": "true", "notify_apprise_url": ""})
        assert config.is_notify_configured() is False

    def test_pwa_push_configured_when_enabled_with_vapid_keys(self, config):
        config.save({
            "notify_pwa_push_enabled": "true",
            "notify_pwa_push_vapid_public_key": "public-key",
            "notify_pwa_push_vapid_private_key": "private-key",
        })
        assert config.is_notify_configured() is True

    def test_pwa_push_not_configured_without_private_key(self, config):
        config.save({
            "notify_pwa_push_enabled": "true",
            "notify_pwa_push_vapid_public_key": "public-key",
            "notify_pwa_push_vapid_private_key": "",
        })
        assert config.is_notify_configured() is False


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

    def test_booked_speed_env_overrides(self, tmp_data_dir, monkeypatch):
        monkeypatch.setenv("BOOKED_DOWNLOAD", "1000")
        monkeypatch.setenv("BOOKED_UPLOAD", "50")
        config = ConfigManager(tmp_data_dir)
        assert config.get("booked_download") == 1000
        assert config.get("booked_upload") == 50

    def test_apprise_env_overrides(self, tmp_data_dir, monkeypatch):
        monkeypatch.setenv("NOTIFY_APPRISE_ENABLED", "true")
        monkeypatch.setenv("NOTIFY_APPRISE_URL", "http://apprise:8000")
        monkeypatch.setenv("NOTIFY_APPRISE_KEY", "default")
        monkeypatch.setenv("NOTIFY_APPRISE_TOKEN", "api-token")
        monkeypatch.setenv("NOTIFY_APPRISE_TAG", "ops")
        config = ConfigManager(tmp_data_dir)
        assert config.get("notify_apprise_enabled") is True
        assert config.get("notify_apprise_url") == "http://apprise:8000"
        assert config.get("notify_apprise_key") == "default"
        assert config.get("notify_apprise_token") == "api-token"
        assert config.get("notify_apprise_tag") == "ops"

    def test_pwa_push_env_overrides(self, tmp_data_dir, monkeypatch):
        monkeypatch.setenv("NOTIFY_PWA_PUSH_ENABLED", "true")
        monkeypatch.setenv("NOTIFY_PWA_PUSH_VAPID_PUBLIC_KEY", "public-key")
        monkeypatch.setenv("NOTIFY_PWA_PUSH_VAPID_PRIVATE_KEY", "private-key")
        monkeypatch.setenv("NOTIFY_PWA_PUSH_VAPID_SUBJECT", "mailto:ops@example.test")
        config = ConfigManager(tmp_data_dir)
        assert config.get("notify_pwa_push_enabled") is True
        assert config.get("notify_pwa_push_vapid_public_key") == "public-key"
        assert config.get("notify_pwa_push_vapid_private_key") == "private-key"
        assert config.get("notify_pwa_push_vapid_subject") == "mailto:ops@example.test"

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

    def test_bqm_requires_url(self, config):
        assert config.is_bqm_configured() is False
        config.save({"bqm_url": "https://www.thinkbroadband.com/broadband/monitoring/quality/share/abc123-2-y.csv"})
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


class TestConfigIntegerValidation:
    """Integer settings only store whole numbers; stored garbage never breaks reads (#875)."""

    @pytest.mark.parametrize("value,expected", [
        ("180", 180), (" 180 ", 180), (180, 180), (180.0, 180), ("-5", -5),
    ])
    def test_whole_numbers_accepted(self, config, value, expected):
        config.save({"history_days": value})
        assert config.get("history_days") == expected

    def test_empty_value_still_means_unset(self, config):
        config.save({"history_days": ""})
        assert config.get("history_days") == 0

    @pytest.mark.parametrize("value", ["1500.5", "1e3", "abc", "1,5", 1500.5, [], {}])
    def test_non_integers_rejected_without_saving_anything(self, config, value):
        config.save({"modem_user": "before", "history_days": 30})
        with pytest.raises(ValueError, match="history_days must be a whole number"):
            config.save({"modem_user": "after", "history_days": value})
        assert config.get("modem_user") == "before"
        assert config.get("history_days") == 30

    def test_module_integer_keys_are_validated(self, config, monkeypatch):
        import app.config as config_module

        key = "connection_monitor_poll_interval_ms"
        monkeypatch.setattr(config_module, "INT_KEYS", config_module.INT_KEYS | {key})
        with pytest.raises(ValueError, match=f"{key} must be a whole number"):
            config.save({key: "1500.5"})

    @pytest.mark.parametrize("stored", ["1500.5", "abc", [1]])
    def test_invalid_stored_value_falls_back_to_default(self, tmp_data_dir, stored, caplog, monkeypatch):
        import app.config as config_module

        monkeypatch.setattr(config_module, "_INVALID_INT_WARNED", set())
        os.makedirs(tmp_data_dir, exist_ok=True)
        with open(os.path.join(tmp_data_dir, "config.json"), "w") as f:
            json.dump({"poll_interval": stored}, f)
        config = ConfigManager(tmp_data_dir)
        assert config.get("poll_interval") == DEFAULTS["poll_interval"]
        assert config.get("poll_interval", 123) == 123
        assert config.get_all()["poll_interval"] == DEFAULTS["poll_interval"]
        assert "invalid stored integer setting" in caplog.text
        assert "poll_interval" not in caplog.text and str(stored) not in caplog.text

    def test_invalid_stored_value_is_logged_once(self, tmp_data_dir, caplog, monkeypatch):
        import app.config as config_module

        monkeypatch.setattr(config_module, "_INVALID_INT_WARNED", set())
        os.makedirs(tmp_data_dir, exist_ok=True)
        with open(os.path.join(tmp_data_dir, "config.json"), "w") as f:
            json.dump({"web_port": "80.5"}, f)
        config = ConfigManager(tmp_data_dir)
        for _ in range(3):
            config.get("web_port")
        assert caplog.text.count("invalid stored integer setting") == 1

    def test_unrelated_save_does_not_truncate_hand_edited_fraction(self, tmp_data_dir):
        os.makedirs(tmp_data_dir, exist_ok=True)
        with open(os.path.join(tmp_data_dir, "config.json"), "w") as f:
            json.dump({"history_days": 1500.5}, f)
        config = ConfigManager(tmp_data_dir)
        config.save({"modem_user": "x"})
        with open(os.path.join(tmp_data_dir, "config.json")) as f:
            assert json.load(f)["history_days"] == 1500.5


@pytest.mark.parametrize("url", ["http://[::1", ["http://a"], 42, 0, []])
def test_save_reports_unparsable_urls_without_library_text(tmp_path, url):
    from app.config import ConfigValueError

    with pytest.raises(ConfigValueError, match="^modem_url is not a valid URL$"):
        ConfigManager(str(tmp_path)).save({"modem_url": url})


def test_save_leaves_the_callers_values_unchanged(tmp_path):
    values = {"modem_password": "secret-value", "poll_interval": "300"}
    ConfigManager(str(tmp_path)).save(values)
    assert values == {"modem_password": "secret-value", "poll_interval": "300"}


@pytest.mark.parametrize("value", [12345, 0, False, []])
def test_save_rejects_secrets_that_are_not_text(tmp_path, value):
    from app.config import ConfigValueError

    with pytest.raises(ConfigValueError, match="^mqtt_password must be text$"):
        ConfigManager(str(tmp_path)).save({"mqtt_password": value})


def test_save_waits_while_values_are_read_together(tmp_path):
    import threading

    config = ConfigManager(str(tmp_path))
    config.save({"mqtt_host": "old.local"})
    save = threading.Thread(target=config.save, args=({"mqtt_host": "new.local"},))

    with config.locked():
        save.start()
        save.join(0.2)
        assert save.is_alive()
        assert config.get("mqtt_host") == "old.local"
    save.join(5)

    assert config.get("mqtt_host") == "new.local"
