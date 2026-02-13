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


class Collector(ABC):
    """Abstract base class for all data collectors.

    Provides timestamp-based scheduling and Netdata-style penalty tracking
    for consecutive failures.
    """

    MAX_PENALTY_SECONDS = 600  # 10 min cap

    def __init__(self, poll_interval_seconds: int):
        self._poll_interval_seconds = poll_interval_seconds
        self._last_poll: float = 0.0
        self._consecutive_failures: int = 0

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
        """Exponential backoff penalty: 30s, 60s, 120s, ... capped at 600s."""
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
        self._consecutive_failures = 0
        self._last_poll = time.time()

    def record_failure(self):
        """Increment penalty counter and update last poll timestamp."""
        self._consecutive_failures += 1
        self._last_poll = time.time()
