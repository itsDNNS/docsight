"""Demo collector — generates realistic DOCSIS data for testing without a real modem."""

import copy
import json
import logging
import math
import os
import random
import sqlite3
import struct
import time
import zlib
from datetime import datetime, timedelta

from .base import Collector, CollectorResult
from ..gaming_index import compute_gaming_index

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

    def __init__(self, analyzer_fn, event_detector, storage, mqtt_pub, web, poll_interval, notifier=None):
        super().__init__(poll_interval)
        self._analyzer = analyzer_fn
        self._event_detector = event_detector
        self._storage = storage
        self._mqtt_pub = mqtt_pub
        self._web = web
        self._notifier = notifier
        self._discovery_published = False
        self._poll_count = 0
        self._device_info = {
            "manufacturer": "DOCSight",
            "model": "Demo Router",
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
            speedtest = self._web._state.get("speedtest_latest")
            gi = compute_gaming_index(analysis, speedtest)
            self._mqtt_pub.publish_data(analysis, gaming_index=gi)

        # Web state + persistent storage
        self._web.update_state(analysis=analysis)
        self._storage.save_snapshot(analysis)

        # Event detection
        events = self._event_detector.check(analysis)
        if events:
            self._storage.save_events(events)
            log.info("Demo: detected %d event(s)", len(events))
            if self._notifier:
                self._notifier.dispatch(events)

        return CollectorResult(source=self.name, data=analysis)

    def _seed_demo_data(self):
        """Populate storage with 9 months of snapshots, events, journal, speedtest, and BQM."""
        # Purge any existing demo data first (handles container rebuilds with persisted volume)
        self._storage.purge_demo_data()
        # Keep all demo data — don't let cleanup purge the seeded history
        self._storage.max_days = 0
        now = datetime.now()
        self._seed_history(now)
        self._seed_events(now)
        self._seed_journal_entries(now)
        self._seed_speedtest_results(now)
        self._seed_bqm_graphs(now)
        self._seed_incident_containers(now)

    def _seed_history(self, now):
        """Generate 9 months of historical snapshots (every 15 min)."""
        days = 270
        interval_min = 15
        total = days * 24 * 60 // interval_min  # 8640 snapshots
        start = now - timedelta(days=days)

        rows = []
        for i in range(total):
            ts = start + timedelta(minutes=i * interval_min)
            ts_str = ts.strftime("%Y-%m-%dT%H:%M:%S")

            # Time-based patterns for realistic variation
            hour = ts.hour + ts.minute / 60.0
            day_of_year = ts.timetuple().tm_yday

            # Diurnal cycle: power drifts slightly during the day
            diurnal = math.sin((hour - 6) * math.pi / 12) * 0.5

            # Slow seasonal drift over weeks
            seasonal = math.sin(day_of_year * math.pi / 45) * 0.3

            # Occasional "bad periods" (every ~10 days, lasting ~6h)
            bad_period = (day_of_year % 10 == 0 and 2 <= hour <= 8)

            analysis = self._generate_historical_analysis(
                i, diurnal, seasonal, bad_period
            )
            rows.append((
                ts_str,
                json.dumps(analysis["summary"]),
                json.dumps(analysis["ds_channels"]),
                json.dumps(analysis["us_channels"]),
                1,  # is_demo
            ))

        # Bulk insert for speed
        with sqlite3.connect(self._storage.db_path) as conn:
            conn.executemany(
                "INSERT INTO snapshots (timestamp, summary_json, ds_channels_json, us_channels_json, is_demo) "
                "VALUES (?, ?, ?, ?, ?)",
                rows,
            )
        log.info("Demo: seeded %d historical snapshots (%d days)", len(rows), days)

    def _generate_historical_analysis(self, index, diurnal, seasonal, bad_period):
        """Generate a single analyzed snapshot for historical seeding."""
        base = _load_base_data()

        # Build DS channels
        ds_channels = []
        total_power = 0
        total_snr = 0
        total_corr = 0
        total_uncorr = 0

        for ch in base["channelDs"]["docsis30"]:
            power = round(ch["powerLevel"] + diurnal + seasonal + random.uniform(-0.3, 0.3), 1)
            snr = round(-ch["mse"] + diurnal * 0.3 + random.uniform(-0.5, 0.5), 1)
            if bad_period:
                power += random.uniform(1.5, 3.0)
                snr -= random.uniform(2.0, 5.0)
            corr = int(ch["corrErrors"] + index * random.randint(0, 3))
            uncorr = int(random.randint(0, 2) if bad_period else 0)
            total_power += power
            total_snr += snr
            total_corr += corr
            total_uncorr += uncorr
            ds_channels.append({
                "channel_id": ch["channelID"],
                "frequency": ch["frequency"],
                "power": power,
                "modulation": ch["modulation"],
                "snr": round(snr, 1),
                "correctable_errors": corr,
                "uncorrectable_errors": uncorr,
                "docsis_version": "3.0",
                "health": "good",
                "health_detail": "",
            })

        for ch in base["channelDs"].get("docsis31", []):
            power = round(ch["powerLevel"] + diurnal + seasonal + random.uniform(-0.3, 0.3), 1)
            snr = round(ch["mer"] + diurnal * 0.3 + random.uniform(-0.5, 0.5), 1)
            if bad_period:
                power += random.uniform(1.0, 2.0)
                snr -= random.uniform(1.5, 3.0)
            corr = int(ch["corrErrors"] + index * random.randint(0, 2))
            uncorr = int(random.randint(0, 1) if bad_period else 0)
            total_power += power
            total_snr += snr
            total_corr += corr
            total_uncorr += uncorr
            ds_channels.append({
                "channel_id": ch["channelID"],
                "frequency": ch["frequency"],
                "power": power,
                "modulation": ch["modulation"],
                "snr": round(snr, 1),
                "correctable_errors": corr,
                "uncorrectable_errors": uncorr,
                "docsis_version": "3.1",
                "health": "good",
                "health_detail": "",
            })

        # Build US channels
        us_channels = []
        us_total_power = 0
        for ch in base["channelUs"]["docsis30"]:
            power = round(ch["powerLevel"] + diurnal * 0.2 + random.uniform(-0.3, 0.3), 1)
            if bad_period:
                power += random.uniform(0.5, 1.5)
            us_total_power += power
            us_channels.append({
                "channel_id": ch["channelID"],
                "frequency": ch["frequency"],
                "power": power,
                "modulation": ch["modulation"],
                "multiplex": ch.get("multiplex", "SC-QAM"),
                "docsis_version": "3.0",
                "health": "good",
                "health_detail": "",
            })

        ds_count = len(ds_channels)
        us_count = len(us_channels)
        ds_powers = [ch["power"] for ch in ds_channels]
        ds_snrs = [ch["snr"] for ch in ds_channels]
        us_powers = [ch["power"] for ch in us_channels]

        health = "good"
        if bad_period:
            health = "marginal"

        return {
            "summary": {
                "ds_total": ds_count,
                "us_total": us_count,
                "ds_power_min": round(min(ds_powers), 1),
                "ds_power_max": round(max(ds_powers), 1),
                "ds_power_avg": round(total_power / ds_count, 1),
                "us_power_min": round(min(us_powers), 1),
                "us_power_max": round(max(us_powers), 1),
                "us_power_avg": round(us_total_power / us_count, 1),
                "ds_snr_min": round(min(ds_snrs), 1),
                "ds_snr_avg": round(total_snr / ds_count, 1),
                "ds_correctable_errors": total_corr,
                "ds_uncorrectable_errors": total_uncorr,
                "health": health,
                "health_issues": [],
            },
            "ds_channels": ds_channels,
            "us_channels": us_channels,
        }

    def _seed_events(self, now):
        """Seed realistic events spread over 9 months."""
        days = 270
        events = [
            {
                "timestamp": (now - timedelta(days=days - 1, hours=23)).strftime("%Y-%m-%dT%H:%M:%S"),
                "severity": "info",
                "event_type": "monitoring_started",
                "message": "Monitoring started (Health: good)",
                "details": {"health": "good"},
            },
        ]

        # Generate events at "bad period" boundaries (~every 10 days)
        for d in range(0, days, 10):
            t_start = now - timedelta(days=days - d, hours=-2)
            t_end = t_start + timedelta(hours=6)
            events.extend([
                {
                    "timestamp": t_start.strftime("%Y-%m-%dT%H:%M:%S"),
                    "severity": "warning",
                    "event_type": "health_change",
                    "message": "Health changed from good to marginal",
                    "details": {"prev": "good", "current": "marginal"},
                },
                {
                    "timestamp": (t_start + timedelta(minutes=15)).strftime("%Y-%m-%dT%H:%M:%S"),
                    "severity": "warning",
                    "event_type": "power_change",
                    "message": f"DS power avg shifted from 4.8 to {round(random.uniform(6.5, 8.0), 1)} dBmV",
                    "details": {"direction": "downstream", "prev": 4.8, "current": round(random.uniform(6.5, 8.0), 1)},
                },
                {
                    "timestamp": (t_start + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%S"),
                    "severity": "warning",
                    "event_type": "error_spike",
                    "message": f"Uncorrectable errors jumped by {random.randint(200, 1200)}",
                    "details": {"prev": 0, "current": random.randint(200, 1200)},
                },
                {
                    "timestamp": t_end.strftime("%Y-%m-%dT%H:%M:%S"),
                    "severity": "info",
                    "event_type": "health_change",
                    "message": "Health recovered from marginal to good",
                    "details": {"prev": "marginal", "current": "good"},
                },
            ])

        # SNR events scattered across 9 months
        for d in [250, 200, 150, 100, 75, 52, 33, 18, 5]:
            t = now - timedelta(days=d, hours=random.randint(8, 22))
            snr_val = round(random.uniform(32.0, 34.5), 1)
            events.append({
                "timestamp": t.strftime("%Y-%m-%dT%H:%M:%S"),
                "severity": "warning",
                "event_type": "snr_change",
                "message": f"DS SNR min dropped to {snr_val} dB (warning threshold: 33)",
                "details": {"prev": 37.0, "current": snr_val, "threshold": "warning"},
            })

        # Channel change events scattered across 9 months
        for d in [240, 180, 120, 60, 25, 3]:
            t = now - timedelta(days=d, hours=random.randint(0, 23))
            events.extend([
                {
                    "timestamp": t.strftime("%Y-%m-%dT%H:%M:%S"),
                    "severity": "info",
                    "event_type": "channel_change",
                    "message": "DS channel count changed from 25 to 24",
                    "details": {"direction": "downstream", "prev": 25, "current": 24},
                },
                {
                    "timestamp": (t + timedelta(hours=random.randint(2, 8))).strftime("%Y-%m-%dT%H:%M:%S"),
                    "severity": "info",
                    "event_type": "channel_change",
                    "message": "DS channel count changed from 24 to 25",
                    "details": {"direction": "downstream", "prev": 24, "current": 25},
                },
            ])

        self._storage.save_events(events, is_demo=True)
        log.info("Demo: seeded %d events", len(events))

    def _seed_journal_entries(self, now):
        """Seed journal entries spread over the 9-month demo period."""
        entries = [
            (
                (now - timedelta(days=265)).strftime("%Y-%m-%d"),
                "Initial setup and baseline measurement",
                "Installed DOCSight to monitor cable connection.\n"
                "Baseline: 25 DS channels (256QAM), 4 US channels (64QAM).\n"
                "All values within VFKD good-range. ISP: Vodafone Cable 250/40.",
            ),
            (
                (now - timedelta(days=240)).strftime("%Y-%m-%d"),
                "First month review — connection stable",
                "After 4 weeks of monitoring: signal levels consistently good.\n"
                "DS power avg 3-5 dBmV, SNR min >35 dB.\n"
                "No uncorrectable errors outside of periodic bad windows.",
            ),
            (
                (now - timedelta(days=210)).strftime("%Y-%m-%d"),
                "Intermittent packet loss during peak hours",
                "Noticed buffering on video calls between 8-10 PM.\n"
                "Downstream SNR dropped below 34 dB on channels 19-24.\n"
                "Resolved after ISP maintenance window overnight.",
            ),
            (
                (now - timedelta(days=180)).strftime("%Y-%m-%d"),
                "Seasonal signal drift observed",
                "Temperature increase seems to affect upstream power levels.\n"
                "US power drifted from 43 to 46 dBmV over the last 2 weeks.\n"
                "Still within tolerance, but monitoring closely.",
            ),
            (
                (now - timedelta(days=150)).strftime("%Y-%m-%d"),
                "ISP network upgrade — brief outage",
                "ISP announced DOCSIS 3.1 capacity upgrade in our area.\n"
                "Connection dropped for ~45 minutes during the window.\n"
                "Post-upgrade: slightly improved SNR values on OFDM channels.",
            ),
            (
                (now - timedelta(days=120)).strftime("%Y-%m-%d"),
                "Downstream channel temporarily dropped",
                "Channel 24 disappeared for ~6 hours.\n"
                "Came back on its own. Possibly ISP-side reconfiguration.\n"
                "No noticeable impact on speeds during the outage.",
            ),
            (
                (now - timedelta(days=90)).strftime("%Y-%m-%d"),
                "Recurring upstream noise — ISP notified",
                "Pattern of upstream noise during evening hours (7-11 PM).\n"
                "US power fluctuations of 2-3 dBmV. Packet loss on VoIP calls.\n"
                "Opened support ticket with ISP. Technician visit scheduled.",
            ),
            (
                (now - timedelta(days=75)).strftime("%Y-%m-%d"),
                "ISP technician visit — partial fix",
                "Technician replaced the building amplifier.\n"
                "Upstream noise reduced but not eliminated.\n"
                "ISP escalated to regional network team.",
            ),
            (
                (now - timedelta(days=50)).strftime("%Y-%m-%d"),
                "ISP maintenance — brief signal degradation",
                "Received ISP notification about planned maintenance.\n"
                "DS power spiked to 7-8 dBmV for about 4 hours.\n"
                "Uncorrectable errors increased during the window.\n"
                "Fully recovered by morning.",
            ),
            (
                (now - timedelta(days=30)).strftime("%Y-%m-%d"),
                "Speedtest results consistently below tariff",
                "Multiple speedtests showing 180-200 Mbps instead of booked 250.\n"
                "Correlated with elevated DS power levels during these times.\n"
                "Gathering evidence for potential BNetzA complaint.",
            ),
            (
                (now - timedelta(days=10)).strftime("%Y-%m-%d"),
                "Uncorrectable error spike after firmware update",
                "Router rebooted for firmware update at 03:00 AM.\n"
                "Uncorrectable errors spiked to ~850 across multiple DS channels.\n"
                "Errors stabilized after ~4 hours. Monitoring for recurrence.",
            ),
            (
                (now - timedelta(days=1)).strftime("%Y-%m-%d"),
                "Brief upstream power fluctuation",
                "US power jumped from 44.8 to 46.3 dBmV for about 2 hours.\n"
                "Possibly related to temperature changes in the building.\n"
                "No impact on speeds observed.",
            ),
        ]
        for date, title, description in entries:
            self._storage.save_entry(date, title, description, is_demo=True)
        log.info("Demo: seeded %d journal entries", len(entries))

    def _seed_incident_containers(self, now):
        """Seed demo incident containers and assign entries by date range."""
        inc1_id = self._storage.save_incident(
            name="Seasonal Signal Drift",
            description="Temperature-related upstream power drift observed over summer months. "
                        "Values stayed within tolerance but were monitored closely.",
            status="resolved",
            start_date=(now - timedelta(days=200)).strftime("%Y-%m-%d"),
            end_date=(now - timedelta(days=140)).strftime("%Y-%m-%d"),
            is_demo=True,
        )
        inc2_id = self._storage.save_incident(
            name="Upstream Noise Issue",
            description="Recurring upstream noise causing packet loss during peak hours. "
                        "ISP has been notified and is investigating. Technician visit partially fixed it.",
            status="open",
            start_date=(now - timedelta(days=90)).strftime("%Y-%m-%d"),
            end_date=None,
            is_demo=True,
        )
        inc3_id = self._storage.save_incident(
            name="Firmware Update Issues",
            description="Router firmware update caused temporary error spikes. "
                        "Resolved after stabilization period.",
            status="resolved",
            start_date=(now - timedelta(days=15)).strftime("%Y-%m-%d"),
            end_date=(now - timedelta(days=5)).strftime("%Y-%m-%d"),
            is_demo=True,
        )
        # Assign entries by date range
        count1 = self._storage.assign_entries_by_date_range(
            inc1_id,
            (now - timedelta(days=200)).strftime("%Y-%m-%d"),
            (now - timedelta(days=140)).strftime("%Y-%m-%d"),
        )
        count2 = self._storage.assign_entries_by_date_range(
            inc2_id,
            (now - timedelta(days=90)).strftime("%Y-%m-%d"),
            (now - timedelta(days=40)).strftime("%Y-%m-%d"),
        )
        count3 = self._storage.assign_entries_by_date_range(
            inc3_id,
            (now - timedelta(days=15)).strftime("%Y-%m-%d"),
            (now - timedelta(days=5)).strftime("%Y-%m-%d"),
        )
        log.info("Demo: seeded 3 incident containers (assigned %d + %d + %d entries)", count1, count2, count3)

    def _seed_speedtest_results(self, now):
        """Seed 9 months of speedtest results (~3 per day, correlated with bad periods)."""
        days = 270
        results = []
        result_id = 1

        for d in range(days):
            ts_day = now - timedelta(days=days - d)
            day_of_year = ts_day.timetuple().tm_yday
            bad_day = (day_of_year % 10 == 0)

            # 3 tests per day: morning, afternoon, evening
            for hour in [8, 14, 21]:
                ts = ts_day.replace(hour=hour, minute=random.randint(0, 59),
                                    second=random.randint(0, 59), microsecond=0)
                # Skip some tests randomly (~15%) for realism
                if random.random() < 0.15:
                    continue

                # Bad period: 2-8 AM on bad days
                is_bad = bad_day and 2 <= hour <= 8

                if is_bad:
                    dl = round(random.uniform(150, 200), 2)
                    ul = round(random.uniform(25, 35), 2)
                    ping = round(random.uniform(15, 35), 1)
                    jitter = round(random.uniform(3, 8), 1)
                    loss = round(random.uniform(0, 2), 1)
                else:
                    dl = round(random.uniform(220, 265), 2)
                    ul = round(random.uniform(36, 42), 2)
                    ping = round(random.uniform(8, 15), 1)
                    jitter = round(random.uniform(1, 4), 1)
                    loss = 0.0

                results.append({
                    "id": result_id,
                    "timestamp": ts.strftime("%Y-%m-%dT%H:%M:%S"),
                    "download_mbps": dl,
                    "upload_mbps": ul,
                    "download_human": f"{dl} Mbps",
                    "upload_human": f"{ul} Mbps",
                    "ping_ms": ping,
                    "jitter_ms": jitter,
                    "packet_loss_pct": loss,
                })
                result_id += 1

        # Bulk insert with is_demo=1 directly (save_speedtest_results doesn't support is_demo)
        if results:
            with sqlite3.connect(self._storage.db_path) as conn:
                conn.executemany(
                    "INSERT OR IGNORE INTO speedtest_results "
                    "(id, timestamp, download_mbps, upload_mbps, download_human, "
                    "upload_human, ping_ms, jitter_ms, packet_loss_pct, is_demo) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1)",
                    [
                        (r["id"], r["timestamp"], r["download_mbps"],
                         r["upload_mbps"], r["download_human"], r["upload_human"],
                         r["ping_ms"], r["jitter_ms"], r["packet_loss_pct"])
                        for r in results
                    ],
                )

        # Set latest result in web state for dashboard card
        if results:
            self._web.update_state(speedtest_latest=results[-1])

        log.info("Demo: seeded %d speedtest results (%d days)", len(results), days)

    def _seed_bqm_graphs(self, now):
        """Seed BQM placeholder graphs for the last 30 days."""
        for d in range(30):
            date = (now - timedelta(days=d)).strftime("%Y-%m-%d")
            ts = (now - timedelta(days=d)).strftime("%Y-%m-%dT%H:%M:%S")
            png = self._generate_bqm_png(seed=d)
            with sqlite3.connect(self._storage.db_path) as conn:
                conn.execute(
                    "INSERT OR IGNORE INTO bqm_graphs (date, timestamp, image_blob, is_demo) "
                    "VALUES (?, ?, ?, 1)",
                    (date, ts, png),
                )
        log.info("Demo: seeded 30 BQM graphs")

    @staticmethod
    def _generate_bqm_png(width=800, height=200, seed=0):
        """Generate a simple BQM-style quality graph as PNG bytes."""
        rng = random.Random(seed)

        def _png_chunk(chunk_type, data):
            c = chunk_type + data
            crc = struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)
            return struct.pack(">I", len(data)) + c + crc

        # Generate pixel data: quality bar chart with green/yellow/red bands
        raw = b""
        for y in range(height):
            row = b"\x00"  # PNG filter: None
            for x in range(width):
                # Simulate quality: mostly green, some yellow/red sections
                quality = 0.8 + 0.2 * math.sin(x * 0.02 + seed) + rng.uniform(-0.05, 0.05)
                quality = max(0, min(1, quality))

                # Quality bar: bottom portion filled, top portion background
                bar_height = int(quality * height * 0.8)
                if y > height - bar_height:
                    if quality > 0.7:
                        r, g, b = 46, 160, 67  # green
                    elif quality > 0.4:
                        r, g, b = 200, 170, 40  # yellow
                    else:
                        r, g, b = 200, 50, 50  # red
                    # Slight vertical gradient
                    fade = 0.7 + 0.3 * (height - y) / height
                    r, g, b = int(r * fade), int(g * fade), int(b * fade)
                else:
                    r, g, b = 30, 30, 40  # dark background
                row += bytes([r, g, b])
            raw += row

        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        idat = _png_chunk(b"IDAT", zlib.compress(raw, 6))
        iend = _png_chunk(b"IEND", b"")
        return sig + ihdr + idat + iend
