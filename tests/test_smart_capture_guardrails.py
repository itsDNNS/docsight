"""Tests for Smart Capture guardrails."""

import time
import pytest
from unittest.mock import MagicMock

from app.smart_capture.guardrails import GuardrailChain
from app.smart_capture.types import Trigger


def _make_config(**overrides):
    """Create a mock ConfigManager with sc_* defaults."""
    defaults = {
        "sc_global_cooldown": 300,
        "sc_trigger_cooldown": 900,
        "sc_max_actions_per_hour": 4,
        "sc_flapping_window": 3600,
        "sc_flapping_threshold": 3,
    }
    defaults.update(overrides)
    config = MagicMock()
    config.get = lambda key, default=None: defaults.get(key, default)
    return config


TRIGGER = Trigger(event_type="modulation_change", action_type="capture")
EVENT = {"event_type": "modulation_change", "severity": "warning",
         "timestamp": "2026-03-15T10:00:00Z", "message": "test"}


def _check_one(chain, trigger, event):
    """Helper: evaluate a single trigger via check_batch, return (allowed, reason)."""
    results = chain.check_batch([(trigger, event)])
    assert len(results) == 1
    _, _, allowed, reason = results[0]
    return allowed, reason


class TestGlobalCooldown:
    def test_first_fire_allowed(self):
        chain = GuardrailChain(_make_config())
        allowed, reason = _check_one(chain, TRIGGER, EVENT)
        assert allowed is True
        assert reason is None

    def test_second_event_within_cooldown_blocked(self):
        chain = GuardrailChain(_make_config(sc_global_cooldown=600))
        _check_one(chain, TRIGGER, EVENT)  # first fire
        allowed, reason = _check_one(chain, TRIGGER, EVENT)
        assert allowed is False
        assert "global_cooldown" in reason

    def test_fire_after_cooldown_disabled(self):
        chain = GuardrailChain(_make_config(sc_global_cooldown=0, sc_trigger_cooldown=0))
        _check_one(chain, TRIGGER, EVENT)
        allowed, reason = _check_one(chain, TRIGGER, EVENT)
        assert allowed is True


class TestBatchSemantics:
    def test_two_triggers_same_event_both_allowed(self):
        """Global cooldown must not suppress the second trigger for the same event."""
        chain = GuardrailChain(_make_config(sc_global_cooldown=300))
        t1 = Trigger(event_type="modulation_change", action_type="capture")
        t2 = Trigger(event_type="modulation_change", action_type="webhook")
        results = chain.check_batch([(t1, EVENT), (t2, EVENT)])
        assert len(results) == 2
        assert results[0][2] is True   # capture allowed
        assert results[1][2] is True   # webhook allowed

    def test_global_cooldown_set_after_batch(self):
        """After a batch with allowed executions, next batch is blocked by global cooldown."""
        chain = GuardrailChain(_make_config(sc_global_cooldown=300))
        chain.check_batch([(TRIGGER, EVENT)])
        # Second batch = new event, should be blocked
        allowed, reason = _check_one(chain, TRIGGER, EVENT)
        assert allowed is False
        assert "global_cooldown" in reason

    def test_global_cooldown_not_set_if_all_suppressed(self):
        """If all triggers in a batch are suppressed, global cooldown should not advance."""
        chain = GuardrailChain(_make_config(
            sc_global_cooldown=0, sc_trigger_cooldown=600,
        ))
        _check_one(chain, TRIGGER, EVENT)  # first fire, allowed
        _check_one(chain, TRIGGER, EVENT)  # second fire, trigger_cooldown blocks
        # Global cooldown should still reflect the first fire only
        other = Trigger(event_type="error_spike", action_type="capture")
        other_ev = {"event_type": "error_spike", "severity": "warning",
                    "timestamp": "2026-03-15T10:00:00Z", "message": "test"}
        allowed, _ = _check_one(chain, other, other_ev)
        assert allowed is True


