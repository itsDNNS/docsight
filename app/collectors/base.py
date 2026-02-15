"""Base classes for the unified Collector Architecture."""

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

log = logging.getLogger("docsis.collector")


@dataclass
class CollectorResult:
    """Result of a single collection run."""

    source: str
    data: Any = None
    success: bool = True
    error: str | None = None
    timestamp: float = field(default_factory=time.time)

    @classmethod
    def success(cls, source: str, data: Any) -> "CollectorResult":
        """Create a successful result."""
        return cls(source=source, data=data, success=True)

    @classmethod
    def failure(cls, source: str, error: str) -> "CollectorResult":
        """Create a failed result."""
        return cls(source=source, success=False, error=error)


class Collector(ABC):
    """Abstract base class for all data collectors.

    Provides timestamp-based scheduling and fail-safe penalty tracking
    for consecutive failures with automatic recovery.
    """

    MAX_PENALTY_SECONDS = 3600  # 1 hour max backoff
    PENALTY_RESET_HOURS = 24    # Auto-reset after 24h idle

    def __init__(self, poll_interval_seconds: int):
        self._poll_interval_seconds = poll_interval_seconds
        self._last_poll: float = 0.0
        self._consecutive_failures: int = 0
        self._last_failure_time: float = 0.0

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique identifier for this collector."""
        ...

    @abstractmethod
    def collect(self) -> CollectorResult:
        """Run a single data collection cycle."""
        ...

    def is_enabled(self) -> bool:
        """Override to conditionally disable this collector."""
        return True

    @property
    def poll_interval_seconds(self) -> int:
        return self._poll_interval_seconds

    @property
    def penalty_seconds(self) -> int:
        """Exponential backoff penalty with auto-reset.
        
        Penalty doubles with each failure: 30s, 60s, 120s, 240s, ...
        Capped at MAX_PENALTY_SECONDS (1 hour).
        Auto-resets to 0 after PENALTY_RESET_HOURS (24h) of idle time.
        """
        # Auto-reset penalty after 24h without activity
        if self._consecutive_failures > 0 and self._last_failure_time > 0:
            idle_hours = (time.time() - self._last_failure_time) / 3600
            if idle_hours >= self.PENALTY_RESET_HOURS:
                log.info(
                    "%s: Auto-resetting penalty after %.1fh idle (was %d failures)",
                    self.name, idle_hours, self._consecutive_failures
                )
                self._consecutive_failures = 0
                self._last_failure_time = 0.0
                return 0
        
        if self._consecutive_failures == 0:
            return 0
        
        return min(
            30 * (2 ** (self._consecutive_failures - 1)),
            self.MAX_PENALTY_SECONDS,
        )

    @property
    def effective_interval(self) -> float:
        """Poll interval including any penalty backoff."""
        return self._poll_interval_seconds + self.penalty_seconds

    def should_poll(self) -> bool:
        """True if enough time has elapsed since the last poll."""
        return (time.time() - self._last_poll) >= self.effective_interval

    def record_success(self):
        """Reset penalty counter and update last poll timestamp."""
        if self._consecutive_failures > 0:
            log.info(
                "%s: Recovered after %d failures (penalty was %ds)",
                self.name, self._consecutive_failures, self.penalty_seconds
            )
        self._consecutive_failures = 0
        self._last_failure_time = 0.0
        self._last_poll = time.time()

    def record_failure(self):
        """Increment penalty counter and update last poll timestamp."""
        self._consecutive_failures += 1
        self._last_failure_time = time.time()
        self._last_poll = time.time()
        
        penalty = self.penalty_seconds
        log.warning(
            "%s: Failure #%d recorded, next attempt in %ds (effective interval: %ds)",
            self.name, self._consecutive_failures, 
            int(self.effective_interval), penalty
        )

    def get_status(self) -> dict:
        """Return collector health status for monitoring.
        
        Returns:
            dict with keys: name, enabled, failures, penalty, next_poll, last_poll
        """
        now = time.time()
        time_until_next = max(0, self.effective_interval - (now - self._last_poll))
        
        return {
            "name": self.name,
            "enabled": self.is_enabled(),
            "consecutive_failures": self._consecutive_failures,
            "penalty_seconds": self.penalty_seconds,
            "poll_interval": self._poll_interval_seconds,
            "effective_interval": self.effective_interval,
            "last_poll": self._last_poll,
            "next_poll_in": int(time_until_next),
        }
