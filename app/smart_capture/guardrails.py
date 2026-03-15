"""Smart Capture guardrails — rate limiting and flapping protection."""

import logging
import threading
import time

log = logging.getLogger("docsis.smart_capture.guardrails")


class GuardrailChain:
    """Applies guardrails in order: flapping, global cooldown, per-trigger
    cooldown, max actions per hour.

    Thread-safe — all state access is protected by a lock.

    Cooldown semantics: 0 = disabled (no cooldown, always allow).
    This differs from NotificationDispatcher where 0 = never send.

    Global cooldown is batch-aware: it is checked once per source event
    (not per trigger), and updated only after all triggers for that event
    have been evaluated. This prevents a second trigger for the same event
    from being suppressed by the first trigger's fire.
    """

    def __init__(self, config_mgr):
        self._config = config_mgr
        self._lock = threading.Lock()
        self._last_global_fire: float = 0.0
        self._last_trigger_fire: dict[str, float] = {}
        self._hourly_fires: list[float] = []
        self._trigger_match_history: dict[str, list[float]] = {}

    def check_batch(self, trigger_results):
        """Evaluate guardrails for a batch of (trigger, event) pairs from one source event.

        Args:
            trigger_results: list of (trigger, event) tuples that matched.

        Returns:
            list of (trigger, event, allowed, reason) tuples.

        Global cooldown is checked once against the batch. Per-trigger
        cooldown and hourly limit are checked per trigger. Flapping counts
        all matches (not just allowed ones) to detect chattering input.
        """
        if not trigger_results:
            return []

        results = []
        with self._lock:
            now = time.monotonic()

            # 1. Global cooldown — checked once for the whole batch
            global_cd = int(self._config.get("sc_global_cooldown", 300))
            global_blocked = (
                global_cd > 0
                and (now - self._last_global_fire) < global_cd
            )
            global_reason = None
            if global_blocked:
                remaining = int(global_cd - (now - self._last_global_fire))
                global_reason = f"global_cooldown: {remaining}s remaining"

            any_allowed = False
            for trigger, event in trigger_results:
                trigger_key = f"{trigger.event_type}:{trigger.action_type}"

                # Record match for flapping (counts ALL matches, not just fires)
                history = self._trigger_match_history.get(trigger_key, [])
                window = int(self._config.get("sc_flapping_window", 3600))
                history = [t for t in history if (now - t) < window]
                history.append(now)
                self._trigger_match_history[trigger_key] = history

                # 2. Flapping — checked before cooldowns
                threshold = int(self._config.get("sc_flapping_threshold", 3))
                if threshold > 0 and len(history) > threshold:
                    results.append((trigger, event, False,
                                    f"flapping: {len(history)} matches in {window}s for {trigger_key}"))
                    continue

                # 3. Global cooldown
                if global_blocked:
                    results.append((trigger, event, False, global_reason))
                    continue

                # 4. Per-trigger cooldown
                trigger_cd = int(self._config.get("sc_trigger_cooldown", 900))
                last_fire = self._last_trigger_fire.get(trigger_key, 0.0)
                if trigger_cd > 0 and (now - last_fire) < trigger_cd:
                    remaining = int(trigger_cd - (now - last_fire))
                    results.append((trigger, event, False,
                                    f"trigger_cooldown: {remaining}s remaining for {trigger_key}"))
                    continue

                # 5. Max actions per hour
                max_per_hour = int(self._config.get("sc_max_actions_per_hour", 4))
                cutoff = now - 3600
                self._hourly_fires = [t for t in self._hourly_fires if t > cutoff]
                if max_per_hour > 0 and len(self._hourly_fires) >= max_per_hour:
                    results.append((trigger, event, False,
                                    f"max_actions_per_hour: {len(self._hourly_fires)}/{max_per_hour} used"))
                    continue

                # All passed
                self._last_trigger_fire[trigger_key] = now
                self._hourly_fires.append(now)
                any_allowed = True
                results.append((trigger, event, True, None))

            # Update global cooldown only if at least one execution was allowed
            if any_allowed:
                self._last_global_fire = now

        return results
