"""Demo collector — generates realistic DOCSIS data for testing without a real modem."""

import copy
import json
import logging
import os
import random
import time
from datetime import datetime, timedelta

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
            ch["powerLevel"] = round(ch["powerLevel"] + random.uniform(-0.3, 0.3), 1)
            ch["mse"] = round(ch["mse"] + random.uniform(-0.5, 0.5), 1)
            # Errors slowly accumulate
            ch["corrErrors"] += random.randint(0, 5) * self._poll_count
            if random.random() < 0.02:
                ch["nonCorrErrors"] += random.randint(1, 3)

        for ch in data["channelDs"].get("docsis31", []):
            ch["powerLevel"] = round(ch["powerLevel"] + random.uniform(-0.3, 0.3), 1)
            ch["mer"] = round(ch["mer"] + random.uniform(-0.5, 0.5), 1)
            ch["corrErrors"] += random.randint(0, 3) * self._poll_count
            if random.random() < 0.01:
                ch["nonCorrErrors"] += random.randint(1, 2)

        for ch in data["channelUs"]["docsis30"]:
            ch["powerLevel"] = round(ch["powerLevel"] + random.uniform(-0.3, 0.3), 1)

        for ch in data["channelUs"].get("docsis31", []):
            ch["powerLevel"] = round(ch["powerLevel"] + random.uniform(-0.3, 0.3), 1)

        return data

    def collect(self) -> CollectorResult:
        self._poll_count += 1

        # Update simulated uptime
        self._device_info["uptime_seconds"] = int(time.time()) % 8640000

        # First poll: publish device/connection info + seed demo history
        if self._poll_count == 1:
            log.info("Demo mode: %s (%s)", self._device_info["model"], self._device_info["sw_version"])
            self._web.update_state(device_info=self._device_info)
            self._web.update_state(connection_info=self._connection_info)
            self._seed_demo_data()

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

    def _seed_demo_data(self):
        """Populate storage with sample events and journal entries on first run."""
        now = datetime.now()

        # ── Sample events (spread over the last 48h) ──
        demo_events = [
            {
                "timestamp": (now - timedelta(hours=47)).strftime("%Y-%m-%dT%H:%M:%S"),
                "severity": "info",
                "event_type": "monitoring_started",
                "message": "Monitoring started (Health: good)",
                "details": {"health": "good"},
            },
            {
                "timestamp": (now - timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%S"),
                "severity": "warning",
                "event_type": "power_change",
                "message": "DS power avg shifted from 4.5 to 6.8 dBmV",
                "details": {"direction": "downstream", "prev": 4.5, "current": 6.8},
            },
            {
                "timestamp": (now - timedelta(hours=36)).strftime("%Y-%m-%dT%H:%M:%S"),
                "severity": "warning",
                "event_type": "health_change",
                "message": "Health changed from good to marginal",
                "details": {"prev": "good", "current": "marginal"},
            },
            {
                "timestamp": (now - timedelta(hours=34)).strftime("%Y-%m-%dT%H:%M:%S"),
                "severity": "warning",
                "event_type": "error_spike",
                "message": "Uncorrectable errors jumped by 847 (from 12 to 859)",
                "details": {"prev": 12, "current": 859, "delta": 847},
            },
            {
                "timestamp": (now - timedelta(hours=30)).strftime("%Y-%m-%dT%H:%M:%S"),
                "severity": "info",
                "event_type": "health_change",
                "message": "Health recovered from marginal to good",
                "details": {"prev": "marginal", "current": "good"},
            },
            {
                "timestamp": (now - timedelta(hours=18)).strftime("%Y-%m-%dT%H:%M:%S"),
                "severity": "warning",
                "event_type": "snr_change",
                "message": "DS SNR min dropped to 33.2 dB (warning threshold: 33)",
                "details": {"prev": 36.5, "current": 33.2, "threshold": "warning"},
            },
            {
                "timestamp": (now - timedelta(hours=12)).strftime("%Y-%m-%dT%H:%M:%S"),
                "severity": "info",
                "event_type": "channel_change",
                "message": "DS channel count changed from 25 to 24",
                "details": {"direction": "downstream", "prev": 25, "current": 24},
            },
            {
                "timestamp": (now - timedelta(hours=8)).strftime("%Y-%m-%dT%H:%M:%S"),
                "severity": "info",
                "event_type": "channel_change",
                "message": "DS channel count changed from 24 to 25",
                "details": {"direction": "downstream", "prev": 24, "current": 25},
            },
            {
                "timestamp": (now - timedelta(hours=3)).strftime("%Y-%m-%dT%H:%M:%S"),
                "severity": "warning",
                "event_type": "power_change",
                "message": "US power avg shifted from 44.8 to 46.3 dBmV",
                "details": {"direction": "upstream", "prev": 44.8, "current": 46.3},
            },
        ]
        self._storage.save_events(demo_events)

        # ── Sample journal entries ──
        yesterday = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        three_days_ago = (now - timedelta(days=3)).strftime("%Y-%m-%d")
        week_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")

        incidents = [
            (
                week_ago,
                "Intermittent packet loss during peak hours",
                "Noticed buffering on video calls between 8-10 PM.\n"
                "Downstream SNR dropped below 34 dB on channels 19-24.\n"
                "Resolved after ISP maintenance window overnight.",
            ),
            (
                three_days_ago,
                "Uncorrectable error spike after firmware update",
                "Router rebooted for firmware update at 03:00 AM.\n"
                "Uncorrectable errors spiked to ~850 across multiple DS channels.\n"
                "Errors stabilized after ~4 hours. Monitoring for recurrence.",
            ),
            (
                yesterday,
                "Brief upstream power fluctuation",
                "US power jumped from 44.8 to 46.3 dBmV for about 2 hours.\n"
                "Possibly related to temperature changes in the building.\n"
                "No impact on speeds observed.",
            ),
        ]
        for date, title, description in incidents:
            self._storage.save_incident(date, title, description)

        log.info("Demo: seeded %d events and %d journal entries", len(demo_events), len(incidents))
