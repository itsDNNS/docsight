"""Windows identity and named-mutex adapters for desktop coordination."""

from __future__ import annotations

import hashlib
import queue
import sys
import threading
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ProcessIdentity:
    """OS identity needed to reject dead, reused, or foreign processes."""

    pid: int
    owner_id: str
    start_time: int


class ProcessInspector(Protocol):
    def inspect(self, pid: int) -> ProcessIdentity | None:
        """Return process identity, or None when it cannot be safely inspected."""


class MutexHandle(Protocol):
    def acquire(self, timeout_milliseconds: int = 0) -> bool:
        """Acquire ownership, including an abandoned mutex, within the timeout."""

    def release(self) -> None:
        """Release owned mutex state."""

    def close(self) -> None:
        """Release ownership and close the underlying handle."""


def mutex_name_for_user(user_identity: str) -> str:
    """Return a machine-visible, per-user mutex name safe for Windows objects."""
    digest = hashlib.sha256(user_identity.encode("utf-8")).hexdigest()
    return rf"Global\DOCSight.Desktop.{digest}"


class Win32ProcessInspector:
    """Inspect Windows process owner SID and creation FILETIME via ctypes."""

    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    TOKEN_QUERY = 0x0008
    TOKEN_USER = 1

    def __init__(self, *, kernel32: Any | None = None, advapi32: Any | None = None) -> None:
        if sys.platform != "win32" and (kernel32 is None or advapi32 is None):
            raise OSError("Windows process inspection is unavailable")
        configure_prototypes = kernel32 is None or advapi32 is None
        if kernel32 is None or advapi32 is None:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
        self._kernel32 = kernel32
        self._advapi32 = advapi32
        if configure_prototypes:
            self._configure_prototypes()

    def _configure_prototypes(self) -> None:
        import ctypes
        from ctypes import wintypes

        self._kernel32.GetCurrentProcess.argtypes = ()
        self._kernel32.GetCurrentProcess.restype = wintypes.HANDLE
        self._kernel32.OpenProcess.argtypes = (
            wintypes.DWORD,
            wintypes.BOOL,
            wintypes.DWORD,
        )
        self._kernel32.OpenProcess.restype = wintypes.HANDLE
        self._kernel32.GetProcessTimes.argtypes = (
            wintypes.HANDLE,
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
            ctypes.POINTER(wintypes.FILETIME),
        )
        self._kernel32.GetProcessTimes.restype = wintypes.BOOL
        self._kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
        self._kernel32.CloseHandle.restype = wintypes.BOOL
        self._kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
        self._kernel32.LocalFree.restype = wintypes.HLOCAL
        self._advapi32.OpenProcessToken.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.HANDLE),
        )
        self._advapi32.OpenProcessToken.restype = wintypes.BOOL
        self._advapi32.GetTokenInformation.argtypes = (
            wintypes.HANDLE,
            wintypes.DWORD,
            wintypes.LPVOID,
            wintypes.DWORD,
            ctypes.POINTER(wintypes.DWORD),
        )
        self._advapi32.GetTokenInformation.restype = wintypes.BOOL
        self._advapi32.ConvertSidToStringSidW.argtypes = (
            ctypes.c_void_p,
            ctypes.POINTER(wintypes.LPWSTR),
        )
        self._advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL

    def current_user_sid(self) -> str:
        return self._process_owner_sid(self._kernel32.GetCurrentProcess())

    def inspect(self, pid: int) -> ProcessIdentity | None:
        import ctypes
        from ctypes import wintypes

        handle = self._kernel32.OpenProcess(
            self.PROCESS_QUERY_LIMITED_INFORMATION,
            False,
            pid,
        )
        if not handle:
            return None
        try:
            creation = wintypes.FILETIME()
            exit_time = wintypes.FILETIME()
            kernel_time = wintypes.FILETIME()
            user_time = wintypes.FILETIME()
            if not self._kernel32.GetProcessTimes(
                handle,
                ctypes.byref(creation),
                ctypes.byref(exit_time),
                ctypes.byref(kernel_time),
                ctypes.byref(user_time),
            ):
                return None
            start_time = (int(creation.dwHighDateTime) << 32) | int(
                creation.dwLowDateTime
            )
            try:
                owner_id = self._process_owner_sid(handle)
            except OSError:
                return None
            return ProcessIdentity(pid=pid, owner_id=owner_id, start_time=start_time)
        finally:
            self._kernel32.CloseHandle(handle)

    def _process_owner_sid(self, process_handle: Any) -> str:
        import ctypes
        from ctypes import wintypes

        token = wintypes.HANDLE()
        if not self._advapi32.OpenProcessToken(
            process_handle,
            self.TOKEN_QUERY,
            ctypes.byref(token),
        ):
            raise OSError("unable to open process token")
        try:
            required = wintypes.DWORD()
            self._advapi32.GetTokenInformation(
                token,
                self.TOKEN_USER,
                None,
                0,
                ctypes.byref(required),
            )
            if required.value == 0:
                raise OSError("unable to size process token")
            buffer = ctypes.create_string_buffer(required.value)
            if not self._advapi32.GetTokenInformation(
                token,
                self.TOKEN_USER,
                buffer,
                required,
                ctypes.byref(required),
            ):
                raise OSError("unable to read process token")
            sid_pointer = ctypes.cast(
                buffer,
                ctypes.POINTER(ctypes.c_void_p),
            ).contents.value
            sid_text = wintypes.LPWSTR()
            if not self._advapi32.ConvertSidToStringSidW(
                sid_pointer,
                ctypes.byref(sid_text),
            ):
                raise OSError("unable to format process SID")
            try:
                return str(sid_text.value)
            finally:
                self._kernel32.LocalFree(sid_text)
        finally:
            self._kernel32.CloseHandle(token)


