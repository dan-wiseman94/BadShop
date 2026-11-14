"""Invocation admission policy, independent of the initiating provider or UI."""

from dataclasses import dataclass


FINISH_TOOLS = frozenset({'deepfry', 'save', 'animate', 'animate_sticker', 'export', 'export_profile'})


@dataclass
class ExecutionBudget:
    limit: int
    executed: int = 0

    @property
    def exhausted(self) -> bool:
        return self.executed >= self.limit

    def record_execution(self) -> None:
        """Reserve a slot immediately before execution; proposals and rejections are free.

        The owning session serializes CLI admissions and execution. The API loop
        executes sequentially, so neither can admit two calls against one slot.
        """
        if self.exhausted:
            raise RuntimeError('execution exceeded its admitted budget')
        self.executed += 1
