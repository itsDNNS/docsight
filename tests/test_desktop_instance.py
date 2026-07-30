"""Focused tests for Windows desktop runtime ownership."""

from __future__ import annotations

import email.message
import importlib.util
import io
import json
import os
import sys
import threading
import urllib.request
import urllib.response
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import desktop_runtime_contract as contract

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DIR = ROOT / "packaging" / "windows"
MODULE_PATH = WINDOWS_DIR / "desktop_instance.py"
if str(WINDOWS_DIR) not in sys.path:
    sys.path.insert(0, str(WINDOWS_DIR))

spec = importlib.util.spec_from_file_location("docsight_desktop_instance", MODULE_PATH)
assert spec is not None
assert spec.loader is not None
runtime = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = runtime
spec.loader.exec_module(runtime)

TOKEN = "A" * 43
OTHER_TOKEN = "B" * 43
OWNER = "S-1-5-21-1000"
PID = 4242
START_TIME = 133700000


def make_state(**overrides):
    values = {
        "pid": PID,
        "port": 8765,
        "application_version": "v1.2.3",
        "process_start_time": START_TIME,
        "instance_token": TOKEN,
    }
    values.update(overrides)
    return runtime.RuntimeState.create(**values)


class FakeMutex:
    def __init__(self, acquire_results):
        self.acquire_results = list(acquire_results)
        self.owned = False
        self.closed = False
        self.release_calls = 0

    def acquire(self, timeout_milliseconds=0):
        del timeout_milliseconds
        result = self.acquire_results.pop(0) if self.acquire_results else False
        self.owned = result
        return result

    def release(self):
        if self.owned:
            self.release_calls += 1
            self.owned = False

    def close(self):
        self.release()
        self.closed = True


class FakeInspector:
    def __init__(self, identities):
        self.identities = identities
        self.calls = []

    def inspect(self, pid):
        self.calls.append(pid)
        return self.identities.get(pid)


def make_coordinator(
    tmp_path,
    *,
    mutex=None,
    inspector=None,
    endpoint_probe=lambda state: True,
    env=None,
    token=TOKEN,
    monotonic=None,
    sleep=None,
):
    identity = runtime.ProcessIdentity(PID, OWNER, START_TIME)
    return runtime.DesktopInstance(
        store=runtime.RuntimeStateStore(tmp_path / "runtime.json"),
        mutex=mutex or FakeMutex([True]),
        inspector=inspector or FakeInspector({PID: identity}),
        current_user_id=OWNER,
        env=env if env is not None else {},
        current_pid=PID,
        token_factory=lambda: token,
        endpoint_probe=endpoint_probe,
        monotonic=monotonic or (lambda: 0.0),
        sleep=sleep or (lambda _seconds: None),
    )


def test_runtime_state_round_trips_with_exact_schema():
    state = make_state()

    assert runtime.RuntimeState.from_mapping(state.to_mapping()) == state
    assert state.to_mapping() == {
        "schema_version": 1,
        "pid": PID,
        "port": 8765,
        "application_version": "v1.2.3",
        "process_start_time": START_TIME,
        "instance_token": TOKEN,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 2),
        ("schema_version", True),
        ("pid", 0),
        ("pid", "4242"),
        ("port", 0),
        ("port", 65536),
        ("process_start_time", -1),
        ("application_version", ""),
        ("application_version", "bad\nversion"),
        ("instance_token", "guessable"),
        ("instance_token", 123),
    ],
)
def test_runtime_state_rejects_invalid_types_and_ranges(field, value):
    mapping = make_state().to_mapping()
    mapping[field] = value

    with pytest.raises(ValueError):
        runtime.RuntimeState.from_mapping(mapping)


def test_runtime_state_rejects_missing_and_extra_fields():
    mapping = make_state().to_mapping()
    mapping["unexpected"] = True

    with pytest.raises(ValueError):
        runtime.RuntimeState.from_mapping(mapping)

    mapping.pop("unexpected")
    mapping.pop("pid")
    with pytest.raises(ValueError):
        runtime.RuntimeState.from_mapping(mapping)


