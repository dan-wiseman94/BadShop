"""The lifecycle state owned by one in-app provider run."""

import asyncio
import uuid
from dataclasses import dataclass, field

from badshop.agent.loop import TurnConfig
from badshop.session.session import Session


@dataclass
class RunState:
    session: Session
    config: TurnConfig
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    task: asyncio.Task | None = None
    cli_actor: str | None = None
    assistant_message_id: str | None = None
    outcome: dict | None = None
    stream_text: str = ''

    def finish(self, params: dict) -> bool:
        """Publish exactly one terminal outcome, retained for snapshot recovery."""
        if self.outcome is not None:
            return False
        self.outcome = {**params, 'run_id': self.id}
        return True
