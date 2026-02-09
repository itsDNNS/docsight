"""Configuration management with persistent config.json + env var overrides."""

import json
import logging
import os
import stat

from cryptography.fernet import Fernet

log = logging.getLogger("docsis.config")

POLL_MIN = 60
POLL_MAX = 3600

SECRET_KEYS = {"fritz_password", "mqtt_password"}
PASSWORD_MASK = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"

DEFAULTS = {
    "fritz_url": "http://192.168.178.1",
    "fritz_user": "",
    "fritz_password": "",
    "mqtt_host": "",
    "mqtt_port": 1883,
    "mqtt_user": "",
    "mqtt_password": "",
    "mqtt_topic_prefix": "fritzbox/docsis",
    "poll_interval": 300,
    "web_port": 8765,
    "history_days": 7,
    "theme": "dark",
}

ENV_MAP = {
    "fritz_url": "FRITZ_URL",
    "fritz_user": "FRITZ_USER",
    "fritz_password": "FRITZ_PASSWORD",
    "mqtt_host": "MQTT_HOST",
    "mqtt_port": "MQTT_PORT",
    "mqtt_user": "MQTT_USER",
    "mqtt_password": "MQTT_PASSWORD",
    "mqtt_topic_prefix": "MQTT_TOPIC_PREFIX",
    "poll_interval": "POLL_INTERVAL",
    "web_port": "WEB_PORT",
    "history_days": "HISTORY_DAYS",
    "data_dir": "DATA_DIR",
}

INT_KEYS = {"mqtt_port", "poll_interval", "web_port", "history_days"}


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
        """Load config.json if it exists."""
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r") as f:
                    self._file_config = json.load(f)
                log.info("Loaded config from %s", self.config_path)
            except Exception as e:
                log.warning("Failed to load config.json: %s", e)
                self._file_config = {}
        else:
            log.info("No config.json found, using defaults/env")

    def get(self, key, default=None):
        """Get config value: env var > config.json > default.
        Secret keys from config.json are decrypted transparently."""
        # Env vars are never encrypted
        env_name = ENV_MAP.get(key)
        if env_name:
            env_val = os.environ.get(env_name)
            if env_val is not None and env_val != "":
                if key in INT_KEYS:
                    return int(env_val)
                return env_val

        if key in self._file_config:
            val = self._file_config[key]
            if key in INT_KEYS and not isinstance(val, int):
                return int(val)
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
        for key in SECRET_KEYS:
            if key in data and data[key] == PASSWORD_MASK:
                del data[key]

        # Encrypt secret values before storing
        for key in SECRET_KEYS:
            if key in data and data[key]:
                data[key] = self._encrypt(data[key])

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
        """True if fritz_password is set (from env or config.json)."""
        return bool(self.get("fritz_password"))

    def is_mqtt_configured(self):
        """True if mqtt_host is set (MQTT is optional)."""
        return bool(self.get("mqtt_host"))

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
            if mask_secrets and key in SECRET_KEYS and val:
                result[key] = PASSWORD_MASK
            else:
                result[key] = val
        result["data_dir"] = os.environ.get("DATA_DIR", self.data_dir)
        return result
