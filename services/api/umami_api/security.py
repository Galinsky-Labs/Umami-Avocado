"""Bearer-token authentication and workspace-scoped access resolution."""
import hashlib
import hmac
import secrets
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from umami_api.db import Database, utcnow
from umami_api.errors import ApiError, not_found
from umami_api.models import ApiToken, Membership, Principal, Workspace

TOKEN_PREFIX = "ua_"


def new_token() -> str:
    return TOKEN_PREFIX + secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def constant_time_equal(left: str, right: str) -> bool:
    return hmac.compare_digest(left.encode(), right.encode())


def issue_token(session: Session, principal: Principal, label: str,
                ttl_days: int | None = None) -> tuple[ApiToken, str]:
    secret = new_token()
    expires = utcnow() + timedelta(days=ttl_days) if ttl_days else None
    token = ApiToken(principal_id=principal.id, label=label, prefix=secret[:10],
                     token_hash=hash_token(secret), expires_at=expires)
    session.add(token)
    session.flush()
    return token, secret


def get_database(request: Request) -> Database:
    database = getattr(request.app.state, "database", None)
    if database is None:
        raise ApiError(503, "unavailable", "The research database is not configured.")
    return database


def get_session(database: Annotated[Database, Depends(get_database)]):
    with database.session() as session:
        yield session


@dataclass
class Caller:
    principal: Principal
    session: Session

    @property
    def is_agent(self) -> bool:
        return self.principal.kind == "agent"


def get_caller(request: Request, session: Annotated[Session, Depends(get_session)]) -> Caller:
    header = request.headers.get("authorization", "")
    scheme, _, secret = header.partition(" ")
    if scheme.lower() != "bearer" or not secret.startswith(TOKEN_PREFIX) or len(secret) > 128:
        raise ApiError(401, "unauthorized", "A valid bearer token is required.")
    token = session.scalar(select(ApiToken).where(ApiToken.token_hash == hash_token(secret)))
    now = utcnow()
    if token is None or token.revoked_at is not None or (
        token.expires_at is not None and token.expires_at <= now
    ):
        raise ApiError(401, "unauthorized", "A valid bearer token is required.")
    principal = session.get(Principal, token.principal_id)
    if principal is None or principal.disabled_at is not None:
        raise ApiError(401, "unauthorized", "A valid bearer token is required.")
    if token.last_used_at is None or (now - token.last_used_at) > timedelta(minutes=5):
        token.last_used_at = now
    return Caller(principal=principal, session=session)


@dataclass
class WorkspaceAccess:
    caller: Caller
    workspace: Workspace
    membership: Membership

    @property
    def session(self) -> Session:
        return self.caller.session

    @property
    def principal(self) -> Principal:
        return self.caller.principal

    @property
    def role(self) -> str:
        return self.membership.role


def resolve_workspace(caller: Caller, workspace_id: uuid.UUID) -> WorkspaceAccess:
    """Non-members receive 404 so workspace existence is not disclosed."""
    row = caller.session.execute(
        select(Workspace, Membership)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Workspace.id == workspace_id, Membership.principal_id == caller.principal.id)
    ).first()
    if row is None:
        raise not_found("workspace")
    return WorkspaceAccess(caller=caller, workspace=row[0], membership=row[1])


def workspace_access(workspace_id: uuid.UUID,
                     caller: Annotated[Caller, Depends(get_caller)]) -> WorkspaceAccess:
    return resolve_workspace(caller, workspace_id)


SessionDep = Annotated[Session, Depends(get_session)]
CallerDep = Annotated[Caller, Depends(get_caller)]
AccessDep = Annotated[WorkspaceAccess, Depends(workspace_access)]
