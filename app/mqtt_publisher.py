"""MQTT publishing with Home Assistant Auto-Discovery."""

import json
import logging
import time

import paho.mqtt.client as mqtt

log = logging.getLogger("docsis.mqtt")


class MQTTPublisher:
    def __init__(self, host, port=1883, user=None, password=None,
                 topic_prefix="fritzbox/docsis", ha_prefix="homeassistant"):
        self.host = host
        self.port = port
        self.topic_prefix = topic_prefix
        self.ha_prefix = ha_prefix

        self.client = mqtt.Client(
            mqtt.CallbackAPIVersion.VERSION2,
            client_id="docsight",
        )
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
            log.error("MQTT connect failed: rc=%d", rc)

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        log.warning("MQTT disconnected (rc=%d)", rc)
        self._connected = False

    def connect(self):
        self.client.connect(self.host, self.port, 60)
        self.client.loop_start()
        # Wait briefly for connection
        for _ in range(20):
            if self._connected:
                break
            time.sleep(0.25)
        if not self._connected:
            raise ConnectionError(f"Could not connect to MQTT broker {self.host}:{self.port}")

    def disconnect(self):
        self.client.loop_stop()
        self.client.disconnect()

    def publish_discovery(self, device_info=None):
        """Publish HA MQTT Auto-Discovery for all sensors."""
        device = {
            "identifiers": ["docsight"],
            "name": "DOCSight",
            "manufacturer": "AVM",
            "model": (device_info or {}).get("model", "FRITZ!Box"),
        }
        sw = (device_info or {}).get("sw_version", "")
        if sw:
            device["sw_version"] = sw

        # --- Summary sensors ---
        summary_sensors = [
            ("ds_total", "Downstream Channels", None, "mdi:arrow-down-bold"),
            ("ds_power_min", "DS Power Min", "dBmV", "mdi:signal"),
            ("ds_power_max", "DS Power Max", "dBmV", "mdi:signal"),
            ("ds_power_avg", "DS Power Avg", "dBmV", "mdi:signal"),
            ("ds_snr_min", "DS SNR Min", "dB", "mdi:ear-hearing"),
            ("ds_snr_avg", "DS SNR Avg", "dB", "mdi:ear-hearing"),
            ("ds_correctable_errors", "DS Correctable Errors", None, "mdi:alert-circle-check"),
            ("ds_uncorrectable_errors", "DS Uncorrectable Errors", None, "mdi:alert-circle"),
            ("us_total", "Upstream Channels", None, "mdi:arrow-up-bold"),
            ("us_power_min", "US Power Min", "dBmV", "mdi:signal"),
            ("us_power_max", "US Power Max", "dBmV", "mdi:signal"),
            ("us_power_avg", "US Power Avg", "dBmV", "mdi:signal"),
            ("health", "DOCSIS Health", None, "mdi:heart-pulse"),
            ("health_details", "DOCSIS Details", None, "mdi:information"),
        ]

        count = 0
        for key, name, unit, icon in summary_sensors:
            topic = f"{self.ha_prefix}/sensor/docsight/{key}/config"
            config = {
                "name": name,
                "unique_id": f"docsight_{key}",
                "state_topic": f"{self.topic_prefix}/{key}",
                "icon": icon,
                "device": device,
            }
            if unit:
                config["unit_of_measurement"] = unit
            if key == "health":
                config["json_attributes_topic"] = f"{self.topic_prefix}/health/attributes"
            self.client.publish(topic, json.dumps(config), retain=True)
            count += 1

        log.info("Published HA discovery for %d summary sensors", count)

    def publish_channel_discovery(self, ds_channels, us_channels, device_info=None):
        """Publish HA MQTT Auto-Discovery for per-channel sensors."""
        device = {
            "identifiers": ["docsight"],
            "name": "DOCSight",
            "manufacturer": "AVM",
            "model": (device_info or {}).get("model", "FRITZ!Box"),
        }
        sw = (device_info or {}).get("sw_version", "")
        if sw:
            device["sw_version"] = sw

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
                "icon": "mdi:arrow-down-bold",
                "device": device,
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
                "icon": "mdi:arrow-up-bold",
                "device": device,
            }
            self.client.publish(topic, json.dumps(config), retain=True)
            count += 1

        log.info("Published HA discovery for %d per-channel sensors", count)

    def publish_data(self, analysis):
        """Publish all DOCSIS data via MQTT."""
        summary = analysis["summary"]
        ds_channels = analysis["ds_channels"]
        us_channels = analysis["us_channels"]

        # Summary sensors
        for key, value in summary.items():
            self.client.publish(
                f"{self.topic_prefix}/{key}", str(value), retain=True
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

        log.info(
            "Published data: DS=%d US=%d Health=%s",
            len(ds_channels), len(us_channels), summary.get("health", "?"),
        )