def test_runtime_store_atomically_replaces_existing_state(monkeypatch, tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text("old-state", encoding="utf-8")
    store = runtime.RuntimeStateStore(path)
    real_replace = os.replace
    calls = []

    def checked_replace(source, destination):
        assert Path(destination).read_text(encoding="utf-8") == "old-state"
        assert Path(source).parent == path.parent
        calls.append((Path(source), Path(destination)))
        real_replace(source, destination)

    monkeypatch.setattr(runtime.os, "replace", checked_replace)

    store.replace(make_state())

    assert len(calls) == 1
    assert store.load() == make_state()
    assert list(tmp_path.glob(".runtime.json.*.tmp")) == []


def sharing_error(winerror):
    error = OSError("sharing failure")
    error.winerror = winerror
    return error


def test_runtime_store_retries_read_sharing_violations(monkeypatch, tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text(json.dumps(make_state().to_mapping()), encoding="utf-8")
    real_read_text = Path.read_text
    attempts = []
    sleeps = []

    def flaky_read_text(target, *args, **kwargs):
        if target == path:
            attempts.append(target)
            if len(attempts) < 3:
                raise sharing_error(32)
        return real_read_text(target, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", flaky_read_text)
    store = runtime.RuntimeStateStore(path, sleep=sleeps.append)

    assert store.load() == make_state()
    assert len(attempts) == 3
    assert sleeps == [0.025, 0.025]


def test_runtime_store_retries_replace_and_remove_sharing_violations(
    monkeypatch,
    tmp_path,
):
    path = tmp_path / "runtime.json"
    real_replace = os.replace
    real_unlink = Path.unlink
    replace_attempts = []
    unlink_attempts = []
    sleeps = []

    def flaky_replace(source, destination):
        replace_attempts.append((source, destination))
        if len(replace_attempts) == 1:
            raise sharing_error(5)
        return real_replace(source, destination)

    def flaky_unlink(target, *args, **kwargs):
        if target == path:
            unlink_attempts.append(target)
            if len(unlink_attempts) == 1:
                raise sharing_error(33)
        return real_unlink(target, *args, **kwargs)

    monkeypatch.setattr(runtime.os, "replace", flaky_replace)
    store = runtime.RuntimeStateStore(path, sleep=sleeps.append)
    store.replace(make_state())
    monkeypatch.setattr(Path, "unlink", flaky_unlink)
    store.remove()

    assert len(replace_attempts) == 2
    assert len(unlink_attempts) == 2
    assert sleeps == [0.025, 0.025]
    assert not path.exists()


def test_runtime_store_does_not_retry_unrelated_os_errors(monkeypatch, tmp_path):
    path = tmp_path / "runtime.json"
    attempts = []
    sleeps = []

    def failed_read_text(*_args, **_kwargs):
        attempts.append(True)
        raise sharing_error(87)

    monkeypatch.setattr(Path, "read_text", failed_read_text)
    store = runtime.RuntimeStateStore(path, sleep=sleeps.append)

    with pytest.raises(runtime.RuntimeStateError):
        store.load()
    assert attempts == [True]
    assert sleeps == []


@pytest.mark.parametrize("contents", ["{", "[]", '{"schema_version":1}', "\udcff"])
def test_runtime_store_treats_malformed_state_as_unusable(tmp_path, contents):
    path = tmp_path / "runtime.json"
    if contents == "\udcff":
        path.write_bytes(b"\xff")
    else:
        path.write_text(contents, encoding="utf-8")

    assert runtime.RuntimeStateStore(path).load() is None


def test_runtime_store_cleanup_does_not_remove_a_newer_owner(tmp_path):
    store = runtime.RuntimeStateStore(tmp_path / "runtime.json")
    store.replace(make_state(instance_token=OTHER_TOKEN))

    store.remove(expected_token=TOKEN)

    assert store.load() == make_state(instance_token=OTHER_TOKEN)


def test_sid_mutex_name_is_machine_visible_and_per_user():
    first = runtime.mutex_name_for_user("S-1-5-21-1000")
    same = runtime.mutex_name_for_user("S-1-5-21-1000")
    other = runtime.mutex_name_for_user("S-1-5-21-2000")

    assert first.startswith("Global\\DOCSight.Desktop.")
    assert first == same
    assert first != other
    assert "Local\\" not in first


def test_factory_uses_same_sid_mutex_for_direct_and_independent_lookup(
    monkeypatch,
    tmp_path,
):
    current_pid = os.getpid()
    captured_names = []

    class Inspector:
        def __init__(self, *, direct_sid):
            self.direct_sid = direct_sid

        def current_user_sid(self):
            if not self.direct_sid:
                raise OSError("SID unavailable")
            return OWNER

        def inspect(self, pid):
            return runtime.ProcessIdentity(pid, OWNER, START_TIME)

    class Mutex(FakeMutex):
        def __init__(self, name):
            captured_names.append(name)
            super().__init__([True])

    inspectors = iter((Inspector(direct_sid=True), Inspector(direct_sid=False)))
    monkeypatch.setattr(runtime, "Win32ProcessInspector", lambda: next(inspectors))
    monkeypatch.setattr(runtime, "Win32NamedMutex", Mutex)

    direct = runtime.create_desktop_instance(tmp_path / "direct.json", {})
    independent = runtime.create_desktop_instance(tmp_path / "independent.json", {})

    assert captured_names == [
        runtime.mutex_name_for_user(OWNER),
        runtime.mutex_name_for_user(OWNER),
    ]
    assert independent.coordinate().role is runtime.InstanceRole.OWNER
    independent.publish(port=8765, application_version="v1")
    assert runtime.RuntimeStateStore(tmp_path / "independent.json").load().pid == (
        current_pid
    )
    direct.cleanup()
    independent.cleanup()


def test_factory_fails_safe_before_mutex_when_both_sid_paths_fail(
    monkeypatch,
    tmp_path,
):
    class Inspector:
        def current_user_sid(self):
            raise OSError("SID unavailable")

        def inspect(self, _pid):
            return None

    monkeypatch.setattr(runtime, "Win32ProcessInspector", Inspector)
    monkeypatch.setattr(
        runtime,
        "Win32NamedMutex",
        lambda _name: pytest.fail("mutex must not be created without a SID"),
    )

    with pytest.raises(
        runtime.DesktopInstanceError,
        match="validate current process ownership",
    ):
        runtime.create_desktop_instance(tmp_path / "runtime.json", {})


@pytest.mark.parametrize("wait_result", [0, 0x80])
def test_named_mutex_owns_abandoned_or_signaled_handle_and_balances_close(wait_result):
    calls = []
    api = SimpleNamespace(
        CreateMutexW=lambda *_args: 55,
        WaitForSingleObject=lambda handle, timeout: (
            calls.append(("wait", handle, timeout)) or wait_result
        ),
        ReleaseMutex=lambda handle: calls.append(("release", handle)) or True,
        CloseHandle=lambda handle: calls.append(("close", handle)) or True,
    )
    mutex = runtime.Win32NamedMutex("Global\\test", kernel32=api)

    assert mutex.acquire() is True
    mutex.close()
    mutex.close()

    assert calls == [("wait", 55, 0), ("release", 55), ("close", 55)]


def test_owner_publishes_environment_and_explicit_cleanup(tmp_path):
    env = {}
    mutex = FakeMutex([True])
    coordinator = make_coordinator(tmp_path, mutex=mutex, env=env)

    assert coordinator.coordinate().role is runtime.InstanceRole.OWNER
    state = coordinator.publish(port=8766, application_version="v2")

    assert state == make_state(port=8766, application_version="v2")
    assert runtime.RuntimeStateStore(tmp_path / "runtime.json").load() == state
    assert env[contract.INSTANCE_TOKEN_ENV] == TOKEN
    assert env[contract.INSTANCE_PID_ENV] == str(PID)
    assert env[contract.INSTANCE_START_TIME_ENV] == str(START_TIME)
    assert env[contract.INSTANCE_VERSION_ENV] == "v2"
    assert env["WEB_PORT"] == "8766"

    coordinator.cleanup()
    coordinator.cleanup()

    assert not (tmp_path / "runtime.json").exists()
    assert contract.INSTANCE_TOKEN_ENV not in env
    assert mutex.release_calls == 1
    assert mutex.closed is True


def test_explicit_owner_cleanup_does_not_remove_unverifiable_runtime_state(tmp_path):
    coordinator = make_coordinator(tmp_path)
    coordinator.coordinate()
    coordinator.publish(port=8765, application_version="v1")
    (tmp_path / "runtime.json").write_text("{malformed", encoding="utf-8")

    coordinator.cleanup()

    assert (tmp_path / "runtime.json").read_text(encoding="utf-8") == "{malformed"


def test_owner_cleanup_does_not_remove_newer_owner_state(tmp_path):
    coordinator = make_coordinator(tmp_path)
    coordinator.coordinate()
    coordinator.publish(port=8765, application_version="v1")
    store = runtime.RuntimeStateStore(tmp_path / "runtime.json")
    newer_state = make_state(instance_token=OTHER_TOKEN)
    store.replace(newer_state)

    coordinator.cleanup()

    assert store.load() == newer_state


def test_owner_that_never_published_does_not_remove_later_runtime_state(tmp_path):
    coordinator = make_coordinator(tmp_path)
    coordinator.coordinate()
    later_state = make_state(instance_token=OTHER_TOKEN)
    runtime.RuntimeStateStore(tmp_path / "runtime.json").replace(later_state)

    coordinator.cleanup()

    assert runtime.RuntimeStateStore(tmp_path / "runtime.json").load() == later_state


def test_follower_reuses_only_fully_validated_runtime_state(tmp_path):
    store = runtime.RuntimeStateStore(tmp_path / "runtime.json")
    state = make_state(port=8770)
    store.replace(state)
    mutex = FakeMutex([False])
    inspector = FakeInspector(
        {PID: runtime.ProcessIdentity(PID, OWNER, START_TIME)}
    )
    probes = []
    coordinator = make_coordinator(
        tmp_path,
        mutex=mutex,
        inspector=inspector,
        endpoint_probe=lambda observed: probes.append(observed) or True,
    )

    decision = coordinator.coordinate(wait_seconds=0)

    assert decision == runtime.InstanceDecision(runtime.InstanceRole.FOLLOWER, 8770)
    assert probes == [state]
    assert mutex.closed is True


def test_follower_cleanup_preserves_owner_runtime_state(tmp_path):
    store = runtime.RuntimeStateStore(tmp_path / "runtime.json")
    state = make_state(port=8770)
    store.replace(state)
    coordinator = make_coordinator(
        tmp_path,
        mutex=FakeMutex([False]),
        inspector=FakeInspector(
            {PID: runtime.ProcessIdentity(PID, OWNER, START_TIME)}
        ),
    )

    assert coordinator.coordinate(wait_seconds=0).role is runtime.InstanceRole.FOLLOWER
    coordinator.cleanup()

    assert store.load() == state


def test_owner_coordination_raises_desktop_instance_error_for_unverified_self(
    tmp_path,
):
    mutex = FakeMutex([True])
    coordinator = make_coordinator(
        tmp_path,
        mutex=mutex,
        inspector=FakeInspector({}),
    )

    with pytest.raises(
        runtime.DesktopInstanceError,
        match="validate desktop owner process",
    ):
        coordinator.coordinate()
    assert mutex.closed is True
    assert mutex.release_calls == 1


def test_owner_setup_remove_failure_releases_mutex_for_immediate_competitor(
    tmp_path,
):
    shared = SimpleNamespace(held=False)

    class SharedMutex:
        def __init__(self):
            self.owned = False
            self.closed = False

        def acquire(self, _timeout_milliseconds=0):
            if shared.held:
                return False
            shared.held = True
            self.owned = True
            return True

        def release(self):
            if self.owned:
                shared.held = False
                self.owned = False

        def close(self):
            self.release()
            self.closed = True

    class FailingStore(runtime.RuntimeStateStore):
        def remove(self, *, expected_token=None):
            del expected_token
            raise runtime.RuntimeStateError("injected remove failure")

    first_mutex = SharedMutex()
    first = runtime.DesktopInstance(
        store=FailingStore(tmp_path / "runtime.json"),
        mutex=first_mutex,
        inspector=FakeInspector(
            {PID: runtime.ProcessIdentity(PID, OWNER, START_TIME)}
        ),
        current_user_id=OWNER,
        env={},
        current_pid=PID,
    )

    with pytest.raises(runtime.RuntimeStateError, match="injected remove failure"):
        first.coordinate(wait_seconds=10)

    assert first_mutex.closed is True
    assert shared.held is False

    second = make_coordinator(
        tmp_path,
        mutex=SharedMutex(),
        sleep=lambda _seconds: pytest.fail("competitor must not enter wait loop"),
    )
    assert second.coordinate(wait_seconds=10).role is runtime.InstanceRole.OWNER
    second.cleanup()


@pytest.mark.parametrize(
    ("observed_identity", "endpoint_valid"),
    [
        (None, True),
        (runtime.ProcessIdentity(PID, "S-1-5-21-OTHER", START_TIME), True),
        (runtime.ProcessIdentity(PID, OWNER, START_TIME + 1), True),
        (runtime.ProcessIdentity(PID, OWNER, START_TIME), False),
    ],
)
def test_dead_reused_foreign_or_wrong_token_runtime_is_rejected(
    tmp_path,
    observed_identity,
    endpoint_valid,
):
    runtime.RuntimeStateStore(tmp_path / "runtime.json").replace(make_state())
    clock = [0.0]

    def advance(seconds):
        clock[0] += seconds

    coordinator = make_coordinator(
        tmp_path,
        mutex=FakeMutex([False, False, False]),
        inspector=FakeInspector(
            {PID: observed_identity} if observed_identity is not None else {}
        ),
        endpoint_probe=lambda state: endpoint_valid,
        monotonic=lambda: clock[0],
        sleep=advance,
    )

    with pytest.raises(runtime.InstanceUnavailableError):
        coordinator.coordinate(wait_seconds=0.02, poll_seconds=0.01)


def test_stale_or_malformed_state_is_cleaned_during_takeover(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text("{malformed", encoding="utf-8")
    mutex = FakeMutex([False, True])
    clock = [0.0]
    coordinator = make_coordinator(
        tmp_path,
        mutex=mutex,
        monotonic=lambda: clock[0],
        sleep=lambda seconds: clock.__setitem__(0, clock[0] + seconds),
    )

    decision = coordinator.coordinate(wait_seconds=1, poll_seconds=0.01)

    assert decision.role is runtime.InstanceRole.OWNER
    assert not path.exists()
    coordinator.cleanup()


def test_coordination_wait_is_capped_at_ten_seconds(tmp_path):
    clock = [0.0]
    sleeps = []

    def advance(seconds):
        sleeps.append(seconds)
        clock[0] += seconds

    coordinator = make_coordinator(
        tmp_path,
        mutex=FakeMutex([]),
        monotonic=lambda: clock[0],
        sleep=advance,
    )

    with pytest.raises(runtime.InstanceUnavailableError):
        coordinator.coordinate(wait_seconds=30, poll_seconds=6)

    assert clock == [10.0]
    assert sleeps == [6, 4.0]


def test_probe_sends_token_and_requires_exact_runtime_payload():
    state = make_state()
    requests = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            payload = {"status": "ok", **state.to_mapping()}
            return json.dumps(payload).encode("utf-8")

    def urlopen(request, timeout):
        requests.append((request, timeout))
        return Response()

    assert runtime.probe_runtime_endpoint(
        state,
        opener=SimpleNamespace(open=urlopen),
    ) is True
    request, timeout = requests[0]
    assert request.full_url == "http://127.0.0.1:8765/desktop-runtime"
    assert request.get_header("Authorization") == f"Bearer {TOKEN}"
    assert timeout == 0.75


def test_probe_builds_proxyless_opener_even_with_proxy_environment(
    monkeypatch,
):
    state = make_state()
    calls = []

    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(
                {"status": "ok", **state.to_mapping()}
            ).encode("utf-8")

    class Opener:
        def open(self, request, timeout):
            calls.append(("open", request.full_url, timeout))
            return Response()

    def proxy_handler(proxies):
        calls.append(("proxy_handler", proxies))
        return "proxy-handler"

    def build_opener(*handlers):
        calls.append(("build_opener", handlers))
        return Opener()

    monkeypatch.setenv("HTTP_PROXY", "http://192.0.2.1:8080")
    monkeypatch.setenv("ALL_PROXY", "http://192.0.2.2:8080")
    monkeypatch.setattr(runtime.urllib.request, "ProxyHandler", proxy_handler)
    monkeypatch.setattr(runtime.urllib.request, "build_opener", build_opener)

    assert runtime.probe_runtime_endpoint(state) is True
    assert calls[:1] == [("proxy_handler", {})]
    assert calls[1][0] == "build_opener"
    assert calls[1][1][0] == "proxy-handler"
    assert isinstance(calls[1][1][1], runtime._NoRedirectHandler)
    assert calls[2:] == [
        ("open", "http://127.0.0.1:8765/desktop-runtime", 0.75),
    ]


def test_proxyless_probe_refuses_non_loopback_redirect_without_following():
    requests = []

    class RedirectTransport(urllib.request.HTTPHandler):
        def http_open(self, request):
            requests.append(
                (request.full_url, request.get_header("Authorization"))
            )
            if request.full_url != "http://127.0.0.1:8765/desktop-runtime":
                pytest.fail("runtime probe followed a redirect off loopback")
            headers = email.message.Message()
            headers["Location"] = "http://192.0.2.1/token-capture"
            response = urllib.response.addinfourl(
                io.BytesIO(b""),
                headers,
                request.full_url,
                code=302,
            )
            response.msg = "Found"
            return response

    state = make_state()
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        runtime._NoRedirectHandler(),
        RedirectTransport(),
    )
    assert runtime.probe_runtime_endpoint(state, opener=opener) is False
    assert requests == [
        (
            "http://127.0.0.1:8765/desktop-runtime",
            f"Bearer {state.instance_token}",
        ),
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"status": "ok", "version": "v1.2.3"},
        {"status": "ok", **make_state(instance_token=OTHER_TOKEN).to_mapping()},
        {"status": "ok", **make_state(process_start_time=START_TIME + 1).to_mapping()},
        ["not", "an", "object"],
    ],
)
def test_probe_rejects_health_lookalikes_and_identity_mismatches(payload):
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, _limit):
            return json.dumps(payload).encode("utf-8")

    assert runtime.probe_runtime_endpoint(
        make_state(),
        opener=SimpleNamespace(open=lambda *_args, **_kwargs: Response()),
    ) is False


