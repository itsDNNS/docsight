"""Collector for Connection Monitor - orchestrates probing, storage, and events."""

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.collectors.base import Collector, CollectorResult
from app.modules.connection_monitor.event_rules import ConnectionEventRules
from app.modules.connection_monitor.probe import ProbeEngine
from app.modules.connection_monitor.storage import ConnectionMonitorStorage
from app.modules.connection_monitor.traceroute_probe import TracerouteProbe
from app.modules.connection_monitor.traceroute_trigger import TracerouteTrigger

logger = logging.getLogger(__name__)

# Run retention cleanup every 15 minutes, not every collect cycle
_CLEANUP_INTERVAL_S = 900

# Probe interval bounds for the "connection_monitor_poll_interval_ms" setting
_DEFAULT_PROBE_INTERVAL_MS = 5000
_MIN_PROBE_INTERVAL_MS = 1000
_MAX_PROBE_INTERVAL_MS = 300_000

# The 1 s collector loop can wake slightly early; do not skip a due probe for that
_DUE_TOLERANCE_S = 0.05


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
        self._traceroute_probe = TracerouteProbe()
        self._last_probe: dict[int, float] = {}
        self._last_cleanup = 0.0
        self._event_rules = ConnectionEventRules(
            outage_threshold=int(config_mgr.get("connection_monitor_outage_threshold", 5)),
            loss_warning_pct=float(config_mgr.get("connection_monitor_loss_warning_pct", 2.0)),
        )

        data_dir = os.environ.get("DATA_DIR", "/data")
        db_path = os.path.join(data_dir, "connection_monitor.db")
        self._cm_storage = ConnectionMonitorStorage(db_path)
        self._traceroute_trigger = TracerouteTrigger(
            probe=self._traceroute_probe,
            storage=self._cm_storage,
        )

        self._seeded = False
        self._smart_capture = None

    def set_smart_capture(self, smart_capture):
        """Inject Smart Capture engine for event evaluation."""
        self._smart_capture = smart_capture

    def is_enabled(self) -> bool:
        return bool(self._config_mgr.get("connection_monitor_enabled", False))

    def should_poll(self) -> bool:
        """Always return True - per-target timing is managed internally."""
        return True

    def collect(self) -> CollectorResult:
        try:
            self._ensure_default_targets()
            interval_ms = self._configured_interval_ms()
            all_targets = self._cm_storage.get_targets()
            self._sync_target_intervals(all_targets, interval_ms)
            targets = [t for t in all_targets if t["enabled"]]
            if not targets:
                return CollectorResult(source=self.name)

            # Determine which targets are due
            now = time.time()
            due = []
            for t in targets:
                interval_s = interval_ms / 1000.0
                last = self._last_probe.get(t["id"], 0)
                if now - last >= interval_s - _DUE_TOLERANCE_S:
                    due.append(t)

            if not due:
                return CollectorResult(source=self.name)

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
                self._cm_storage.cleanup_traces(retention)
                self._last_cleanup = now

            return CollectorResult(source=self.name, data={"probed": len(due)})
        except Exception as exc:
            logger.exception("Connection Monitor collect error")
            return CollectorResult(source=self.name, success=False, error=str(exc))

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

        for event in all_events:
            self._traceroute_trigger.on_event(event)

        if all_events and hasattr(self._core_storage, "save_events_with_ids"):
            self._core_storage.save_events_with_ids(all_events)
            if self._smart_capture:
                self._smart_capture.evaluate(all_events)

    def _configured_interval_ms(self) -> int:
        """Probe interval from settings, bounded; unreadable values use the default."""
        try:
            # ConfigManager.get() itself casts INT keys and raises for values
            # such as "1500.5" that the settings form can still save.
            interval_ms = int(self._config_mgr.get(
                "connection_monitor_poll_interval_ms", _DEFAULT_PROBE_INTERVAL_MS
            ))
        except (TypeError, ValueError, OverflowError):
            return _DEFAULT_PROBE_INTERVAL_MS
        return min(max(interval_ms, _MIN_PROBE_INTERVAL_MS), _MAX_PROBE_INTERVAL_MS)

    def _sync_target_intervals(self, targets: list[dict], interval_ms: int):
        """Keep stored per-target intervals equal to the configured interval.

        Consumers such as the correlation view read a target's
        poll_interval_ms to know how long one raw sample covers.
        """
        for t in targets:
            if t["poll_interval_ms"] != interval_ms:
                self._cm_storage.update_target(t["id"], poll_interval_ms=interval_ms)
                t["poll_interval_ms"] = interval_ms

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

    def stop(self):
        """Shutdown background resources."""
        self._traceroute_trigger.shutdown()
