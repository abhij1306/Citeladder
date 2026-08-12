# Workspace + membership service (workspace-scoped, invariant 5).
from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.product_tour import PRODUCT_TOUR_VERSION
from app.core.config.workspaces import MAX_WORKSPACES_PER_USER
from app.domain.abuse.service import lock_subject
from app.domain.billing.bootstrap import ensure_user_billing
from app.domain.workspaces.schemas import ProductTourResponse, ProductTourUpdate
from app.models.user import User
from app.models.workspace import ProductTourStatus, Workspace, WorkspaceMember

# Roles a member can hold within a workspace. The creator is the owner.
WORKSPACE_ROLE_OWNER = "owner"


class WorkspaceLimitExceededError(ValueError):
    """The account already owns or belongs to the maximum tenant roots."""

    def __init__(self, *, limit: int) -> None:
        super().__init__(f"Workspace limit of {limit} reached")
        self.limit = limit


def product_tour_response(member: WorkspaceMember) -> ProductTourResponse:
    version = member.product_tour_version or PRODUCT_TOUR_VERSION
    status = ProductTourStatus(member.product_tour_status)
    started_at = member.product_tour_started_at
    completed_at = member.product_tour_completed_at
    if member.product_tour_version != PRODUCT_TOUR_VERSION:
        version = PRODUCT_TOUR_VERSION
        status = ProductTourStatus.NOT_STARTED
        started_at = None
        completed_at = None
    return ProductTourResponse(
        workspace_id=member.workspace_id,
        version=version,
        status=status,
        step_id=(
            member.product_tour_step_id
            if status == ProductTourStatus.IN_PROGRESS
            else None
        ),
        started_at=started_at,
        completed_at=completed_at,
    )


async def update_product_tour(
    session: AsyncSession,
    member: WorkspaceMember,
    payload: ProductTourUpdate,
) -> ProductTourResponse:
    now = datetime.now(UTC)
    is_new_version = member.product_tour_version != payload.version
    member.product_tour_version = payload.version
    member.product_tour_status = payload.status.value
    member.product_tour_step_id = payload.step_id

    if payload.status == ProductTourStatus.NOT_STARTED:
        member.product_tour_started_at = None
        member.product_tour_completed_at = None
    elif payload.status == ProductTourStatus.IN_PROGRESS:
        if is_new_version or member.product_tour_started_at is None:
            member.product_tour_started_at = now
        member.product_tour_completed_at = None
    else:
        if is_new_version or member.product_tour_started_at is None:
            member.product_tour_started_at = now
        member.product_tour_completed_at = now

    await session.commit()
    await session.refresh(member)
    return product_tour_response(member)


def _default_workspace_name(user: User) -> str:
    local_part = (user.email or "").split("@", 1)[0].strip()
    label = local_part or "My"
    return f"{label}'s Workspace"


async def get_membership(
    session: AsyncSession, workspace_id: uuid.UUID, user_id: uuid.UUID
) -> WorkspaceMember | None:
    """Resolve the caller's membership row for a workspace, or None.

    This is the single source of truth used by ``require_workspace_member``;
    a missing row means no access (403/404), never a user-id fallback. A
    membership row pointing at the reserved SYSTEM workspace never authorizes
    (T11): system workspaces cannot have memberships, so even a stray row is
    inert here.
    """
    result = await session.execute(
        select(WorkspaceMember)
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(
            WorkspaceMember.workspace_id == workspace_id,
            WorkspaceMember.user_id == user_id,
            Workspace.is_system.is_(False),
        )
    )
    return result.scalar_one_or_none()


async def list_workspaces_for_user(
    session: AsyncSession, user: User
) -> list[tuple[Workspace, WorkspaceMember]]:
    """Return the workspaces the user is a member of, with their membership.

    The reserved system workspace is never a tenant workspace (T11): it is
    excluded even if a stray membership row exists.
    """
    result = await session.execute(
        select(Workspace, WorkspaceMember)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .where(
            WorkspaceMember.user_id == user.id,
            Workspace.is_system.is_(False),
        )
        .order_by(Workspace.created_at.asc())
    )
    return [tuple(row) for row in result.all()]


async def create_workspace(
    session: AsyncSession, user: User, name: str
) -> tuple[Workspace, WorkspaceMember]:
    """Create a workspace and add ``user`` as its owner."""
    await lock_subject(session, namespace="workspace.create", subject=user.id)
    current = await session.scalar(
        select(func.count(WorkspaceMember.id))
        .join(Workspace, Workspace.id == WorkspaceMember.workspace_id)
        .where(
            WorkspaceMember.user_id == user.id,
            Workspace.is_system.is_(False),
        )
    )
    if int(current or 0) >= MAX_WORKSPACES_PER_USER:
        raise WorkspaceLimitExceededError(limit=MAX_WORKSPACES_PER_USER)
    workspace = Workspace(name=name)
    session.add(workspace)
    await session.flush()
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WORKSPACE_ROLE_OWNER,
    )
    session.add(member)
    await session.flush()
    await ensure_user_billing(session, user, workspace_ids=(workspace.id,))
    await session.commit()
    await session.refresh(workspace)
    await session.refresh(member)
    return workspace, member


async def ensure_personal_workspace(
    session: AsyncSession, user: User
) -> Workspace | None:
    """Auto-create a personal workspace + owner membership if the user has none.

    Returns the newly created workspace, or ``None`` if the user was already a
    member of at least one workspace. Flushes but does not commit — the caller
    owns the transaction boundary.
    """
    await lock_subject(session, namespace="workspace.create", subject=user.id)
    existing = await session.execute(
        select(WorkspaceMember.id).where(WorkspaceMember.user_id == user.id).limit(1)
    )
    if existing.scalar_one_or_none() is not None:
        return None
    workspace = Workspace(name=_default_workspace_name(user))
    session.add(workspace)
    await session.flush()
    member = WorkspaceMember(
        workspace_id=workspace.id,
        user_id=user.id,
        role=WORKSPACE_ROLE_OWNER,
    )
    session.add(member)
    await session.flush()
    return workspace