def test_parallel_coordination_produces_one_owner_and_one_follower(tmp_path):
    class SharedState:
        def __init__(self):
            self.lock = threading.Lock()
            self.held = False

    class SharedMutex:
        def __init__(self, shared):
            self.shared = shared
            self.owned = False
            self.closed = False

        def acquire(self, _timeout=0):
            with self.shared.lock:
                if self.shared.held:
                    return False
                self.shared.held = True
                self.owned = True
                return True

        def release(self):
            with self.shared.lock:
                if self.owned:
                    self.shared.held = False
                    self.owned = False

        def close(self):
            self.release()
            self.closed = True

    shared = SharedState()
    store = runtime.RuntimeStateStore(tmp_path / "runtime.json")
    inspector = FakeInspector(
        {PID: runtime.ProcessIdentity(PID, OWNER, START_TIME)}
    )
    barrier = threading.Barrier(2)
    owner_done = threading.Event()
    results = []
    errors = []

    def worker(token):
        clock = [0.0]
        coordinator = runtime.DesktopInstance(
            store=store,
            mutex=SharedMutex(shared),
            inspector=inspector,
            current_user_id=OWNER,
            env={},
            current_pid=PID,
            token_factory=lambda: token,
            endpoint_probe=lambda state: store.load() == state,
            monotonic=lambda: clock[0],
            sleep=lambda seconds: (
                clock.__setitem__(0, clock[0] + seconds),
                threading.Event().wait(0.001),
            ),
        )
        try:
            barrier.wait()
            decision = coordinator.coordinate(wait_seconds=2, poll_seconds=0.01)
            results.append(decision.role)
            if decision.role is runtime.InstanceRole.OWNER:
                coordinator.publish(port=8765, application_version="v1")
                owner_done.wait(2)
                coordinator.cleanup()
            else:
                owner_done.set()
        except Exception as exc:
            errors.append(exc)
            owner_done.set()

    first = threading.Thread(target=worker, args=(TOKEN,))
    second = threading.Thread(target=worker, args=(OTHER_TOKEN,))
    first.start()
    second.start()
    first.join(timeout=3)
    second.join(timeout=3)

    assert errors == []
    assert sorted(results) == [
        runtime.InstanceRole.FOLLOWER,
        runtime.InstanceRole.OWNER,
    ]
