class EngineError(Exception):
    """A failure the user or the model can act on. `hint` says what to try instead."""

    def __init__(self, message: str, hint: str | None = None, *, data: dict | None = None):
        super().__init__(message)
        self.message = message
        self.hint = hint
        self.data = data or {}  # structured observations survive an actionable failure