@dataclass
class _MutexCommand:
    operation: str
    timeout_milliseconds: int = 0
    completed: threading.Event = field(default_factory=threading.Event)
    result: bool | None = None
    error: Exception | None = None


class Win32NamedMutex:
    """Named mutex whose ownership is parked on one dedicated OS thread."""

    COMMAND_TIMEOUT_SECONDS = 5.0
    WAIT_OBJECT_0 = 0
    WAIT_ABANDONED = 0x80
    WAIT_TIMEOUT = 0x102

    def __init__(
        self,
        name: str,
        *,
        kernel32: Any | None = None,
        command_timeout_seconds: float = COMMAND_TIMEOUT_SECONDS,
    ) -> None:
        if sys.platform != "win32" and kernel32 is None:
            raise OSError("Windows named mutexes are unavailable")
        configure_prototypes = kernel32 is None
        if kernel32 is None:
            import ctypes

            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        if configure_prototypes:
            from ctypes import wintypes

            kernel32.CreateMutexW.argtypes = (
                wintypes.LPVOID,
                wintypes.BOOL,
                wintypes.LPCWSTR,
            )
            kernel32.CreateMutexW.restype = wintypes.HANDLE
            kernel32.WaitForSingleObject.argtypes = (
                wintypes.HANDLE,
                wintypes.DWORD,
            )
            kernel32.WaitForSingleObject.restype = wintypes.DWORD
            kernel32.ReleaseMutex.argtypes = (wintypes.HANDLE,)
            kernel32.ReleaseMutex.restype = wintypes.BOOL
            kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
            kernel32.CloseHandle.restype = wintypes.BOOL

        self._kernel32 = kernel32
        self._name = name
        self._commands: queue.Queue[_MutexCommand] = queue.Queue()
        self._ready = threading.Event()
        self._startup_error: Exception | None = None
        self._command_timeout_seconds = max(0.0, command_timeout_seconds)
        self._closed = False
        self._call_lock = threading.Lock()
        self._thread = threading.Thread(
            target=self._ownership_loop,
            name="docsight-mutex-owner",
            daemon=True,
        )
        self._thread.start()
        if not self._ready.wait(self.COMMAND_TIMEOUT_SECONDS):
            raise TimeoutError("desktop mutex ownership thread did not initialize")
        if self._startup_error is not None:
            self._thread.join()
            raise self._startup_error

    def acquire(self, timeout_milliseconds: int = 0) -> bool:
        command = self._submit(
            _MutexCommand(
                "acquire",
                timeout_milliseconds=max(0, timeout_milliseconds),
            )
        )
        return bool(command.result)

    def release(self) -> None:
        with self._call_lock:
            if self._closed:
                return
            command = _MutexCommand("release")
            self._commands.put(command)
            self._wait_for_command(command)
        if command.error is not None:
            raise command.error

    def close(self) -> None:
        wait_error: Exception | None = None
        with self._call_lock:
            if self._closed:
                return
            command = _MutexCommand("close")
            self._commands.put(command)
            try:
                self._wait_for_command(command)
            except Exception as exc:
                wait_error = exc
            finally:
                self._closed = True
        self._thread.join(timeout=0)
        if wait_error is not None:
            raise wait_error
        if command.error is not None:
            raise command.error

    def _submit(self, command: _MutexCommand) -> _MutexCommand:
        with self._call_lock:
            if self._closed:
                raise RuntimeError("desktop ownership mutex is closed")
            self._commands.put(command)
            self._wait_for_command(command)
        if command.error is not None:
            raise command.error
        return command

    def _wait_for_command(self, command: _MutexCommand) -> None:
        if command.completed.is_set():
            return
        if not self._thread.is_alive():
            raise RuntimeError("desktop mutex ownership thread stopped unexpectedly")
        if command.completed.wait(self._command_timeout_seconds):
            return
        if not self._thread.is_alive():
            raise RuntimeError("desktop mutex ownership thread stopped unexpectedly")
        raise TimeoutError(
            f"desktop mutex {command.operation} command timed out"
        )

    def _ownership_loop(self) -> None:
        try:
            handle = self._kernel32.CreateMutexW(None, False, self._name)
            if not handle:
                raise OSError("unable to create desktop ownership mutex")
        except Exception as exc:
            self._startup_error = exc
            self._ready.set()
            return

        owned = False
        self._ready.set()
        while True:
            command = self._commands.get()
            should_exit = False
            try:
                if command.operation == "acquire":
                    if owned:
                        command.result = True
                    else:
                        result = int(
                            self._kernel32.WaitForSingleObject(
                                handle,
                                command.timeout_milliseconds,
                            )
                        )
                        if result in (self.WAIT_OBJECT_0, self.WAIT_ABANDONED):
                            owned = True
                            command.result = True
                        elif result == self.WAIT_TIMEOUT:
                            command.result = False
                        else:
                            raise OSError(
                                "unable to wait for desktop ownership mutex"
                            )
                elif command.operation == "release":
                    if owned:
                        if not self._kernel32.ReleaseMutex(handle):
                            raise OSError(
                                "unable to release desktop ownership mutex"
                            )
                        owned = False
                elif command.operation == "close":
                    release_error: Exception | None = None
                    if owned:
                        try:
                            if not self._kernel32.ReleaseMutex(handle):
                                raise OSError(
                                    "unable to release desktop ownership mutex"
                                )
                            owned = False
                        except Exception as exc:
                            release_error = exc
                    try:
                        if not self._kernel32.CloseHandle(handle):
                            raise OSError(
                                "unable to close desktop ownership mutex"
                            )
                    except Exception as exc:
                        if release_error is None:
                            release_error = exc
                    if release_error is not None:
                        raise release_error
                    should_exit = True
                else:
                    raise RuntimeError("unknown desktop mutex command")
            except BaseException as exc:
                if isinstance(exc, Exception):
                    command.error = exc
                else:
                    command.error = RuntimeError(
                        "desktop mutex ownership thread stopped unexpectedly"
                    )
                    command.error.__cause__ = exc
                    should_exit = True
                if command.operation == "close":
                    should_exit = True
            finally:
                command.completed.set()
            if should_exit:
                return
