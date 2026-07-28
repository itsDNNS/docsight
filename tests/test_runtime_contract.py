"""Runtime contract tests for portable DOCSight startup."""

import os
import sys
import threading
import time
import types
from unittest.mock import Mock

from app import main as app_main
from app.drivers import driver_registry
from app.runtime import RuntimeController


class _Config:
    def __init__(
        self,
        timezone="Europe/Berlin",
        history_days=14,
        configured=True,
        modem_type="fritzbox",
    ):
        self.timezone = timezone
        self.history_days = history_days
        self.configured = configured
        self.modem_type = modem_type
        self.load_calls = 0

    def get(self, key, default=None):
        if key == "timezone":
            return self.timezone
        if key == "history_days":
            return self.history_days
        if key == "modem_type":
            return self.modem_type
        return default

    def _load(self):
        self.load_calls += 1

    def is_configured(self):
        return self.configured


class _Storage:
    def __init__(self):
        self.max_days = None


def test_run_web_defaults_to_public_bind(monkeypatch):
    calls = []

    def fake_serve(app, **kwargs):
        calls.append(kwargs)

    monkeypatch.delenv("WEB_HOST", raising=False)
    monkeypatch.setitem(sys.modules, "waitress", types.SimpleNamespace(serve=fake_serve))

    app_main.run_web(8765)

    assert calls == [{"host": "0.0.0.0", "port": 8765, "threads": 4, "_quiet": True}]


def test_run_web_honors_web_host_env(monkeypatch):
    calls = []

    def fake_serve(app, **kwargs):
        calls.append(kwargs)

    monkeypatch.setenv("WEB_HOST", "127.0.0.1")
    monkeypatch.setitem(sys.modules, "waitress", types.SimpleNamespace(serve=fake_serve))

    app_main.run_web(8770)

    assert calls == [{"host": "127.0.0.1", "port": 8770, "threads": 4, "_quiet": True}]


def test_apply_timezone_skips_missing_tzset(monkeypatch):
    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.delattr(app_main.time, "tzset", raising=False)

    app_main._apply_timezone(_Config())

    assert os.environ["TZ"] == "Europe/Berlin"


def test_apply_timezone_calls_tzset_when_available(monkeypatch):
    calls = []

    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.setattr(app_main.time, "tzset", lambda: calls.append("tzset"), raising=False)

    app_main._apply_timezone(_Config("UTC"))

    assert os.environ["TZ"] == "UTC"
    assert calls == ["tzset"]


def test_runtime_apply_uses_guarded_timezone_and_starts_configured_instance(
    monkeypatch,
):
    cfg = _Config(timezone="Europe/Berlin", history_days=30, configured=True)
    storage = _Storage()
    runtime = RuntimeController(
        cfg,
        storage,
        lambda _config, _storage, stop_event: stop_event.wait(),
    )

    monkeypatch.delenv("TZ", raising=False)
    monkeypatch.delattr(app_main.time, "tzset", raising=False)

    runtime.apply_config_changed()

    assert cfg.load_calls == 1
    assert os.environ["TZ"] == "Europe/Berlin"
    assert storage.max_days == 30
    assert runtime.desired_running is True
    runtime.shutdown()


def test_runtime_apply_stops_polling_when_instance_becomes_unconfigured(monkeypatch):
    cfg = _Config(timezone="Europe/Berlin", history_days=7, configured=False)
    storage = _Storage()
    runtime = RuntimeController(cfg, storage, Mock())

    monkeypatch.setattr(app_main, "_apply_timezone", lambda _cfg: None)

    runtime.apply_config_changed()

    assert cfg.load_calls == 1
    assert storage.max_days == 7
    assert runtime.desired_running is False
    assert runtime.is_running is False


