"""Focused contracts for the test-only browser server harness."""

from __future__ import annotations

import inspect
import socket
import sqlite3
import sys
import threading
import urllib.request
from contextlib import closing
from types import ModuleType

import pytest

from tests.e2e.support.application import (
    SEED_CACHE_ENV,
    demo_seed_cache_entry,
    install_demo_seed_cache,
    restore_seeded_databases,
    serve_server,
)
from tests.e2e.support.lifecycle import (
    HarnessCleanupError,
    ProcessSpec,
    ReadinessError,
    ServerEndpoint,
    _run_logged,
    cleanup_processes,
    reserve_local_port,
    running_processes,
    wait_for_server,
)
from tests.e2e.support.profiles import ServerProfile, ServerTarget


class _ExitedProcess:
    exitcode = 17

    def is_alive(self):
        return False

    def join(self, timeout):
        return None


class _RunningProcess:
    exitcode = None


class _KillFallbackProcess:
    exitcode = None

    def __init__(self):
        self.calls = []
        self.alive = True

    def is_alive(self):
        return self.alive

    def terminate(self):
        self.calls.append("terminate")

    def join(self, timeout):
        self.calls.append(("join", timeout))

    def kill(self):
        self.calls.append("kill")
        self.alive = False
        self.exitcode = -9


def _serve_health_forever(*, listener_socket):
    listener_socket.listen()
    while True:
        connection, _ = listener_socket.accept()
        with connection:
            connection.recv(4096)
            connection.sendall(
                b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\nOK"
            )


def _fail_during_startup(*, listener_socket):
    listener_socket.close()
    raise RuntimeError("startup credential must be redacted")