class TestPerTriggerCooldown:
    def test_different_trigger_not_blocked(self):
        chain = GuardrailChain(_make_config(sc_global_cooldown=0))
        _check_one(chain, TRIGGER, EVENT)
        other_trigger = Trigger(event_type="error_spike", action_type="capture")
        other_event = {"event_type": "error_spike", "severity": "warning",
                       "timestamp": "2026-03-15T10:00:00Z", "message": "spike"}
        allowed, reason = _check_one(chain, other_trigger, other_event)
        assert allowed is True

    def test_same_trigger_within_cooldown_blocked(self):
        chain = GuardrailChain(_make_config(sc_global_cooldown=0,
                                            sc_trigger_cooldown=600))
        _check_one(chain, TRIGGER, EVENT)
        allowed, reason = _check_one(chain, TRIGGER, EVENT)
        assert allowed is False
        assert "trigger_cooldown" in reason


class TestMaxActionsPerHour:
    def test_blocks_after_max(self):
        chain = GuardrailChain(_make_config(
            sc_global_cooldown=0, sc_trigger_cooldown=0,
            sc_max_actions_per_hour=2, sc_flapping_threshold=999,
        ))
        _check_one(chain, TRIGGER, EVENT)
        other = Trigger(event_type="error_spike", action_type="capture")
        other_ev = {"event_type": "error_spike", "severity": "warning",
                    "timestamp": "2026-03-15T10:00:00Z", "message": "test"}
        _check_one(chain, other, other_ev)
        third = Trigger(event_type="power_change", action_type="capture")
        third_ev = {"event_type": "power_change", "severity": "warning",
                    "timestamp": "2026-03-15T10:00:00Z", "message": "test"}
        allowed, reason = _check_one(chain, third, third_ev)
        assert allowed is False
        assert "max_actions_per_hour" in reason


class TestFlappingSuppression:
    def test_blocks_after_threshold_counts_all_matches(self):
        """Flapping counts all matches, not just allowed executions."""
        chain = GuardrailChain(_make_config(
            sc_global_cooldown=0, sc_trigger_cooldown=0,
            sc_max_actions_per_hour=999,
            sc_flapping_threshold=2, sc_flapping_window=3600,
        ))
        _check_one(chain, TRIGGER, EVENT)
        _check_one(chain, TRIGGER, EVENT)
        allowed, reason = _check_one(chain, TRIGGER, EVENT)
        assert allowed is False
        assert "flapping" in reason

    def test_suppressed_matches_still_count_for_flapping(self):
        """Even if cooldown suppresses a trigger, the match increments flap counter."""
        chain = GuardrailChain(_make_config(
            sc_global_cooldown=0, sc_trigger_cooldown=600,
            sc_max_actions_per_hour=999,
            sc_flapping_threshold=3, sc_flapping_window=3600,
        ))
        _check_one(chain, TRIGGER, EVENT)  # match 1: allowed
        _check_one(chain, TRIGGER, EVENT)  # match 2: trigger_cooldown suppresses
        _check_one(chain, TRIGGER, EVENT)  # match 3: trigger_cooldown suppresses
        # 4th match: should be flapping (3 prior matches in window)
        allowed, reason = _check_one(chain, TRIGGER, EVENT)
        assert allowed is False
        assert "flapping" in reason

    def test_different_trigger_not_counted(self):
        chain = GuardrailChain(_make_config(
            sc_global_cooldown=0, sc_trigger_cooldown=0,
            sc_max_actions_per_hour=999,
            sc_flapping_threshold=2, sc_flapping_window=3600,
        ))
        _check_one(chain, TRIGGER, EVENT)
        _check_one(chain, TRIGGER, EVENT)
        other = Trigger(event_type="error_spike", action_type="capture")
        other_ev = {"event_type": "error_spike", "severity": "warning",
                    "timestamp": "2026-03-15T10:00:00Z", "message": "test"}
        allowed, reason = _check_one(chain, other, other_ev)
        assert allowed is True