def test_runtime_start_and_stop_reset_modem_state_once_per_transition():
    resets = []
    collector_sets = []
    collectors_sets = []
    fake_web = types.SimpleNamespace(
        init_collector=lambda value: collector_sets.append(value),
        init_collectors=lambda value: collectors_sets.append(value),
        reset_modem_state=lambda: resets.append("reset"),
        get_collectors=lambda: [],
    )

    def polling_target(_config, _storage, stop_event):
        stop_event.wait()

    runtime = RuntimeController(
        _Config(),
        _Storage(),
        polling_target,
        web_module=fake_web,
    )

    runtime.start_polling()
    assert runtime.is_running is True
    assert resets == ["reset"]

    runtime.stop_polling()
    assert runtime.wait_for_state(False)

    assert runtime.is_running is False
    assert resets == ["reset", "reset"]
    assert collector_sets == [None, None]
    assert collectors_sets == [[], []]


def test_slow_poll_handoff_uses_latest_desired_state_without_overlap():
    state_lock = threading.Lock()
    first_started = threading.Event()
    second_started = threading.Event()
    allow_first_exit = threading.Event()
    active = 0
    maximum_active = 0
    starts = 0

    def polling_target(_config, _storage, stop_event):
        nonlocal active, maximum_active, starts
        with state_lock:
            starts += 1
            run_number = starts
            active += 1
            maximum_active = max(maximum_active, active)
        (first_started if run_number == 1 else second_started).set()
        try:
            stop_event.wait()
            if run_number == 1:
                allow_first_exit.wait()
        finally:
            with state_lock:
                active -= 1

    fake_web = types.SimpleNamespace(
        init_collector=Mock(),
        init_collectors=Mock(),
        reset_modem_state=Mock(),
        get_collectors=lambda: [],
    )
    runtime = RuntimeController(
        _Config(),
        _Storage(),
        polling_target,
        web_module=fake_web,
        stop_timeout=0.01,
    )

    runtime.start_polling()
    assert first_started.wait(timeout=1)

    # Config/start requests want a replacement, then demo exit wins while the
    # attributed predecessor is still winding down.
    runtime.start_polling()
    runtime.start_polling()
    runtime.stop_polling()
    assert runtime.desired_running is False
    assert starts == 1
    assert maximum_active == 1

    allow_first_exit.set()
    assert runtime.wait_for_state(False)
    assert starts == 1

    # A later config/demo-start transition becomes the latest desired state.
    runtime.start_polling()
    assert second_started.wait(timeout=1)
    assert runtime.is_running is True
    assert starts == 2
    assert maximum_active == 1

    runtime.stop_polling()
    assert runtime.wait_for_state(False)
    assert active == 0
    assert starts == 2
    assert maximum_active == 1


def test_slow_poll_eventually_restarts_once_after_multiple_running_transitions():
    first_started = threading.Event()
    replacement_started = threading.Event()
    allow_first_exit = threading.Event()
    state_lock = threading.Lock()
    starts = 0
    active = 0
    maximum_active = 0

    def polling_target(_config, _storage, stop_event):
        nonlocal starts, active, maximum_active
        with state_lock:
            starts += 1
            run_number = starts
            active += 1
            maximum_active = max(maximum_active, active)
        (first_started if run_number == 1 else replacement_started).set()
        try:
            stop_event.wait()
            if run_number == 1:
                allow_first_exit.wait()
        finally:
            with state_lock:
                active -= 1

    runtime = RuntimeController(
        _Config(),
        _Storage(),
        polling_target,
        stop_timeout=0.01,
    )
    runtime.start_polling()
    assert first_started.wait(timeout=1)

    initial_generation = runtime.generation
    runtime.start_polling()
    runtime.start_polling()
    assert runtime.generation == initial_generation + 2
    assert starts == 1

    allow_first_exit.set()
    assert replacement_started.wait(timeout=1)
    assert starts == 2
    assert maximum_active == 1

    runtime.shutdown()
    assert active == 0
    assert runtime.is_running is False
    assert runtime._handoff_thread is None


