"""Demo collector — generates realistic DOCSIS data for testing without a real modem."""

import copy
import json
import logging
import os
import random
import time

from .base import Collector, CollectorResult

log = logging.getLogger("docsis.collector.demo")

_FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "..", "fixtures")
_BASE_DATA = None


def _load_base_data():
    """Load channel definitions from demo_channels.json (once)."""
    global _BASE_DATA
    if _BASE_DATA is None:
        path = os.path.join(_FIXTURES_DIR, "demo_channels.json")
        with open(path) as f:
            _BASE_DATA = json.load(f)
    return _BASE_DATA


class DemoCollector(Collector):
    """Generates realistic DOCSIS data with slight random variation per poll.

    Uses the real analyzer pipeline — only the data source is simulated.
    """

    name = "demo"

    def __init__(self, analyzer_fn, event_detector, storage, mqtt_pub, web, poll_interval):
        super().__init__(poll_interval)
        self._analyzer = analyzer_fn
        self._event_detector = event_detector
        self._storage = storage
        self._mqtt_pub = mqtt_pub
        self._web = web
        self._discovery_published = False
        self._poll_count = 0
        self._device_info = {
            "model": "DOCSight Demo Router",
            "sw_version": "Demo v2.0",
            "uptime_seconds": 0,
        }
        self._connection_info = {
            "max_downstream_kbps": 250000,
            "max_upstream_kbps": 40000,
            "connection_type": "Cable",
        }

    def _generate_data(self):
        """Generate FritzBox-format DOCSIS data with per-poll variation."""
        base = _load_base_data()
        data = copy.deepcopy(base)

        for ch in data["channelDs"]["docsis30"]:
            ch["powerLevel"] += random.uniform(-0.3, 0.3)
            ch["mse"] += random.uniform(-0.5, 0.5)
            # Errors slowly accumulate
            ch["corrErrors"] += random.randint(0, 5) * self._poll_count
            if random.random() < 0.02:
                ch["nonCorrErrors"] += random.randint(1, 3)

        for ch in data["channelDs"].get("docsis31", []):
            ch["powerLevel"] += random.uniform(-0.3, 0.3)
            ch["mer"] += random.uniform(-0.5, 0.5)
            ch["corrErrors"] += random.randint(0, 3) * self._poll_count
            if random.random() < 0.01:
                ch["nonCorrErrors"] += random.randint(1, 2)

        for ch in data["channelUs"]["docsis30"]:
            ch["powerLevel"] += random.uniform(-0.3, 0.3)

        for ch in data["channelUs"].get("docsis31", []):
            ch["powerLevel"] += random.uniform(-0.3, 0.3)

        return data

    def collect(self) -> CollectorResult:
        self._poll_count += 1

        # Update simulated uptime
        self._device_info["uptime_seconds"] = int(time.time()) % 8640000

        # Publish device/connection info on first poll
        if self._poll_count == 1:
            log.info("Demo mode: %s (%s)", self._device_info["model"], self._device_info["sw_version"])
            self._web.update_state(device_info=self._device_info)
            self._web.update_state(connection_info=self._connection_info)

        data = self._generate_data()
        analysis = self._analyzer(data)

        # MQTT publishing
        if self._mqtt_pub:
            if not self._discovery_published:
                self._mqtt_pub.publish_discovery(self._device_info)
                self._mqtt_pub.publish_channel_discovery(
                    analysis["ds_channels"], analysis["us_channels"], self._device_info
                )
                self._discovery_published = True
                time.sleep(1)
            self._mqtt_pub.publish_data(analysis)

        # Web state + persistent storage
        self._web.update_state(analysis=analysis)
        self._storage.save_snapshot(analysis)

        # Event detection
        events = self._event_detector.check(analysis)
        if events:
            self._storage.save_events(events)
            log.info("Demo: detected %d event(s)", len(events))

        return CollectorResult(source=self.name, data=analysis)
