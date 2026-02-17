"""MQTT publishing with Home Assistant Auto-Discovery."""

import json
import logging
import re
import time

import paho.mqtt.client as mqtt

log = logging.getLogger("docsis.mqtt")

_MQTT_UNSAFE_RE = re.compile(r"[#+\x00]")


def _sanitize_topic(topic):
    """Remove MQTT wildcard characters and normalize slashes."""
    topic = _MQTT_UNSAFE_RE.sub("", topic)
    topic = re.sub(r"/+", "/", topic).strip("/")
    return topic[:200]


class MQTTPublisher:
    def __init__(self, host, port=1883, user=None, password=None,
                 topic_prefix="fritzbox/docsis", ha_prefix="homeassistant",
                 tls_insecure=False, web_port=8765, public_url=""):
        self.host = host
        self.port = port
        self.topic_prefix = _sanitize_topic(topic_prefix)
        self.ha_prefix = _sanitize_topic(ha_prefix)
        self.public_url = public_url.rstrip("/") if public_url else f"http://docsight:{web_port}"

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="docsight",
        )
        # Enable TLS if using secure port (8883)
        if port == 8883:
            self.client.tls_set()
            if tls_insecure:
                self.client.tls_insecure_set(True)
                log.warning("MQTT TLS certificate verification disabled (insecure mode)")

        if user:
            self.client.username_pw_set(user, password)

        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self._connected = False

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        if rc == 0:
            log.info("MQTT connected to %s:%d", self.host, self.port)
            self._connected = True
        else:
            log.error("MQTT connect failed: rc=%s", rc)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        log.warning("MQTT disconnected (rc=%s)", rc)
        self._connected = False

    @property
    def _status_topic(self):
        return f"{self.topic_prefix}/status"

    def connect(self):
        # LWT: broker publishes "offline" if we disconnect unexpectedly
        self.client.will_set(self._status_topic, "offline", retain=True)
        self.client.connect(self.host, self.port, 60)
        self.client.loop_start()
        # Wait briefly for connection
        for _ in range(20):
            if self._connected:
                break
            time.sleep(0.25)
        if not self._connected:
            raise ConnectionError(f"Could not connect to MQTT broker {self.host}:{self.port}")
        # Birth message
        self.client.publish(self._status_topic, "online", retain=True)

    def disconnect(self):
        self.client.publish(self._status_topic, "offline", retain=True)
        self.client.loop_stop()
        self.client.disconnect()

    def _build_device(self, device_info=None):
        """Build HA device object from device_info."""
        info = device_info or {}
        device = {
            "identifiers": ["docsight"],
            "name": "DOCSight",
            "manufacturer": info.get("manufacturer", "Unknown"),
            "model": info.get("model", "Cable Modem"),
            "configuration_url": self.public_url,
        }
        sw = info.get("sw_version", "")
        if sw:
            device["sw_version"] = sw
        return device

    def _availability(self):
        """Return HA availability config block."""
        return {
            "availability_topic": self._status_topic,
            "payload_available": "online",
            "payload_not_available": "offline",
        }

    def publish_discovery(self, device_info=None):
        """Publish HA MQTT Auto-Discovery for all sensors."""
        device = self._build_device(device_info)
        avail = self._availability()

        # --- Summary sensors (key, name, unit, icon, enabled_by_default) ---
        summary_sensors = [
            ("ds_total", "Downstream Channels", None, "mdi:arrow-down-bold", False),
            ("ds_power_min", "DS Power Min", "dBmV", "mdi:signal", False),
            ("ds_power_max", "DS Power Max", "dBmV", "mdi:signal", False),
            ("ds_power_avg", "DS Power Avg", "dBmV", "mdi:signal", True),
            ("ds_snr_min", "DS SNR Min", "dB", "mdi:ear-hearing", True),
            ("ds_snr_avg", "DS SNR Avg", "dB", "mdi:ear-hearing", True),
            ("ds_correctable_errors", "DS Correctable Errors", None, "mdi:alert-circle-check", True),
            ("ds_uncorrectable_errors", "DS Uncorrectable Errors", None, "mdi:alert-circle", True),
            ("us_total", "Upstream Channels", None, "mdi:arrow-up-bold", False),
            ("us_power_min", "US Power Min", "dBmV", "mdi:signal", False),
            ("us_power_max", "US Power Max", "dBmV", "mdi:signal", False),
            ("us_power_avg", "US Power Avg", "dBmV", "mdi:signal", True),
            ("health_details", "DOCSIS Details", None, "mdi:information", True),
        ]

        count = 0
        for key, name, unit, icon, enabled in summary_sensors:
            topic = f"{self.ha_prefix}/sensor/docsight/{key}/config"
            config = {
                "name": name,
                "unique_id": f"docsight_{key}",
                "state_topic": f"{self.topic_prefix}/{key}",
                "icon": icon,
                "device": device,
                "entity_category": "diagnostic",
                "enabled_by_default": enabled,
                **avail,
            }
            if unit:
                config["unit_of_measurement"] = unit
                config["state_class"] = "measurement"
            self.client.publish(topic, json.dumps(config), retain=True)
            count += 1

        # --- Health as binary_sensor with device_class=problem ---
        health_topic = f"{self.ha_prefix}/binary_sensor/docsight/health/config"
        health_config = {
            "name": "DOCSIS Health",
            "unique_id": "docsight_health",
            "state_topic": f"{self.topic_prefix}/health",
            "value_template": "{{ 'ON' if value not in ['Good', 'good'] else 'OFF' }}",
            "device_class": "problem",
            "icon": "mdi:heart-pulse",
            "device": device,
            "entity_category": "diagnostic",
            "json_attributes_topic": f"{self.topic_prefix}/health/attributes",
            **avail,
        }
        self.client.publish(health_topic, json.dumps(health_config), retain=True)
        count += 1

        # --- DOCSight Status as binary_sensor with device_class=running ---
        status_topic = f"{self.ha_prefix}/binary_sensor/docsight/status/config"
        status_config = {
            "name": "Status",
            "unique_id": "docsight_status",
            "state_topic": self._status_topic,
            "payload_on": "online",
            "payload_off": "offline",
            "device_class": "running",
            "icon": "mdi:monitor-eye",
            "device": device,
            "entity_category": "diagnostic",
        }
        self.client.publish(status_topic, json.dumps(status_config), retain=True)
        count += 1

        # --- Gaming Quality sensors ---
        gaming_sensors = [
            ("gaming_quality_score", "Gaming Quality Score", "%", "mdi:gamepad-variant", "measurement"),
            ("gaming_quality_grade", "Gaming Quality Grade", None, "mdi:gamepad-variant", None),
        ]
        for key, name, unit, icon, state_class in gaming_sensors:
            topic = f"{self.ha_prefix}/sensor/docsight/{key}/config"
            config = {
                "name": name,
                "unique_id": f"docsight_{key}",
                "state_topic": f"{self.topic_prefix}/{key}",
                "icon": icon,
                "device": device,
                "entity_category": "diagnostic",
                **avail,
            }
            if unit:
                config["unit_of_measurement"] = unit
            if state_class:
                config["state_class"] = state_class
            self.client.publish(topic, json.dumps(config), retain=True)
            count += 1

        log.info("Published HA discovery for %d sensors", count)

    def publish_channel_discovery(self, ds_channels, us_channels, device_info=None):
        """Publish HA MQTT Auto-Discovery for per-channel sensors."""
        device = self._build_device(device_info)
        avail = self._availability()

        count = 0
        for ch in ds_channels:
            ch_id = ch["channel_id"]
            obj_id = f"ds_ch{ch_id}"
            topic = f"{self.ha_prefix}/sensor/docsight/{obj_id}/config"
            config = {
                "name": f"DS Channel {ch_id}",
                "unique_id": f"docsight_{obj_id}",
                "state_topic": f"{self.topic_prefix}/channel/{obj_id}",
                "value_template": "{{ value_json.power }}",
                "json_attributes_topic": f"{self.topic_prefix}/channel/{obj_id}",
                "json_attributes_template": "{{ value_json | tojson }}",
                "unit_of_measurement": "dBmV",
                "state_class": "measurement",
                "icon": "mdi:arrow-down-bold",
                "device": device,
                "entity_category": "diagnostic",
                "enabled_by_default": False,
                **avail,
            }
            self.client.publish(topic, json.dumps(config), retain=True)
            count += 1

        for ch in us_channels:
            ch_id = ch["channel_id"]
            obj_id = f"us_ch{ch_id}"
            topic = f"{self.ha_prefix}/sensor/docsight/{obj_id}/config"
            config = {
                "name": f"US Channel {ch_id}",
                "unique_id": f"docsight_{obj_id}",
                "state_topic": f"{self.topic_prefix}/channel/{obj_id}",
                "value_template": "{{ value_json.power }}",
                "json_attributes_topic": f"{self.topic_prefix}/channel/{obj_id}",
                "json_attributes_template": "{{ value_json | tojson }}",
                "unit_of_measurement": "dBmV",
                "state_class": "measurement",
                "icon": "mdi:arrow-up-bold",
                "device": device,
                "entity_category": "diagnostic",
                "enabled_by_default": False,
                **avail,
            }
            self.client.publish(topic, json.dumps(config), retain=True)
            count += 1

        log.info("Published HA discovery for %d per-channel sensors", count)

    def publish_data(self, analysis, gaming_index=None):
        """Publish all DOCSIS data via MQTT."""
        summary = analysis["summary"]
        ds_channels = analysis["ds_channels"]
        us_channels = analysis["us_channels"]

        # Summary sensors
        health_issues = summary.get("health_issues", [])
        for key, value in summary.items():
            if key == "health_issues":
                continue
            self.client.publish(
                f"{self.topic_prefix}/{key}", str(value), retain=True
            )

        # Health details (human-readable summary of issues)
        _ISSUE_LABELS = {
            "ds_power_critical": "DS power critical",
            "ds_power_warn": "DS power warning",
            "us_power_critical": "US power critical",
            "us_power_warn": "US power warning",
            "snr_critical": "SNR critical",
            "snr_warn": "SNR warning",
            "uncorr_errors_high": "High uncorrectable errors",
        }
        details = ", ".join(_ISSUE_LABELS.get(i, i) for i in health_issues)
        self.client.publish(
            f"{self.topic_prefix}/health_details",
            details or "No issues",
            retain=True,
        )

        # Health attributes
        attrs = {"last_update": time.strftime("%Y-%m-%d %H:%M:%S")}
        self.client.publish(
            f"{self.topic_prefix}/health/attributes",
            json.dumps(attrs),
            retain=True,
        )

        # Per-channel data
        for ch in ds_channels:
            ch_id = ch["channel_id"]
            payload = {
                "power": ch["power"],
                "frequency": ch["frequency"],
                "modulation": ch["modulation"],
                "snr": ch["snr"],
                "correctable_errors": ch["correctable_errors"],
                "uncorrectable_errors": ch["uncorrectable_errors"],
                "docsis_version": ch["docsis_version"],
                "health": ch["health"],
            }
            self.client.publish(
                f"{self.topic_prefix}/channel/ds_ch{ch_id}",
                json.dumps(payload),
                retain=True,
            )

        for ch in us_channels:
            ch_id = ch["channel_id"]
            payload = {
                "power": ch["power"],
                "frequency": ch["frequency"],
                "modulation": ch["modulation"],
                "multiplex": ch.get("multiplex", ""),
                "docsis_version": ch["docsis_version"],
                "health": ch["health"],
            }
            self.client.publish(
                f"{self.topic_prefix}/channel/us_ch{ch_id}",
                json.dumps(payload),
                retain=True,
            )

        # Gaming Quality Index
        if gaming_index:
            self.client.publish(
                f"{self.topic_prefix}/gaming_quality_score",
                str(gaming_index["score"]),
                retain=True,
            )
            self.client.publish(
                f"{self.topic_prefix}/gaming_quality_grade",
                gaming_index["grade"],
                retain=True,
            )

        log.info(
            "Published data: DS=%d US=%d Health=%s",
            len(ds_channels), len(us_channels), summary.get("health", "?"),
        )