def test_unexpected_poll_exit_is_reconciled_without_a_monitoring_gap():
    second_started = threading.Event()
    starts = 0

    def polling_target(_config, _storage, stop_event):
        nonlocal starts
        starts += 1
        if starts == 1:
            return
        second_started.set()
        stop_event.wait()

    runtime = RuntimeController(_Config(), _Storage(), polling_target)

    runtime.start_polling()

    assert second_started.wait(timeout=1)
    assert starts == 2
    assert runtime.is_running is True
    assert runtime.desired_running is True

    runtime.shutdown()
    assert runtime.is_running is False
    assert runtime._handoff_thread is None


def test_permanent_poll_failure_has_exact_budget_and_exponential_backoff(
    caplog,
):
    starts = []
    state_lock = threading.Lock()

    def polling_target(_config, _storage, _stop_event):
        with state_lock:
            starts.append(time.monotonic())
        raise RuntimeError("credential=must-not-appear")

    runtime = RuntimeController(
        _Config(),
        _Storage(),
        polling_target,
        restart_initial_delay=0.03,
        restart_max_delay=0.05,
        restart_max_failures=4,
    )

    runtime.start_polling()
    with runtime._state_changed:
        assert runtime._state_changed.wait_for(
            lambda: runtime._restart_exhausted,
            timeout=1,
        )

    with state_lock:
        observed_starts = list(starts)
    assert len(observed_starts) == 4
    intervals = [
        later - earlier
        for earlier, later in zip(observed_starts, observed_starts[1:])
    ]
    assert intervals[0] >= 0.02
    assert intervals[1] >= 0.04
    assert intervals[2] >= 0.04
    assert runtime.desired_running is True
    assert runtime.is_running is False
    assert runtime.status()["restart_exhausted"] is True
    assert runtime.status()["last_failure"] == {"type": "RuntimeError"}
    assert "must-not-appear" not in caplog.text
    assert caplog.text.count("ended unexpectedly") == 4
    assert caplog.text.count("restart budget exhausted") == 1

    runtime.shutdown()


def test_zero_delay_storm_probe_still_has_a_hard_start_ceiling():
    starts = 0

    def polling_target(_config, _storage, _stop_event):
        nonlocal starts
        starts += 1
        raise ValueError("unknown modem type")

    runtime = RuntimeController(
        _Config(),
        _Storage(),
        polling_target,
        restart_initial_delay=0,
        restart_max_delay=0,
        restart_max_failures=6,
    )

    runtime.start_polling()
    with runtime._state_changed:
        assert runtime._state_changed.wait_for(
            lambda: runtime._restart_exhausted,
            timeout=1,
        )

    assert starts == 6
    assert runtime._handoff_thread is None
    runtime.shutdown()


def test_unknown_backup_modem_uses_production_registry_with_bounded_retries():
    cfg = _Config(modem_type="removed-third-party-driver")
    starts = 0

    def polling_target(config, _storage, _stop_event):
        nonlocal starts
        starts += 1
        driver_registry.load_driver(
            config.get("modem_type"),
            "http://192.0.2.1",
            "",
            "",
        )

    runtime = RuntimeController(
        cfg,
        _Storage(),
        polling_target,
        restart_initial_delay=0,
        restart_max_delay=0,
        restart_max_failures=3,
    )

    runtime.start_polling()
    with runtime._state_changed:
        assert runtime._state_changed.wait_for(
            lambda: runtime._restart_exhausted,
            timeout=1,
        )

    assert starts == 3
    assert runtime.status()["last_failure"] == {"type": "ValueError"}
    assert runtime.desired_running is True
    assert runtime.is_running is False
    runtime.shutdown()


