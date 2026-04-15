"""Smart Capture types -- execution status and trigger definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable

from ..types import EventDict

SEVERITY_RANK = {"info": 0, "warning": 1, "critical": 2}


class ExecutionStatus(str, Enum):
    PENDING = "pending"
    FIRED = "fired"
    COMPLETED = "completed"
    SUPPRESSED = "suppressed"
    EXPIRED = "expired"


@dataclass(frozen=True)
class Trigger:
    """A rule that matches events to actions.

    Modules register triggers with the engine. When an event matches,
    the engine applies guardrails and records an execution.
    """
    event_type: str
    action_type: str
    config_key: str | None = None
    min_severity: str | None = None
    require_details: dict[str, Any] | None = field(default=None, hash=False)
    sub_filter: Callable[..., bool] | None = field(default=None, repr=False, hash=False, compare=False)

    def matches(self, event: EventDict) -> bool:
        if event.get("event_type") != self.event_type:
            return False
        if self.min_severity:
            event_rank = SEVERITY_RANK.get(event.get("severity", "info"), 0)
            min_rank = SEVERITY_RANK.get(self.min_severity, 0)
            if event_rank < min_rank:
                return False
        if self.require_details:
            details = event.get("details") or {}
            for key, value in self.require_details.items():
                if details.get(key) != value:
                    return False
        return True
