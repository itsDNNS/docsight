"""Configuration management with persistent config.json + env var overrides."""

import json
import logging
import os
import stat

from cryptography.fernet import Fernet
from werkzeug.security import generate_password_hash

log = logging.getLogger("docsis.config")

POLL_MIN = 60
POLL_MAX = 14400

SECRET_KEYS = {"modem_password", "mqtt_password", "speedtest_tracker_token"}
HASH_KEYS = {"admin_password"}
PASSWORD_MASK = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"

# Modem-specific default configurations
MODEM_DEFAULTS = {
    "fritzbox": {
        "modem_url": "http://192.168.178.1",
        "modem_user": "",
    },
    "vodafone": {
        "modem_url": "http://192.168.0.1",
        "modem_user": "admin",
    },
}

DEFAULTS = {
    "modem_type": "fritzbox",
    "modem_url": "http://192.168.178.1",
    "modem_user": "",
    "modem_password": "",
    "mqtt_host": "",
    "mqtt_port": 1883,
    "mqtt_user": "",
    "mqtt_password": "",
    "mqtt_topic_prefix": "docsight",
    "mqtt_discovery_prefix": "homeassistant",
    "poll_interval": 900,
    "web_port": 8765,
    "history_days": 0,
    "snapshot_time": "06:00",
    "theme": "dark",
    "language": "en",
    "isp_name": "",
    "admin_password": "",
    "bqm_url": "",
    "speedtest_tracker_url": "",
    "speedtest_tracker_token": "",
    "booked_download": 0,
    "booked_upload": 0,
}

ENV_MAP = {
    "modem_type": "MODEM_TYPE",
    "modem_url": "MODEM_URL",
    "modem_user": "MODEM_USER",
    "modem_password": "MODEM_PASSWORD",
    "mqtt_host": "MQTT_HOST",
    "mqtt_port": "MQTT_PORT",
    "mqtt_user": "MQTT_USER",
    "mqtt_password": "MQTT_PASSWORD",
    "mqtt_topic_prefix": "MQTT_TOPIC_PREFIX",
    "mqtt_discovery_prefix": "MQTT_DISCOVERY_PREFIX",
    "poll_interval": "POLL_INTERVAL",
    "web_port": "WEB_PORT",
    "history_days": "HISTORY_DAYS",
    "data_dir": "DATA_DIR",
    "admin_password": "ADMIN_PASSWORD",
    "bqm_url": "BQM_URL",
    "speedtest_tracker_url": "SPEEDTEST_TRACKER_URL",
    "speedtest_tracker_token": "SPEEDTEST_TRACKER_TOKEN",
}

# Deprecated env vars (FRITZ_* -> MODEM_*) - checked as fallback
_LEGACY_ENV_MAP = {
    "modem_url": "FRITZ_URL",
    "modem_user": "FRITZ_USER",
    "modem_password": "FRITZ_PASSWORD",
}

# Deprecated config keys (fritz_* -> modem_*) - migrated on load
_LEGACY_KEY_MAP = {
    "fritz_url": "modem_url",
    "fritz_user": "modem_user",
    "fritz_password": "modem_password",
}

INT_KEYS = {"mqtt_port", "poll_interval", "web_port", "history_days", "booked_download", "booked_upload"}

# Keys where an empty string should fall back to the DEFAULTS value
_NON_EMPTY_KEYS = {"mqtt_topic_prefix", "mqtt_discovery_prefix"}


