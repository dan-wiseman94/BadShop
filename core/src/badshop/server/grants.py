"""Revocable adapter credentials, separate from the renderer's capability."""

import hmac
import secrets
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field

from badshop.diagnostics import register_secret


@dataclass(eq=False)
class AdapterGrant:
    actor: str
    document_incarnation: str
    profile_id: str | None = None
    token: str = field(default_factory=lambda: secrets.token_urlsafe(32), repr=False)
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    run_id: str | None = None
    run_token: str | None = field(default=None, repr=False)
    output_ids: set[str] = field(default_factory=set)
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

    def start_run(self, grant: AdapterGrant, run_id: str, branch_id: str | None,
                  publish: Callable[[str], None]) -> str:
        token = secrets.token_urlsafe(32)
        register_secret(token)
        publish(token)
        grant.run_token, grant.run_id, grant.branch_id = token, run_id, branch_id
        self._tokens[token] = grant
        return token

    def _end_grant_run(self, grant: AdapterGrant) -> None:
        if grant.run_token is not None:
            self._tokens.pop(grant.run_token, None)
        grant.run_token = grant.run_id = None
        grant.output_ids.clear()

    def revoke(self, grant: AdapterGrant) -> None:
        grant.revoked = True
        self._end_grant_run(grant)
        self._tokens.pop(grant.token, None)
        self._ids.pop(grant.id, None)

    def revoke_document(self, incarnation: str) -> None:
        for grant in list(self._ids.values()):
            if grant.document_incarnation == incarnation:
                self.revoke(grant)

    def end_run(self, run_id: str) -> None:
        for grant in self._ids.values():
            if grant.run_id == run_id:
                self._end_grant_run(grant)

    def close(self) -> None:
        for grant in list(self._ids.values()):
            self.revoke(grant)
