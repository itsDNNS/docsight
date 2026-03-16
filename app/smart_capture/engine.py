"""Smart Capture execution engine — evaluates events, applies guardrails, records executions."""

import logging

from .guardrails import GuardrailChain
from .types import ExecutionStatus, Trigger

log = logging.getLogger("docsis.smart_capture.engine")


class SmartCaptureEngine:
    """Core Smart Capture engine.

    Sits alongside the NotificationDispatcher as an event consumer.
    Modules register triggers; the engine evaluates incoming events against
    them, applies guardrails, and writes execution records to storage.
    Registered adapters are called to execute actions for pending executions.
    """

    def __init__(self, storage, config_mgr):
        self._storage = storage
        self._config = config_mgr
        self._guardrails = GuardrailChain(config_mgr)
        self._triggers: list[Trigger] = []
        self._adapters: dict[str, object] = {}

    @property
    def triggers(self) -> list[Trigger]:
        return list(self._triggers)

    @property
    def adapter_action_types(self) -> list[str]:
        """Return list of action types with registered adapters."""
        return list(self._adapters.keys())

    def register_trigger(self, trigger: Trigger):
        """Register a trigger. Duplicates (same event_type + action_type) are ignored."""
        if trigger not in self._triggers:
            self._triggers.append(trigger)
            log.info("Registered trigger: %s -> %s", trigger.event_type, trigger.action_type)

    def register_adapter(self, action_type: str, adapter):
        """Register an action adapter for an action type."""
        self._adapters[action_type] = adapter
        log.info("Registered adapter for action_type=%s", action_type)

    def evaluate(self, events: list[dict]):
        """Evaluate a batch of events against registered triggers.

        For each event, collect matching triggers, then pass them through
        check_batch() for batch-aware guardrail evaluation.
        Called from the modem collector after event detection.
        """
        if not self._is_enabled():
            return
        if not events or not self._triggers:
            return

        for event in events:
            self._evaluate_event(event)

    def _is_enabled(self) -> bool:
        val = self._config.get("sc_enabled", False)
        if isinstance(val, str):
            return val.lower() in ("true", "1", "yes", "on")
        return bool(val)

    def _evaluate_event(self, event: dict):
        matches = [(t, event) for t in self._triggers if t.matches(event)]
        if not matches:
            return

        # Filter by per-trigger config key (sc_trigger_* must be True)
        matches = [
            (t, ev) for t, ev in matches
            if t.config_key is None or self._config.get(t.config_key, False)
        ]
        if not matches:
            return

        # Apply sub-filter if set
        matches = [
            (t, ev) for t, ev in matches
            if t.sub_filter is None or t.sub_filter(self._config, ev)
        ]
        if not matches:
            return

        results = self._guardrails.check_batch(matches)

        for trigger, ev, allowed, reason in results:
            if allowed:
                execution_id = self._storage.save_execution(
                    trigger_type=ev["event_type"],
                    action_type=trigger.action_type,
                    status=ExecutionStatus.PENDING,
                    trigger_event_id=ev.get("_id"),
                    trigger_timestamp=ev.get("timestamp"),
                    details=ev.get("details"),
                )
                log.info("Smart Capture: pending execution #%d for %s -> %s",
                         execution_id, ev["event_type"], trigger.action_type)

                adapter = self._adapters.get(trigger.action_type)
                if adapter:
                    try:
                        adapter.execute(execution_id, ev)
                    except Exception as e:
                        log.error("Smart Capture: adapter error for #%d: %s",
                                  execution_id, e)
            else:
                self._storage.save_execution(
                    trigger_type=ev["event_type"],
                    action_type=trigger.action_type,
                    status=ExecutionStatus.SUPPRESSED,
                    trigger_event_id=ev.get("_id"),
                    trigger_timestamp=ev.get("timestamp"),
                    suppression_reason=reason,
                    details=ev.get("details"),
                )
                log.info("Smart Capture: suppressed %s -> %s (%s)",
                         ev["event_type"], trigger.action_type, reason)
