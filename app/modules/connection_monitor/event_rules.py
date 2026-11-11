"""Event detection rules for Connection Monitor."""

import time
from app.tz import utc_now


# Cooldown prevents duplicate packet loss warnings within this window
LOSS_COOLDOWN_S = 300


def _target_identity(target_id: int, label: str | None, host: str | None) -> tuple[str, dict]:
    """Return the target's display name and the identity an event stores.

    Target IDs are stable keys that are never reused, so they do not count
    the targets. Events keep the label and address from the time they
    happened; renaming or deleting the target later does not change them.
    """
    label = (label or "").strip()
    host = (host or "").strip()
    if label and host and label != host:
        name = f"{label} ({host})"
    else:
        name = label or host or f"ID {target_id}"
    return name, {"target_id": target_id, "target_label": label, "target_host": host}


class ConnectionEventRules:
    """Tracks per-target state and emits events for outages, recovery, packet loss."""

    def __init__(self, outage_threshold: int = 5, loss_warning_pct: float = 2.0):
        self._outage_threshold = outage_threshold
        self._loss_warning_pct = loss_warning_pct
        # Per-target state: {target_id: {"consecutive_timeouts": int, "in_outage": bool}}
        self._target_state: dict[int, dict] = {}
        # Per-target loss cooldown: {target_id: last_warning_ts}
        self._loss_cooldown: dict[int, float] = {}

    def _get_state(self, target_id: int) -> dict[str, object]:
        if target_id not in self._target_state:
            self._target_state[target_id] = {
                "consecutive_timeouts": 0,
                "in_outage": False,
            }
        return self._target_state[target_id]

    def check_probe_result(
        self, target_id: int, timeout: bool,
        target_label: str | None = None, target_host: str | None = None,
    ) -> list[dict]:
        """Check a single probe result and return any events to emit."""
        state = self._get_state(target_id)
        name, identity = _target_identity(target_id, target_label, target_host)
        events = []

        if timeout:
            state["consecutive_timeouts"] += 1
            if (
                state["consecutive_timeouts"] >= self._outage_threshold
                and not state["in_outage"]
            ):
                state["in_outage"] = True
                events.append({
                    "timestamp": utc_now(),
                    "severity": "critical",
                    "event_type": "cm_target_unreachable",
                    "message": f"Target {name} unreachable ({state['consecutive_timeouts']} consecutive timeouts)",
                    "details": {**identity, "consecutive_timeouts": state["consecutive_timeouts"]},
                })
        else:
            if state["in_outage"]:
                events.append({
                    "timestamp": utc_now(),
                    "severity": "info",
                    "event_type": "cm_target_recovered",
                    "message": f"Target {name} recovered after {state['consecutive_timeouts']} timeouts",
                    "details": {**identity, "was_down_for": state["consecutive_timeouts"]},
                })
            state["consecutive_timeouts"] = 0
            state["in_outage"] = False

        return events

    def check_window_stats(
        self, target_id: int, packet_loss_pct: float, window_seconds: int,
        target_label: str | None = None, target_host: str | None = None,
    ) -> list[dict]:
        """Check aggregated window stats and return any events."""
        events = []
        now = time.time()

        if packet_loss_pct >= self._loss_warning_pct:
            last_warning = self._loss_cooldown.get(target_id, 0)
            if now - last_warning >= LOSS_COOLDOWN_S:
                self._loss_cooldown[target_id] = now
                name, identity = _target_identity(target_id, target_label, target_host)
                events.append({
                    "timestamp": utc_now(),
                    "severity": "warning",
                    "event_type": "cm_packet_loss_warning",
                    "message": f"Target {name}: {packet_loss_pct:.1f}% packet loss over {window_seconds}s",
                    "details": {
                        **identity,
                        "packet_loss_pct": packet_loss_pct,
                        "window_seconds": window_seconds,
                    },
                })
        return events
