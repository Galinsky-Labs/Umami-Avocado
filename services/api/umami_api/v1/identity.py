"""Bootstrap, principals, workspaces, memberships and API tokens (UA-003)."""
import uuid

from fastapi import APIRouter, Request
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from umami_api.db import utcnow
from umami_api.errors import ApiError, conflict, forbidden, not_found
from umami_api.models import ApiToken, Membership, Principal, Workspace
from umami_api.schemas import (
    BootstrapIn,
    BootstrapOut,
    IssuedToken,
    MemberCreated,
    MemberIn,
    MemberOut,
    MeOut,
    PrincipalOut,
    TokenIn,
    TokenOut,
    WorkspaceIn,
    WorkspaceMembershipOut,
    WorkspaceOut,
)
from umami_api.security import (
    AccessDep,
    CallerDep,
    SessionDep,
    WorkspaceAccess,
    constant_time_equal,
    issue_token,
)

router = APIRouter(tags=["identity"])
MANAGER_ROLES = ("owner", "admin")


def require_role(access: WorkspaceAccess, roles: tuple[str, ...]) -> None:
    if access.role not in roles:
        raise forbidden()


@router.post("/bootstrap", response_model=BootstrapOut, status_code=201,
             operation_id="bootstrap_first_owner")
def bootstrap(body: BootstrapIn, request: Request, session: SessionDep):
    """One-time creation of the first human owner, gated by UMAMI_BOOTSTRAP_TOKEN."""
    expected = request.app.state.settings.bootstrap_token
    supplied = request.headers.get("x-bootstrap-token", "")
    if not expected or not supplied or not constant_time_equal(supplied, expected):
        raise ApiError(401, "unauthorized", "A valid bootstrap token is required.")
    session.execute(select(func.pg_advisory_xact_lock(74_210_001)))
    if session.scalar(select(func.count()).select_from(Principal)):
        raise conflict("The platform has already been bootstrapped.")
    principal = Principal(kind="human", display_name=body.display_name, email=body.email.lower())
    session.add(principal)
    session.flush()
    workspace = Workspace(slug=body.workspace_slug, name=body.workspace_name,
                          created_by=principal.id)
    session.add(workspace)
    session.flush()
    session.add(Membership(workspace_id=workspace.id, principal_id=principal.id, role="owner"))
    token, secret = issue_token(session, principal, "bootstrap")
    return BootstrapOut(principal=PrincipalOut.model_validate(principal),
                        workspace=WorkspaceOut.model_validate(workspace),
                        issued=IssuedToken(token=TokenOut.model_validate(token), secret=secret))


@router.get("/me", response_model=MeOut, operation_id="get_me")
def me(caller: CallerDep):
    rows = caller.session.execute(
        select(Workspace, Membership.role)
        .join(Membership, Membership.workspace_id == Workspace.id)
        .where(Membership.principal_id == caller.principal.id)
        .order_by(Workspace.name)
    ).all()
    return MeOut(
        principal=PrincipalOut.model_validate(caller.principal),
        memberships=[WorkspaceMembershipOut(workspace=WorkspaceOut.model_validate(w), role=r)
                     for w, r in rows],
    )


@router.post("/workspaces", response_model=WorkspaceOut, status_code=201,
             operation_id="create_workspace")
def create_workspace(body: WorkspaceIn, caller: CallerDep):
    if caller.is_agent:
        raise forbidden("Agents cannot create workspaces.")
    if caller.session.scalar(select(Workspace.id).where(Workspace.slug == body.slug)):
        raise conflict("A workspace with this slug already exists.")
    workspace = Workspace(slug=body.slug, name=body.name, created_by=caller.principal.id)
    caller.session.add(workspace)
    caller.session.flush()
    caller.session.add(Membership(workspace_id=workspace.id, principal_id=caller.principal.id,
                                  role="owner"))
    return workspace


@router.get("/workspaces/{workspace_id}", response_model=WorkspaceOut,
            operation_id="get_workspace")
def get_workspace(access: AccessDep):
    return access.workspace


@router.get("/workspaces/{workspace_id}/members", response_model=list[MemberOut],
            operation_id="list_members")
def list_members(access: AccessDep):
    rows = access.session.execute(
        select(Principal, Membership.role)
        .join(Membership, Membership.principal_id == Principal.id)
        .where(Membership.workspace_id == access.workspace.id)
        .order_by(Principal.display_name)
    ).all()
    return [MemberOut(principal=PrincipalOut.model_validate(p), role=r) for p, r in rows]


@router.post("/workspaces/{workspace_id}/members", response_model=MemberCreated,
             status_code=201, operation_id="create_member")
def create_member(body: MemberIn, access: AccessDep):
    require_role(access, MANAGER_ROLES)
    if access.caller.is_agent:
        raise forbidden("Agents cannot create principals.")
    if (body.kind == "agent") != (body.role == "agent"):
        raise ApiError(400, "invalid_request",
                       "Agent principals must hold exactly the agent role.")
    if body.role == "owner" and access.role != "owner":
        raise forbidden("Only owners can appoint owners.")
    principal = Principal(kind=body.kind, display_name=body.display_name,
                          email=body.email.lower() if body.email else None)
    access.session.add(principal)
    try:
        access.session.flush()
    except IntegrityError as error:
        raise conflict("A principal with this email already exists.") from error
    access.session.add(Membership(workspace_id=access.workspace.id, principal_id=principal.id,
                                  role=body.role))
    token, secret = issue_token(access.session, principal, "initial",
                                ttl_days=90 if body.kind == "agent" else None)
    return MemberCreated(
        member=MemberOut(principal=PrincipalOut.model_validate(principal), role=body.role),
        issued=IssuedToken(token=TokenOut.model_validate(token), secret=secret),
    )


@router.get("/tokens", response_model=list[TokenOut], operation_id="list_tokens")
def list_tokens(caller: CallerDep):
    return caller.session.scalars(
        select(ApiToken).where(ApiToken.principal_id == caller.principal.id)
        .order_by(ApiToken.created_at.desc())
    ).all()


@router.post("/tokens", response_model=IssuedToken, status_code=201, operation_id="create_token")
def create_token(body: TokenIn, caller: CallerDep):
    ttl = body.ttl_days
    if caller.is_agent:
        ttl = min(ttl or 90, 90)
    token, secret = issue_token(caller.session, caller.principal, body.label, ttl)
    return IssuedToken(token=TokenOut.model_validate(token), secret=secret)


@router.delete("/tokens/{token_id}", response_model=TokenOut, operation_id="revoke_token")
def revoke_token(token_id: uuid.UUID, caller: CallerDep):
    token = caller.session.get(ApiToken, token_id)
    if token is None or token.principal_id != caller.principal.id:
        raise not_found("token")
    if token.revoked_at is None:
        token.revoked_at = utcnow()
    return token
