"""Replay #1106 through the real Connection Monitor collector and event rules."""

import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

XSS_LABEL = "<img src=x onerror=window.__docsightXss=1> $& $1 {count}"

# Two hours before the replay, as the events looked before #1106: only the target ID.
LEGACY_EVENTS = [
    ("warning", "cm_packet_loss_warning", "Target 1: 4.5% packet loss over 60s",
     {"target_id": 1, "packet_loss_pct": 4.5, "window_seconds": 60}),
    ("critical", "cm_target_unreachable", "Target 1 unreachable (5 consecutive timeouts)",
     {"target_id": 1, "consecutive_timeouts": 5}),
    ("info", "cm_target_recovered", "Target 1 recovered after 5 timeouts",
     {"target_id": 1, "was_down_for": 5}),
]


def seed_connection_monitor_events(runtime):
    """Create two targets, delete the first, add more, then probe them all.

    Every target times out five times and then answers again, so the real
    rules emit packet loss, unreachable and recovered events. Afterwards one
    target is renamed and another deleted; their events keep the old names.
    """
    from app.modules.connection_monitor.collector import ConnectionMonitorCollector
    from app.modules.connection_monitor.probe import ProbeResult

    storage = runtime.storage
    legacy_time = datetime.now(timezone.utc) - timedelta(hours=2)
    storage.save_events([
        {"timestamp": (legacy_time + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ"),
         "severity": severity, "event_type": event_type, "message": message, "details": details}
        for i, (severity, event_type, message, details) in enumerate(LEGACY_EVENTS)
    ])

    with patch("app.modules.connection_monitor.collector.ProbeEngine"), \
            patch("app.modules.connection_monitor.collector.TracerouteProbe"):
        collector = ConnectionMonitorCollector(
            config_mgr=runtime.config_manager, storage=storage, web=runtime
        )
    # Outages trigger a traceroute; the replay records none.
    collector._traceroute_probe.run.return_value = SimpleNamespace(hops=[])
    try:
        cm = collector.get_storage()
        first = cm.create_target("First", "192.0.2.1")
        second = cm.create_target("Second", "192.0.2.2")
        cm.delete_target(first)
        third = cm.create_target("Third", "192.0.2.3")
        cm.create_target(XSS_LABEL, "lab.example")
        collector._seeded = True
        collector._last_cleanup = time.time()

        for timeout in (True,) * 5 + (False,):
            collector._probe.probe.return_value = ProbeResult(
                latency_ms=None if timeout else 12.0, timeout=timeout, method="tcp"
            )
            collector._last_probe = {}
            collector.collect()

        cm.update_target(third, label="Renamed", host="198.51.100.3")
        cm.delete_target(second)
    finally:
        collector.stop()