def test_stop_during_restart_backoff_prevents_restart():
    first_finished = threading.Event()
    starts = 0

    def polling_target(_config, _storage, _stop_event):
        nonlocal starts
        starts += 1
        first_finished.set()

    runtime = RuntimeController(
        _Config(),
        _Storage(),
        polling_target,
        restart_initial_delay=1,
        restart_max_delay=1,
        restart_max_failures=3,
    )

    runtime.start_polling()
    assert first_finished.wait(timeout=1)
    with runtime._state_changed:
        assert runtime._state_changed.wait_for(
            lambda: (
                runtime._consecutive_failures == 1
                and runtime._attempt is None
            ),
            timeout=1,
        )

    runtime.stop_polling()
    with runtime._state_changed:
        assert runtime._state_changed.wait_for(
            lambda: runtime._handoff_thread is None,
            timeout=1,
        )

    assert starts == 1
    assert runtime.desired_running is False
    assert runtime.is_running is False


def test_explicit_start_resets_exhausted_budget_and_recovers_once():
    fail = True
    healthy_started = threading.Event()
    starts = 0

    def polling_target(_config, _storage, stop_event):
        nonlocal starts
        starts += 1
        if fail:
            raise RuntimeError("bad config")
        healthy_started.set()
        stop_event.wait()

    runtime = RuntimeController(
        _Config(),
        _Storage(),
        polling_target,
        restart_initial_delay=0,
        restart_max_delay=0,
        restart_max_failures=2,
    )
    runtime.start_polling()
    with runtime._state_changed:
        assert runtime._state_changed.wait_for(
            lambda: runtime._restart_exhausted,
            timeout=1,
        )

    fail = False
    runtime.start_polling()

    assert healthy_started.wait(timeout=1)
    assert starts == 3
    assert runtime.status()["restart_failures"] == 0
    assert runtime.status()["restart_exhausted"] is False
    assert runtime.is_running is True
    runtime.shutdown()


def test_apply_config_resets_exhausted_budget_and_recovers_once(monkeypatch):
    fail = True
    healthy_started = threading.Event()
    starts = 0

    def polling_target(_config, _storage, stop_event):
        nonlocal starts
        starts += 1
        if fail:
            raise RuntimeError("bad backup config")
        healthy_started.set()
        stop_event.wait()

    cfg = _Config(configured=True)
    runtime = RuntimeController(
        cfg,
        _Storage(),
        polling_target,
        restart_initial_delay=0,
        restart_max_delay=0,
        restart_max_failures=2,
    )
    monkeypatch.setattr(app_main, "_apply_timezone", lambda _cfg: None)
    runtime.start_polling()
    with runtime._state_changed:
        assert runtime._state_changed.wait_for(
            lambda: runtime._restart_exhausted,
            timeout=1,
        )

    fail = False
    runtime.apply_config_changed()

    assert healthy_started.wait(timeout=1)
    assert starts == 3
    assert cfg.load_calls == 1
    assert runtime.status()["restart_failures"] == 0
    assert runtime.is_running is True
    runtime.shutdown()


def test_shutdown_is_bounded_and_late_exit_keeps_attribution_until_cleanup():
    started = threading.Event()
    release = threading.Event()
    starts = 0

    def polling_target(_config, _storage, stop_event):
        nonlocal starts
        starts += 1
        started.set()
        stop_event.wait()
        release.wait()

    runtime = RuntimeController(
        _Config(),
        _Storage(),
        polling_target,
        stop_timeout=0.03,
    )
    runtime.start_polling()
    assert started.wait(timeout=1)

    before = time.monotonic()
    runtime.shutdown()
    elapsed = time.monotonic() - before

    assert elapsed < 0.15
    assert runtime.is_running is True
    assert runtime.status()["poll_attributed"] is True
    assert runtime._poll_thread is not None
    assert runtime._handoff_thread is not None

    release.set()
    assert runtime.wait_for_state(False, timeout=1)
    with runtime._state_changed:
        assert runtime._state_changed.wait_for(
            lambda: runtime._handoff_thread is None,
            timeout=1,
        )
    assert starts == 1
    assert runtime.is_running is False
    assert runtime.status()["poll_attributed"] is False