class ConfigManager:
    """Loads config from config.json, env vars override file values.
    Passwords are encrypted at rest using Fernet (AES-128-CBC)."""

    def __init__(self, data_dir="/data"):
        self.data_dir = data_dir
        self.config_path = os.path.join(data_dir, "config.json")
        self._key_path = os.path.join(data_dir, ".config_key")
        self._file_config = {}
        self._fernet = self._init_fernet()
        self._load()

    def _init_fernet(self):
        """Load or generate encryption key."""
        os.makedirs(self.data_dir, exist_ok=True)
        if os.path.exists(self._key_path):
            with open(self._key_path, "rb") as f:
                key = f.read().strip()
        else:
            key = Fernet.generate_key()
            with open(self._key_path, "wb") as f:
                f.write(key)
            try:
                os.chmod(self._key_path, stat.S_IRUSR | stat.S_IWUSR)
            except OSError:
                pass
            log.info("Generated new encryption key")
        return Fernet(key)

    def _encrypt(self, value):
        """Encrypt a string value."""
        if not value:
            return ""
        return self._fernet.encrypt(value.encode()).decode()

    def _decrypt(self, value):
        """Decrypt a string value. Returns plaintext on failure (migration)."""
        if not value:
            return ""
        try:
            return self._fernet.decrypt(value.encode()).decode()
        except Exception:
            # Value is likely plaintext (pre-encryption migration)
            return value

    def _load(self):
        """Load config.json if it exists. Migrates legacy fritz_* keys to modem_*."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    self._file_config = json.load(f)
                log.info("Loaded config from %s", self.config_path)
                self._migrate_legacy_keys()
            except Exception as e:
                log.warning("Failed to load config.json: %s", e)
                self._file_config = {}
        else:
            log.info("No config.json found, using defaults/env")

    def _migrate_legacy_keys(self):
        """Migrate fritz_* config keys to modem_* (backwards compatibility)."""
        migrated = False
        for old_key, new_key in _LEGACY_KEY_MAP.items():
            if old_key in self._file_config and new_key not in self._file_config:
                self._file_config[new_key] = self._file_config.pop(old_key)
                migrated = True
            elif old_key in self._file_config:
                del self._file_config[old_key]
                migrated = True
        if migrated:
            try:
                with open(self.config_path, "w") as f:
                    json.dump(self._file_config, f, indent=2)
                log.info("Migrated legacy fritz_* keys to modem_*")
            except Exception as e:
                log.warning("Failed to save migrated config: %s", e)

    def get(self, key, default=None):
        """Get config value: env var > legacy env var > config.json > default.
        Secret keys from config.json are decrypted transparently."""
        # Env vars are never encrypted
        env_name = ENV_MAP.get(key)
        if env_name:
            env_val = os.environ.get(env_name)
            if env_val is not None and env_val != "":
                if key in INT_KEYS:
                    return int(env_val)
                return env_val
        # Check deprecated FRITZ_* env vars as fallback
        legacy_env = _LEGACY_ENV_MAP.get(key)
        if legacy_env:
            env_val = os.environ.get(legacy_env)
            if env_val is not None and env_val != "":
                return env_val

        if key in self._file_config:
            val = self._file_config[key]
            # Keys that must not be empty: fall through to defaults
            if key in _NON_EMPTY_KEYS and not val:
                return DEFAULTS[key]
            if key in INT_KEYS and not isinstance(val, int):
                if val == "" or val is None:
                    return default if default is not None else 0
                return int(val)
            if key in HASH_KEYS:
                # Return werkzeug hash as-is; legacy Fernet-encrypted values get decrypted
                if val and (val.startswith("scrypt:") or val.startswith("pbkdf2:")):
                    return val
                return self._decrypt(val)
            if key in SECRET_KEYS:
                return self._decrypt(val)
            return val

        if default is not None:
            return default
        return DEFAULTS.get(key)

    def save(self, data):
        """Save config values to config.json. Passwords are encrypted."""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)

        # Don't overwrite passwords with the mask placeholder
        for key in SECRET_KEYS | HASH_KEYS:
            if key in data and data[key] == PASSWORD_MASK:
                del data[key]

        # Hash password keys (admin_password) before storing
        for key in HASH_KEYS:
            if key in data and data[key]:
                if not (data[key].startswith("scrypt:") or data[key].startswith("pbkdf2:")):
                    data[key] = generate_password_hash(data[key])

        # Encrypt secret values before storing
        for key in SECRET_KEYS:
            if key in data and data[key]:
                data[key] = self._encrypt(data[key])

        # Replace empty strings with defaults for keys that require a value
        for key in _NON_EMPTY_KEYS:
            if key in data and not data[key]:
                data[key] = DEFAULTS[key]

        # Merge with existing config
        self._file_config.update(data)

        # Cast int keys
        for key in INT_KEYS:
            if key in self._file_config:
                try:
                    self._file_config[key] = int(self._file_config[key])
                except (ValueError, TypeError):
                    pass

        with open(self.config_path, "w") as f:
            json.dump(self._file_config, f, indent=2)
        try:
            os.chmod(self.config_path, stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass
        log.info("Config saved to %s", self.config_path)

    def is_configured(self):
        """True if modem_password is set (from env or config.json)."""
        return bool(self.get("modem_password"))

    def is_mqtt_configured(self):
        """True if mqtt_host is set (MQTT is optional)."""
        return bool(self.get("mqtt_host"))

    def is_bqm_configured(self):
        """True if bqm_url is set (BQM is optional)."""
        return bool(self.get("bqm_url"))

    def is_speedtest_configured(self):
        """True if speedtest_tracker_url and token are set (optional)."""
        return bool(self.get("speedtest_tracker_url") and self.get("speedtest_tracker_token"))

    def get_theme(self):
        """Return 'dark' or 'light'."""
        theme = self.get("theme", "dark")
        return theme if theme in ("dark", "light") else "dark"

    def get_all(self, mask_secrets=False):
        """Return all config values as dict.
        If mask_secrets=True, password fields show a mask instead of real values."""
        result = {}
        for key in DEFAULTS:
            val = self.get(key)
            if mask_secrets and key in (SECRET_KEYS | HASH_KEYS) and val:
                result[key] = PASSWORD_MASK
            else:
                result[key] = val
        result["data_dir"] = os.environ.get("DATA_DIR", self.data_dir)
        return result
