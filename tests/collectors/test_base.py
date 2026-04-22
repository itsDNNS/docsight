"""Tests for collector and modem driver base contracts."""

"""Tests for the unified Collector Architecture."""

import os
import tempfile
import time
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

from app.collectors.base import Collector, CollectorResult
from app.collectors.modem import ModemCollector
from app.modules.speedtest.collector import SpeedtestCollector
from app.modules.bqm.collector import BQMCollector
from app.drivers.base import ModemDriver
from app.drivers.fritzbox import FritzBoxDriver
from app.drivers.ch7465 import CH7465Driver
from app.drivers.ch7465_play import CH7465PlayDriver


class TestCollectorResult:
    def test_defaults(self):
        r = CollectorResult(source="test")
        assert r.source == "test"
        assert r.data is None
        assert r.success is True
        assert r.error is None
        assert r.timestamp > 0

    def test_failure(self):
        r = CollectorResult(source="test", success=False, error="timeout")
        assert not r.success
        assert r.error == "timeout"


# ── Collector ABC Tests ──


class ConcreteCollector(Collector):
    name = "test"

    def __init__(self, poll_interval=60):
        super().__init__(poll_interval)
        self.call_count = 0

    def collect(self):
        self.call_count += 1
        return CollectorResult(source=self.name)


class TestCollectorABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            Collector(60)

    def test_initial_state(self):
        c = ConcreteCollector(120)
        assert c.name == "test"
        assert c.poll_interval_seconds == 120
        assert c._consecutive_failures == 0
        assert c._last_poll == 0.0
        assert c.is_enabled() is True

    def test_should_poll_initially(self):
        c = ConcreteCollector()
        assert c.should_poll() is True

    def test_should_not_poll_right_after_success(self):
        c = ConcreteCollector(60)
        c.record_success()
        assert c.should_poll() is False

    def test_penalty_zero_on_no_failures(self):
        c = ConcreteCollector()
        assert c.penalty_seconds == 0

    def test_penalty_exponential_backoff(self):
        c = ConcreteCollector()
        c._consecutive_failures = 1
        assert c.penalty_seconds == 30
        c._consecutive_failures = 2
        assert c.penalty_seconds == 60
        c._consecutive_failures = 3
        assert c.penalty_seconds == 120
        c._consecutive_failures = 4
        assert c.penalty_seconds == 240

    def test_penalty_capped_at_max(self):
        c = ConcreteCollector()
        c._consecutive_failures = 100
        assert c.penalty_seconds == 3600

    def test_effective_interval_includes_penalty(self):
        c = ConcreteCollector(60)
        assert c.effective_interval == 60
        c._consecutive_failures = 1
        assert c.effective_interval == 90  # 60 + 30

    def test_record_success_resets_failures(self):
        c = ConcreteCollector()
        c._consecutive_failures = 5
        c.record_success()
        assert c._consecutive_failures == 0
        assert c._last_poll > 0

    def test_record_failure_increments(self):
        c = ConcreteCollector()
        c.record_failure()
        assert c._consecutive_failures == 1
        c.record_failure()
        assert c._consecutive_failures == 2
        assert c._last_poll > 0

    def test_should_poll_respects_interval(self):
        c = ConcreteCollector(1)
        c.record_success()
        assert c.should_poll() is False
        time.sleep(1.1)
        assert c.should_poll() is True


# ── ModemDriver ABC Tests ──


class TestModemDriverABC:
    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            ModemDriver("http://modem", "user", "pass")

    def test_concrete_driver_stores_credentials(self):
        class DummyDriver(ModemDriver):
            def login(self): pass
            def get_docsis_data(self): return {}
            def get_device_info(self): return {}
            def get_connection_info(self): return {}

        d = DummyDriver("http://modem", "admin", "secret")
        assert d._url == "http://modem"
        assert d._user == "admin"
        assert d._password == "secret"

