"""Revocable adapter credentials, separate from the renderer's capability."""

import hmac
import secrets
import uuid
from dataclasses import dataclass, field


@dataclass(eq=False)
class AdapterGrant:
    actor: str
    document_incarnation: str
    profile_id: str | None = None
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    run_id: str | None = None
    branch_id: str | None = None
    revoked: bool = False
    standalone: bool = False

    @property
    def execution_actor(self) -> str:
        return f'{self.actor}:{self.id}'


class AdapterGrants:
    def __init__(self):
        self._tokens: dict[str, AdapterGrant] = {}
        self._ids: dict[str, AdapterGrant] = {}

    def issue(self, actor: str, incarnation: str, profile_id: str | None = None,
              *, standalone: bool = False) -> AdapterGrant:
        grant = AdapterGrant(actor, incarnation, profile_id, standalone=standalone)
        self._ids[grant.id] = grant
        if not standalone:
            self._tokens[grant.token] = grant
        return grant

    def authenticate(self, token: str, actor: str) -> AdapterGrant | None:
        grant = self._tokens.get(token)
        if grant and not grant.revoked and hmac.compare_digest(grant.actor, actor):
            return grant
        return None

    def get(self, grant_id: str | None) -> AdapterGrant | None:
        return self._ids.get(grant_id) if grant_id else None

    def revoke(self, grant: AdapterGrant) -> None:
        grant.revoked = True
        grant.run_id = None
        self._tokens.pop(grant.token, None)
        self._ids.pop(grant.id, None)

    def revoke_document(self, incarnation: str) -> None:
        for grant in list(self._ids.values()):
            if grant.document_incarnation == incarnation:
                self.revoke(grant)

    def end_run(self, run_id: str) -> None:
        for grant in self._ids.values():
            if grant.run_id == run_id:
                grant.run_id = None

    def close(self) -> None:
        for grant in list(self._ids.values()):
            self.revoke(grant)
