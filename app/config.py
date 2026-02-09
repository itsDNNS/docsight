"""Configuration management with persistent config.json + env var overrides."""

import json
import logging
import os

log = logging.getLogger("docsis.config")

POLL_MIN = 60
POLL_MAX = 3600

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
    """Loads config from config.json, env vars override file values."""

    def __init__(self, data_dir="/data"):
        self.data_dir = data_dir
        self.config_path = os.path.join(data_dir, "config.json")
        self._file_config = {}
        self._load()

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
        """Get config value: env var > config.json > default."""
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
            return val

        if default is not None:
            return default
        return DEFAULTS.get(key)

    def save(self, data):
        """Save config values to config.json."""
        os.makedirs(os.path.dirname(self.config_path), exist_ok=True)
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

    def get_all(self):
        """Return all config values as dict."""
        result = {}
        for key in DEFAULTS:
            result[key] = self.get(key)
        result["data_dir"] = os.environ.get("DATA_DIR", self.data_dir)
        return result
