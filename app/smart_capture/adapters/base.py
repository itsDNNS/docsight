"""Base class for Smart Capture action adapters."""

from __future__ import annotations

from typing import Any

from ...types import EventDict


class ActionAdapter:
    """Base class for Smart Capture action adapters.

    Subclasses implement execute() to fire an action when a pending
    execution is created, and optionally on_results_imported() for
    async result linking.
    """

    def __init__(self, action_type: str):
        self.action_type = action_type

    def execute(self, execution_id: int, event: EventDict) -> tuple[bool, str | None]:
        """Fire the action. Returns (success, error_message).

        Called by the engine immediately after save_execution(PENDING).
        On success: adapter should update execution to FIRED.
        On failure: adapter should update execution to EXPIRED with last_error.
        """
        raise NotImplementedError

    def on_results_imported(self, results: list[dict[str, Any]]) -> None:
        """Called when new results are available for matching. Optional."""
        pass