def _assert_port_reusable(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind(("127.0.0.1", port))


def test_os_assigned_port_reservations_are_unique_and_bound():
    try:
        reservations = [reserve_local_port() for _ in range(8)]
    except PermissionError:
        pytest.skip("this execution sandbox does not permit local sockets")
    try:
        assert len({reservation.port for reservation in reservations}) == 8
        for reservation in reservations:
            assert reservation.address == ("127.0.0.1", reservation.port)
            with pytest.raises(OSError):
                contender = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                try:
                    contender.bind(reservation.address)
                finally:
                    contender.close()
    finally:
        for reservation in reservations:
            reservation.close()


def test_readiness_failure_reports_identity_exit_code_and_redacted_log(tmp_path):
    log_path = tmp_path / "configured.log"
    log_path.write_text("startup failed for <redacted>\n", encoding="utf-8")
    endpoint = ServerEndpoint("configured-7", 43123, "", log_path)

    with pytest.raises(ReadinessError) as exc_info:
        wait_for_server(endpoint, _ExitedProcess(), timeout=0.01)

    message = str(exc_info.value)
    assert "configured-7" in message
    assert "exit code 17" in message
    assert "startup failed for <redacted>" in message


def test_readiness_sends_profile_specific_forwarded_prefix_headers():
    observed = {}

    class _Response:
        status_code = 200

    def request_get(url, **kwargs):
        observed.update(url=url, **kwargs)
        return _Response()

    endpoint = ServerEndpoint(
        "trusted-prefix",
        43129,
        "",
        None,
        (("X-Forwarded-Prefix", "/docsight, /docsight"),),
    )

    wait_for_server(endpoint, _RunningProcess(), request_get=request_get)

    assert observed == {
        "url": "http://127.0.0.1:43129/health",
        "timeout": 2,
        "headers": {"X-Forwarded-Prefix": "/docsight, /docsight"},
    }


def test_cleanup_uses_kill_fallback_and_verifies_closed_port():
    process = _KillFallbackProcess()
    endpoint = ServerEndpoint("demo-3", 43124, "", None)

    cleanup_processes(
        [(process, endpoint)],
        join_timeout=0.01,
        port_is_open=lambda _port: False,
    )

    assert process.calls == [
        "terminate",
        ("join", 0.01),
        "kill",
        ("join", 0.01),
    ]


def test_cleanup_fails_when_a_port_leaks_even_after_process_exit():
    process = _ExitedProcess()
    endpoint = ServerEndpoint("setup-2", 43125, "", None)

    with pytest.raises(HarnessCleanupError, match="setup-2.*43125.*open"):
        cleanup_processes(
            [(process, endpoint)],
            join_timeout=0.01,
            port_is_open=lambda _port: True,
        )


def test_spawn_handoff_runs_two_isolated_servers_and_releases_ports(tmp_path):
    reservations = [reserve_local_port(), reserve_local_port()]
    ports = [reservation.port for reservation in reservations]
    specs = [
        ProcessSpec(
            f"spawn-{index}",
            reservation,
            _serve_health_forever,
            log_path=tmp_path / f"spawn-{index}.log",
        )
        for index, reservation in enumerate(reservations, 1)
    ]

    with running_processes(specs):
        for port in ports:
            assert urllib.request.urlopen(
                f"http://127.0.0.1:{port}/health", timeout=2
            ).status == 200
            with (
                pytest.raises(OSError),
                socket.socket(socket.AF_INET, socket.SOCK_STREAM) as contender,
            ):
                contender.bind(("127.0.0.1", port))

    for port in ports:
        _assert_port_reusable(port)


def test_partial_spawn_failure_cleans_started_peer_and_redacts_log(tmp_path, capfd):
    healthy = reserve_local_port()
    failing = reserve_local_port()
    ports = [healthy.port, failing.port]
    credential = "startup credential"
    specs = [
        ProcessSpec(
            "healthy-peer",
            healthy,
            _serve_health_forever,
            log_path=tmp_path / "healthy.log",
        ),
        ProcessSpec(
            "failing-peer",
            failing,
            _fail_during_startup,
            log_path=tmp_path / "failing.log",
            secrets=(credential,),
        ),
    ]

    with pytest.raises(ReadinessError) as exc_info, running_processes(specs):
        pytest.fail("partial startup unexpectedly succeeded")

    assert credential not in str(exc_info.value)
    assert "<redacted>" in str(exc_info.value)
    assert credential not in capfd.readouterr().err
    for port in ports:
        _assert_port_reusable(port)


def test_profiles_and_targets_are_immutable_and_environment_isolated(
    tmp_path, monkeypatch
):
    profile = ServerProfile(
        name="configured",
        configured=True,
        demo_mode=False,
        base_path="/docsight",
    )
    target = ServerTarget(
        identity="configured-gw0",
        data_dir=str(tmp_path / "configured-gw0"),
        port=43126,
        profile=profile,
    )

    with pytest.raises(AttributeError):
        profile.name = "changed"
    with pytest.raises(AttributeError):
        target.port = 1

    monkeypatch.setenv("DEMO_MODE", "stale")
    monkeypatch.setenv("REVERSE_PROXY_PREFIX", "9")
    monkeypatch.setenv("ADMIN_PASSWORD", "must-not-leak")
    monkeypatch.setenv("MODEM_TYPE", "must-not-leak")
    monkeypatch.setenv("NOTIFY_APPRISE_TOKEN", "must-not-leak")
    monkeypatch.setenv("UNRELATED_SECRET", "must-not-leak")
    environment = target.environment()
    assert environment["DATA_DIR"] == str(tmp_path / "configured-gw0")
    assert environment["BASE_PATH"] == "/docsight"
    assert environment["LOG_LEVEL"] == "WARNING"
    assert "DEMO_MODE" not in environment
    assert "REVERSE_PROXY_PREFIX" not in environment
    assert "ADMIN_PASSWORD" not in environment
    assert "MODEM_TYPE" not in environment
    assert "NOTIFY_APPRISE_TOKEN" not in environment
    assert "UNRELATED_SECRET" not in environment


def test_target_repr_never_contains_credentials(tmp_path):
    credential = "test-credential-value"
    target = ServerTarget(
        identity="auth-gw0",
        data_dir=str(tmp_path / "auth-gw0"),
        port=43127,
        profile=ServerProfile(name="auth", configured=True, demo_mode=True),
        admin_password=credential,
    )

    assert credential not in repr(target)


def test_child_log_capture_redacts_credentials(tmp_path):
    log_path = tmp_path / "auth.log"

    def emit_secret(*, listener_socket):
        assert listener_socket is None
        print("credential=do-not-log-this")

    _run_logged(
        str(log_path),
        ("do-not-log-this",),
        emit_secret,
        (),
        None,
    )

    assert log_path.read_text(encoding="utf-8") == "credential=<redacted>\n"


def test_production_startup_keeps_reserved_socket_through_app_main(
    tmp_path, monkeypatch
):
    import waitress

    listener = object()
    observed = {}

    def original_create_server(application, **kwargs):
        observed.update(kwargs)
        return object()

    fake_main_module = ModuleType("app.main")

    def fake_main():
        from waitress import create_server

        create_server(object(), host="127.0.0.1", port=43128, threads=4)

    fake_main_module.main = fake_main
    monkeypatch.setitem(sys.modules, "app.main", fake_main_module)
    monkeypatch.setattr(waitress, "create_server", original_create_server)
    monkeypatch.setattr(ServerTarget, "apply_environment", lambda self: None)
    target = ServerTarget(
        identity="first-run-gw0",
        data_dir=str(tmp_path / "first-run-gw0"),
        port=43128,
        profile=ServerProfile(
            name="first-run-production-startup",
            configured=False,
            demo_mode=False,
            production_startup=True,
        ),
    )

    serve_server(target, listener_socket=listener)

    assert observed == {"sockets": [listener], "threads": 4}


class _FakeRuntime:
    def __init__(self):
        self.state = {"analysis": None}

    def get_state(self):
        return dict(self.state)

    def update_state(self, **fields):
        self.state.update(fields)


class _FakeStorage:
    def __init__(self, db_path):
        self.db_path = db_path
        self.max_days = 7


_SEED_RUNS = {}


class _FakeCollector:
    """Seeds like DemoCollector: database rows plus in-memory state."""

    def __init__(self, storage, runtime, extra=None):
        self._storage = storage
        self._web = runtime
        self._counters = {"3.0": 0}
        self._extra = extra

    @property
    def seed_runs(self):
        # Counted outside the instance so a replayed seed cannot copy it.
        return _SEED_RUNS.get(id(self), 0)

    def _seed_demo_data(self):
        _SEED_RUNS[id(self)] = self.seed_runs + 1
        with closing(sqlite3.connect(self._storage.db_path)) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS snapshots (value INTEGER)")
            connection.executemany(
                "INSERT INTO snapshots VALUES (?)", [(index,) for index in range(50)]
            )
            connection.commit()
        self._counters = {"3.0": 4711}
        self._storage.max_days = 0
        self._web.update_state(speedtest_latest={"download": 250.0})
        if self._extra is not None:
            self._extra(self)


def _fresh_server(data_dir, extra=None):
    data_dir.mkdir(parents=True, exist_ok=True)
    with closing(sqlite3.connect(data_dir / "docsis_history.db")) as connection:
        connection.execute("CREATE TABLE IF NOT EXISTS _meta (key TEXT)")
    runtime = _FakeRuntime()
    storage = _FakeStorage(str(data_dir / "docsis_history.db"))
    return _FakeCollector(storage, runtime, extra), runtime, storage


def test_seed_cache_key_follows_modules_and_modem_not_mount_or_password(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(SEED_CACHE_ENV, str(tmp_path))
    demo = ServerProfile("demo", configured=True, demo_mode=True)
    mounted = ServerProfile(
        "mount-auth", configured=True, demo_mode=True, mount_path="/docsight",
        base_path="/docsight", trusted_prefix_hops=2,
    )

    assert demo_seed_cache_entry(demo) == demo_seed_cache_entry(mounted)
    for other in (
        ServerProfile("tkg", configured=True, demo_mode=True, disabled_modules="docsight.bnetz"),
        ServerProfile("fritzbox", configured=True, demo_mode=True, modem_type="fritzbox"),
        ServerProfile("configured", configured=True, demo_mode=False),
    ):
        assert demo_seed_cache_entry(other) != demo_seed_cache_entry(demo)
    assert demo_seed_cache_entry(
        ServerProfile("setup", configured=False, demo_mode=False)
    ) is None
    assert demo_seed_cache_entry(
        ServerProfile("own-seed", configured=True, demo_mode=False, seed_callback=print)
    ) is None
    monkeypatch.delenv(SEED_CACHE_ENV)
    assert demo_seed_cache_entry(demo) is None


def test_seed_cache_replays_databases_and_state_without_seeding_again(tmp_path):
    entry = tmp_path / "cache" / "demo-key"
    entry.parent.mkdir()
    first, first_runtime, first_storage = _fresh_server(tmp_path / "first")
    assert restore_seeded_databases(entry, str(tmp_path / "first")) is None
    install_demo_seed_cache(
        first, first_runtime, first_storage, entry, None, str(tmp_path / "first")
    )
    first._seed_demo_data()
    assert first.seed_runs == 1
    assert (entry / "docsis_history.db").is_file()
    assert not list(entry.parent.glob(".demo-key-*"))

    second_dir = tmp_path / "second"
    state = restore_seeded_databases(entry, str(second_dir))
    second, second_runtime, second_storage = _fresh_server(second_dir)
    install_demo_seed_cache(
        second, second_runtime, second_storage, entry, state, str(second_dir)
    )
    second._seed_demo_data()

    assert second.seed_runs == 0
    assert second._counters == {"3.0": 4711}
    assert second_storage.max_days == 0
    assert second_runtime.state["speedtest_latest"] == {"download": 250.0}
    with closing(sqlite3.connect(second_dir / "docsis_history.db")) as connection:
        assert connection.execute("SELECT COUNT(*) FROM snapshots").fetchone() == (50,)
    # The replayed state is a copy, not shared with the template.
    second._counters["3.0"] = 1
    assert restore_seeded_databases(entry, str(tmp_path / "third"))["collector"][
        "_counters"
    ] == {"3.0": 4711}


@pytest.mark.parametrize("defect", ["unpicklable-state", "foreign-file"])
def test_seed_cache_never_publishes_a_seed_it_cannot_replay(tmp_path, defect):
    def extra(collector):
        if defect == "unpicklable-state":
            collector._lock = threading.Lock()
        else:
            (tmp_path / "server" / "extra.bin").write_bytes(b"seeded elsewhere")

    entry = tmp_path / "cache" / "demo-key"
    entry.parent.mkdir()
    collector, runtime, storage = _fresh_server(tmp_path / "server", extra)
    install_demo_seed_cache(
        collector, runtime, storage, entry, None, str(tmp_path / "server")
    )
    collector._seed_demo_data()

    assert collector.seed_runs == 1
    assert not entry.exists()
    assert restore_seeded_databases(entry, str(tmp_path / "next")) is None


def test_demo_collector_still_seeds_through_the_replaced_hook():
    from app.collectors.demo import DemoCollector

    source = inspect.getsource(DemoCollector.collect)
    assert "self._seed_demo_data()" in source
