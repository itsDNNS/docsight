"""Collector for Connection Monitor - orchestrates probing, storage, and events."""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.collectors.base import Collector, CollectorResult
from app.modules.connection_monitor.event_rules import ConnectionEventRules
from app.modules.connection_monitor.probe import ProbeEngine
from app.modules.connection_monitor.storage import ConnectionMonitorStorage

logger = logging.getLogger(__name__)

# Run retention cleanup every 15 minutes, not every collect cycle
_CLEANUP_INTERVAL_S = 900


class ConnectionMonitorCollector(Collector):
    """Always-on latency collector with per-target timing."""

    name = "connection_monitor"

    def __init__(self, config_mgr, storage, web, **kwargs):
        super().__init__(poll_interval_seconds=1)
        self._config_mgr = config_mgr
        self._core_storage = storage
        self._web = web

        method = config_mgr.get("connection_monitor_probe_method", "auto")
        self._probe = ProbeEngine(method=method)
        self._last_probe: dict[int, float] = {}
        self._last_cleanup = 0.0
        self._event_rules = ConnectionEventRules(
            outage_threshold=int(config_mgr.get("connection_monitor_outage_threshold", 5)),
            loss_warning_pct=float(config_mgr.get("connection_monitor_loss_warning_pct", 2.0)),
        )

        data_dir = os.environ.get("DATA_DIR", "/data")
        db_path = os.path.join(data_dir, "connection_monitor.db")
        self._cm_storage = ConnectionMonitorStorage(db_path)

        self._seeded = False

    def is_enabled(self) -> bool:
        return bool(self._config_mgr.get("connection_monitor_enabled", False))

    def should_poll(self) -> bool:
        """Always return True - per-target timing is managed internally."""
        return True

    def collect(self) -> CollectorResult:
        try:
            self._ensure_default_targets()
            targets = [
                t for t in self._cm_storage.get_targets() if t["enabled"]
            ]
            if not targets:
                return CollectorResult.ok(self.name, None)

            # Determine which targets are due
            now = time.time()
            due = []
            for t in targets:
                interval_s = t["poll_interval_ms"] / 1000.0
                last = self._last_probe.get(t["id"], 0)
                if now - last >= interval_s:
                    due.append(t)

            if not due:
                return CollectorResult.ok(self.name, None)

            # Probe all due targets in parallel
            samples = self._probe_targets(due, now)

            # Save samples
            if samples:
                self._cm_storage.save_samples(samples)

            # Check events
            self._check_events(samples)

            # Periodic aggregation + retention cleanup
            if now - self._last_cleanup >= _CLEANUP_INTERVAL_S:
                self._cm_storage.aggregate()
                retention = int(
                    self._config_mgr.get("connection_monitor_retention_days", 0)
                )
                self._cm_storage.cleanup(retention)
                self._last_cleanup = now

            return CollectorResult.ok(self.name, {"probed": len(due)})
        except Exception as exc:
            logger.exception("Connection Monitor collect error")
            return CollectorResult.failure(self.name, str(exc))

    def _probe_targets(self, targets: list[dict], now: float) -> list[dict]:
        """Probe targets in parallel and return sample dicts."""
        samples = []
        tcp_port = int(self._config_mgr.get("connection_monitor_tcp_port", 443))

        with ThreadPoolExecutor(
            max_workers=max(len(targets), 1),
            thread_name_prefix="cm-probe",
        ) as pool:
            futures = {
                pool.submit(self._probe.probe, t["host"], t.get("tcp_port", tcp_port)): t
                for t in targets
            }
            for future in as_completed(futures, timeout=5):
                target = futures[future]
                try:
                    result = future.result()
                except Exception:
                    result = type("R", (), {"latency_ms": None, "timeout": True, "method": "error"})()

                self._last_probe[target["id"]] = now
                samples.append({
                    "target_id": target["id"],
                    "timestamp": now,
                    "latency_ms": result.latency_ms,
                    "timeout": result.timeout,
                    "probe_method": result.method,
                })
        return samples

    def _check_events(self, samples: list[dict]):
        """Run event rules and save any emitted events."""
        all_events = []
        for s in samples:
            events = self._event_rules.check_probe_result(
                target_id=s["target_id"], timeout=s["timeout"]
            )
            all_events.extend(events)

        # Check windowed packet loss stats per probed target
        window_seconds = 60
        checked_targets = set()
        for s in samples:
            tid = s["target_id"]
            if tid in checked_targets:
                continue
            checked_targets.add(tid)
            summary = self._cm_storage.get_summary(tid, window_seconds=window_seconds)
            loss_pct = summary.get("packet_loss_pct") or 0.0
            events = self._event_rules.check_window_stats(
                target_id=tid, packet_loss_pct=loss_pct, window_seconds=window_seconds,
            )
            all_events.extend(events)

        if all_events and hasattr(self._core_storage, "save_events"):
            self._core_storage.save_events(all_events)

    def _ensure_default_targets(self):
        """Seed default targets on first enable."""
        if self._seeded:
            return
        self._seeded = True
        if not self._cm_storage.get_targets():
            self._cm_storage.create_target("Cloudflare DNS", "1.1.1.1")
            self._cm_storage.create_target("Google DNS", "8.8.8.8")
            logger.info("Connection Monitor: seeded default targets")

    def get_storage(self) -> ConnectionMonitorStorage:
        """Expose storage for routes."""
        return self._cm_storage

    def get_probe(self) -> ProbeEngine:
        """Expose probe engine for capability endpoint."""
        return self._probe
