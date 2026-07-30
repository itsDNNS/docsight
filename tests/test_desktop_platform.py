"""Focused tests for the Windows identity and mutex platform adapter."""

from __future__ import annotations

import importlib
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
WINDOWS_DIR = ROOT / "packaging" / "windows"
if str(WINDOWS_DIR) not in sys.path:
    sys.path.insert(0, str(WINDOWS_DIR))

platform_adapter = importlib.import_module("desktop_platform")


@pytest.mark.parametrize("wait_result", [0, 0x80])
def test_named_mutex_parks_wait_release_and_close_on_one_thread(wait_result):
    api_calls = []
    caller_threads = []

    def record(name, result):
        def call(*args):
            api_calls.append((name, threading.get_ident(), args))
            return result

        return call

    api = SimpleNamespace(
        CreateMutexW=record("create", 55),
        WaitForSingleObject=record("wait", wait_result),
        ReleaseMutex=record("release", True),
        CloseHandle=record("close", True),
    )
    mutex = platform_adapter.Win32NamedMutex("Global\\test", kernel32=api)

    def acquire_from_startup_worker():
        caller_threads.append(threading.get_ident())
        assert mutex.acquire() is True

    worker = threading.Thread(target=acquire_from_startup_worker)
    worker.start()
    worker.join()
    caller_threads.append(threading.get_ident())
    mutex.close()

    ownership_calls = [
        call for call in api_calls if call[0] in {"wait", "release", "close"}
    ]
    assert [call[0] for call in ownership_calls] == ["wait", "release", "close"]
    assert len({call[1] for call in ownership_calls}) == 1
    assert ownership_calls[0][1] not in caller_threads


def test_named_mutex_release_and_reacquire_are_safe_from_retry_thread():
    api_calls = []
    api = SimpleNamespace(
        CreateMutexW=lambda *_args: 55,
        WaitForSingleObject=lambda *_args: (
            api_calls.append(("wait", threading.get_ident())) or 0
        ),
        ReleaseMutex=lambda *_args: (
            api_calls.append(("release", threading.get_ident())) or True
        ),
        CloseHandle=lambda *_args: (
            api_calls.append(("close", threading.get_ident())) or True
        ),
    )
    mutex = platform_adapter.Win32NamedMutex("Global\\test", kernel32=api)
    assert mutex.acquire()
    retry_caller = []

    def retry():
        retry_caller.append(threading.get_ident())
        mutex.release()
        assert mutex.acquire()

    worker = threading.Thread(target=retry)
    worker.start()
    worker.join()
    mutex.close()

    assert [name for name, _thread_id in api_calls] == [
        "wait",
        "release",
        "wait",
        "release",
        "close",
    ]
    assert len({thread_id for _name, thread_id in api_calls}) == 1
    assert api_calls[0][1] != retry_caller[0]


def test_named_mutex_timeout_does_not_release_unowned_handle():
    calls = []
    api = SimpleNamespace(
        CreateMutexW=lambda *_args: 55,
        WaitForSingleObject=lambda *_args: 0x102,
        ReleaseMutex=lambda *_args: calls.append("release") or True,
        CloseHandle=lambda *_args: calls.append("close") or True,
    )
    mutex = platform_adapter.Win32NamedMutex("Global\\test", kernel32=api)

    assert mutex.acquire(25) is False
    mutex.close()

    assert calls == ["close"]


def test_named_mutex_acquire_fails_boundedly_when_owner_thread_stalls():
    entered = threading.Event()
    resume = threading.Event()
    finished = threading.Event()

    def stalled_wait(*_args):
        entered.set()
        assert resume.wait(timeout=1)
        finished.set()
        return 0

    api = SimpleNamespace(
        CreateMutexW=lambda *_args: 55,
        WaitForSingleObject=stalled_wait,
        ReleaseMutex=lambda *_args: True,
        CloseHandle=lambda *_args: True,
    )
    mutex = platform_adapter.Win32NamedMutex(
        "Global\\test",
        kernel32=api,
        command_timeout_seconds=0.01,
    )

    with pytest.raises(TimeoutError, match="acquire"):
        mutex.acquire()

    assert entered.is_set()
    resume.set()
    assert finished.wait(timeout=1)
    mutex._command_timeout_seconds = 1
    mutex.close()


def test_named_mutex_worker_death_fails_commands_and_close_is_idempotent():
    api = SimpleNamespace(
        CreateMutexW=lambda *_args: 55,
        WaitForSingleObject=lambda *_args: (_ for _ in ()).throw(SystemExit()),
        ReleaseMutex=lambda *_args: True,
        CloseHandle=lambda *_args: True,
    )
    mutex = platform_adapter.Win32NamedMutex("Global\\test", kernel32=api)

    with pytest.raises(RuntimeError, match="ownership thread stopped"):
        mutex.acquire()
    mutex._thread.join(timeout=1)
    assert not mutex._thread.is_alive()

    with pytest.raises(RuntimeError, match="ownership thread stopped"):
        mutex.release()
    with pytest.raises(RuntimeError, match="ownership thread stopped"):
        mutex.close()
    mutex.close()


def test_process_inspector_uses_limited_query_and_closes_process_handle(
    monkeypatch,
):
    calls = []

    class Kernel32:
        def OpenProcess(self, access, inherit, pid):
            calls.append(("open", access, inherit, pid))
            return 77

        def GetProcessTimes(
            self,
            handle,
            creation,
            _exit_time,
            _kernel_time,
            _user_time,
        ):
            calls.append(("times", handle))
            creation._obj.dwLowDateTime = 0x89ABCDEF
            creation._obj.dwHighDateTime = 0x01234567
            return True

        def CloseHandle(self, handle):
            calls.append(("close", handle))
            return True

    inspector = platform_adapter.Win32ProcessInspector(
        kernel32=Kernel32(),
        advapi32=object(),
    )
    monkeypatch.setattr(inspector, "_process_owner_sid", lambda handle: "S-1-test")

    identity = inspector.inspect(4242)

    assert identity == platform_adapter.ProcessIdentity(
        4242,
        "S-1-test",
        0x0123456789ABCDEF,
    )
    assert calls == [
        (
            "open",
            platform_adapter.Win32ProcessInspector.PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            4242,
        ),
        ("times", 77),
        ("close", 77),
    ]


def test_process_inspector_closes_handle_when_process_times_are_unavailable():
    calls = []
    kernel32 = SimpleNamespace(
        OpenProcess=lambda *_args: 77,
        GetProcessTimes=lambda *_args: False,
        CloseHandle=lambda handle: calls.append(handle) or True,
    )
    inspector = platform_adapter.Win32ProcessInspector(
        kernel32=kernel32,
        advapi32=object(),
    )

    assert inspector.inspect(4242) is None
    assert calls == [77]
