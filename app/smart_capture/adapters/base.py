"""Base class for Smart Capture action adapters."""


class ActionAdapter:
    """Base class for Smart Capture action adapters.

    Subclasses implement execute() to fire an action when a pending
    execution is created, and optionally on_results_imported() for
    async result linking.
    """

    def __init__(self, action_type: str):
        self.action_type = action_type

    def execute(self, execution_id: int, event: dict) -> tuple[bool, str | None]:
        """Fire the action. Returns (success, error_message).

        Called by the engine immediately after save_execution(PENDING).
        On success: adapter should update execution to FIRED.
        On failure: adapter should update execution to EXPIRED with last_error.
        """
        raise NotImplementedError

    def on_results_imported(self, results: list[dict]):
        """Called when new results are available for matching. Optional."""
        pass
