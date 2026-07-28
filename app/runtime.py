"""Thread-safe ownership of the collector polling runtime."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from types import ModuleType

from . import web

log = logging.getLogger("docsis.runtime")


@dataclass
class _PollingAttempt:
    """One attributed polling invocation and its explicit completion outcome."""

    generation: int
    sequence: int
    stop_event: threading.Event
    done_event: threading.Event
    thread: threading.Thread | None = None
    outcome: str = "running"
    failure_type: str | None = None
    slow_stop_logged: bool = False


class RuntimeController:
    """Apply configuration changes and own exactly one polling thread."""

    DEFAULT_RESTART_INITIAL_DELAY = 0.25
    DEFAULT_RESTART_MAX_DELAY = 5.0
    DEFAULT_RESTART_MAX_FAILURES = 5

    def __init__(
        self,
        config_manager,
        storage,
        polling_target: Callable,
        *,
        web_module: ModuleType = web,
        stop_timeout: float = 10,
        restart_initial_delay: float = DEFAULT_RESTART_INITIAL_DELAY,
        restart_max_delay: float = DEFAULT_RESTART_MAX_DELAY,
        restart_max_failures: int = DEFAULT_RESTART_MAX_FAILURES,
    ):
        if stop_timeout <= 0:
            raise ValueError("stop_timeout must be positive")
        if restart_initial_delay < 0:
            raise ValueError("restart_initial_delay must not be negative")
        if restart_max_delay < restart_initial_delay:
            raise ValueError(
                "restart_max_delay must be at least restart_initial_delay"
            )
        if restart_max_failures < 1:
            raise ValueError("restart_max_failures must be at least one")

        self.config_manager = config_manager
        self.storage = storage
        self.polling_target = polling_target
        self.web = web_module
        self.stop_timeout = stop_timeout
        self.restart_initial_delay = restart_initial_delay
        self.restart_max_delay = restart_max_delay
        self.restart_max_failures = restart_max_failures

        # Route-level mutations acquire this lock before entering runtime state.
        # Runtime watcher code never acquires it, preserving Transaction -> State.
        self.transaction_lock = threading.RLock()
        self._state_lock = threading.RLock()
        self._state_changed = threading.Condition(self._state_lock)

        self._attempt: _PollingAttempt | None = None
        # Keep the legacy private attributes as observable ownership references.
        self._poll_thread: threading.Thread | None = None
        self._poll_stop: threading.Event | None = None
        self._poll_done: threading.Event | None = None
        self._handoff_thread: threading.Thread | None = None
        self._desired_running = False
        self._generation = 0
        self._attempt_sequence = 0
        self._shutting_down = False
        self._consecutive_failures = 0
        self._restart_exhausted = False
        self._last_poll_outcome: str | None = None
        self._last_failure_type: str | None = None
        self._watch_interval = min(stop_timeout, 0.1)

    @property
    def is_running(self) -> bool:
        with self._state_lock:
            return bool(self._poll_thread and self._poll_thread.is_alive())

    @property
    def desired_running(self) -> bool:
        with self._state_lock:
            return self._desired_running

    @property
    def generation(self) -> int:
        with self._state_lock:
            return self._generation

    def _clear_web_state_locked(self) -> None:
        self.web.init_collector(None)
        self.web.init_collectors([])
        self.web.reset_modem_state()

    def _reset_failure_budget_locked(self) -> None:
        self._consecutive_failures = 0
        self._restart_exhausted = False
        self._last_poll_outcome = None
        self._last_failure_type = None

    def _run_polling(self, attempt: _PollingAttempt) -> None:
        outcome = "running"
        failure_type = None
        try:
            self.polling_target(
                self.config_manager,
                self.storage,
                attempt.stop_event,
            )
            outcome = (
                "stopped"
                if attempt.stop_event.is_set()
                else "unexpected_exit"
            )
        except BaseException as exc:
            outcome = (
                "stopped"
                if attempt.stop_event.is_set()
                else "failed"
            )
            if outcome == "failed":
                failure_type = type(exc).__name__
        finally:
            with self._state_changed:
                attempt.outcome = outcome
                attempt.failure_type = failure_type
                attempt.done_event.set()
                self._state_changed.notify_all()

        if outcome == "failed":
            # Deliberately omit exception text and traceback: driver errors can
            # contain credentials or URLs, and retries are already bounded.
            log.warning(
                "Polling attempt %d ended unexpectedly (%s)",
                attempt.sequence,
                failure_type,
            )
        elif outcome == "unexpected_exit":
            log.warning(
                "Polling attempt %d returned unexpectedly",
                attempt.sequence,
            )

    def _start_thread_locked(self) -> None:
        """Start one poll and ensure the single watcher owns its handoffs."""
        if self._attempt is not None:
            return

        self._attempt_sequence += 1
        attempt = _PollingAttempt(
            generation=self._generation,
            sequence=self._attempt_sequence,
            stop_event=threading.Event(),
            done_event=threading.Event(),
        )
        thread = threading.Thread(
            target=self._run_polling,
            args=(attempt,),
            daemon=True,
            name=f"docsight-polling-{attempt.sequence}",
        )
        attempt.thread = thread
        self._attempt = attempt
        self._poll_stop = attempt.stop_event
        self._poll_done = attempt.done_event
        self._poll_thread = thread
        thread.start()
        self._ensure_handoff_locked()
        self._state_changed.notify_all()
        log.info(
            "Polling loop started for runtime generation %d (attempt %d)",
            self._generation,
            attempt.sequence,
        )

    def _ensure_handoff_locked(self) -> None:
        if self._handoff_thread and self._handoff_thread.is_alive():
            return
        watcher = threading.Thread(
            target=self._handoff_loop,
            daemon=True,
            name="docsight-runtime-handoff",
        )
        self._handoff_thread = watcher
        watcher.start()

    def _finish_handoff_locked(
        self,
        current_watcher: threading.Thread,
    ) -> None:
        if self._handoff_thread is current_watcher:
            self._handoff_thread = None
        self._state_changed.notify_all()

    def _wait_for_attributed_exit(
        self,
        attempt: _PollingAttempt,
    ) -> bool:
        """Observe an attributed predecessor without an unbounded join."""
        thread = attempt.thread
        if thread is None:
            return True

        while thread.is_alive():
            with self._state_changed:
                if not attempt.done_event.is_set():
                    finished = self._state_changed.wait_for(
                        attempt.done_event.is_set,
                        timeout=self.stop_timeout,
                    )
                    if not finished and not attempt.slow_stop_logged:
                        attempt.slow_stop_logged = True
                        log.warning(
                            "Polling attempt %d is still stopping; "
                            "handoff remains attributed",
                            attempt.sequence,
                        )
                    continue

            # done_event is set immediately before the target wrapper returns.
            # The bounded join closes that tiny gap; the condition timeout keeps
            # an abnormal wrapper exit observable without spinning.
            thread.join(timeout=self._watch_interval)
            if thread.is_alive():
                with self._state_changed:
                    self._state_changed.wait(timeout=self._watch_interval)

        return True

    def _handoff_loop(self) -> None:
        """Reconcile actual polling ownership with the latest desired state."""
        current_watcher = threading.current_thread()
        while True:
            with self._state_changed:
                attempt = self._attempt
                if attempt is None:
                    self._finish_handoff_locked(current_watcher)
                    return
                self._state_changed.wait_for(
                    lambda: (
                        attempt.done_event.is_set()
                        or attempt.stop_event.is_set()
                    )
                )

            self._wait_for_attributed_exit(attempt)

            with self._state_changed:
                if self._attempt is not attempt:
                    continue

                self._attempt = None
                self._poll_thread = None
                self._poll_stop = None
                self._poll_done = None
                self._last_poll_outcome = attempt.outcome
                self._clear_web_state_locked()
                self._state_changed.notify_all()

                if not self._desired_running or self._shutting_down:
                    self._finish_handoff_locked(current_watcher)
                    log.info(
                        "Polling loop stopped at runtime generation %d",
                        self._generation,
                    )
                    return

                # A newer explicit start/config request supersedes this result
                # and has already reset the failure budget.
                replaced = attempt.generation != self._generation
                if attempt.outcome == "stopped" or replaced:
                    self._start_thread_locked()
                    continue

                self._consecutive_failures += 1
                self._last_failure_type = (
                    attempt.failure_type or attempt.outcome
                )
                if (
                    self._consecutive_failures
                    >= self.restart_max_failures
                ):
                    self._restart_exhausted = True
                    log.error(
                        "Polling restart budget exhausted after %d "
                        "consecutive failures; explicit start or config "
                        "change required",
                        self._consecutive_failures,
                    )
                    self._finish_handoff_locked(current_watcher)
                    return

                delay = min(
                    self.restart_initial_delay
                    * (2 ** (self._consecutive_failures - 1)),
                    self.restart_max_delay,
                )
                failure_generation = self._generation
                interrupted = self._state_changed.wait_for(
                    lambda: (
                        self._generation != failure_generation
                        or not self._desired_running
                        or self._shutting_down
                        or self._attempt is not None
                    ),
                    timeout=delay,
                )
                if interrupted:
                    if self._attempt is not None:
                        continue
                    if not self._desired_running or self._shutting_down:
                        self._finish_handoff_locked(current_watcher)
                        return
                    # A newer request normally starts synchronously. Retain a
                    # safe reconciliation fallback for future callers.
                    self._start_thread_locked()
                    continue

                self._start_thread_locked()

    def _request_state_locked(
        self,
        desired_running: bool,
        *,
        reset_failure_budget: bool = False,
    ) -> None:
        self._generation += 1
        self._desired_running = desired_running
        if reset_failure_budget:
            self._reset_failure_budget_locked()

        attempt = self._attempt
        if attempt is not None:
            if attempt.thread and attempt.thread.is_alive():
                attempt.stop_event.set()
            self._ensure_handoff_locked()
            self._state_changed.notify_all()
            return

        self._clear_web_state_locked()
        if desired_running:
            self._start_thread_locked()
        else:
            self._state_changed.notify_all()

    def stop_polling(self) -> None:
        """Request a stop without losing ownership of a winding-down poll."""
        with self._state_changed:
            self._request_state_locked(False)

    def start_polling(self) -> None:
        """Request polling, handing off only after any predecessor has exited."""
        with self._state_changed:
            if self._shutting_down:
                raise RuntimeError("Runtime is shutting down")
            self._request_state_locked(
                True,
                reset_failure_budget=True,
            )

    def apply_config_changed(self) -> None:
        """Reload persisted configuration and apply it to the running process."""
        with self._state_changed:
            if self._shutting_down:
                raise RuntimeError("Runtime is shutting down")
            log.info("Configuration changed, applying runtime configuration")
            self.config_manager._load()

            # Imported lazily to keep runtime ownership independent of the entrypoint.
            from .main import _apply_timezone

            _apply_timezone(self.config_manager)
            self.storage.max_days = self.config_manager.get("history_days", 7)
            self._request_state_locked(
                self.config_manager.is_configured(),
                reset_failure_budget=True,
            )

    def wait_for_state(self, running: bool, timeout: float = 10) -> bool:
        """Wait for an observed state in tests and orderly process control."""
        with self._state_changed:
            return self._state_changed.wait_for(
                lambda: (
                    bool(self._poll_thread and self._poll_thread.is_alive())
                    if running
                    else self._poll_thread is None
                ),
                timeout=timeout,
            )

    def shutdown(self) -> None:
        """Request shutdown and wait no longer than the configured boundary."""
        with self._state_changed:
            self._shutting_down = True
            self._request_state_locked(False)
            watcher = self._handoff_thread

        if watcher and watcher is not threading.current_thread():
            watcher.join(timeout=self.stop_timeout)

        with self._state_changed:
            watcher_alive = bool(
                self._handoff_thread
                and self._handoff_thread.is_alive()
            )
            poll_alive = bool(
                self._poll_thread and self._poll_thread.is_alive()
            )
            if watcher_alive or poll_alive:
                log.warning(
                    "Runtime shutdown timed out after %.3fs; "
                    "attributed polling cleanup continues in daemon watcher",
                    self.stop_timeout,
                )
            self._state_changed.notify_all()

    def status(self) -> dict[str, object]:
        """Return a small secret-free runtime snapshot for diagnostics."""
        with self._state_lock:
            return {
                "running": bool(
                    self._poll_thread and self._poll_thread.is_alive()
                ),
                "desired_running": self._desired_running,
                "generation": self._generation,
                "poll_attributed": self._poll_thread is not None,
                "poll_attempt": (
                    self._attempt.sequence if self._attempt else None
                ),
                "restart_failures": self._consecutive_failures,
                "restart_exhausted": self._restart_exhausted,
                "last_poll_outcome": self._last_poll_outcome,
                "last_failure": (
                    {"type": self._last_failure_type}
                    if self._last_failure_type
                    else None
                ),
                "collectors": [
                    getattr(collector, "name", "")
                    for collector in self.web.get_collectors()
                ],
            }
