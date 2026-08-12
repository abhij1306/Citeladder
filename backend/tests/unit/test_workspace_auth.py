"""Unit tests for the workspace-auth dependency (invariant 5).

A member is authorized; a non-member and an unauthenticated caller are
rejected. This is the single gate every downstream query relies on.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import cast

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.deps import require_workspace_member
from app.core.security import create_access_token
from app.domain.auth.service import register_user
from app.domain.workspaces import service as workspace_service
from app.domain.workspaces.service import (
    create_workspace,
    ensure_personal_workspace,
    get_membership,
    list_workspaces_for_user,
)
from app.models.user import User
from app.models.workspace import WorkspaceMember


async def _register(session: AsyncSession, email: str):
    return await register_user(session, email, "password123")


@pytest.mark.asyncio
async def test_member_is_authorized(db_session: AsyncSession) -> None:
    user = await _register(db_session, "member@example.com")
    workspaces = await list_workspaces_for_user(db_session, user)
    workspace, _member = workspaces[0]

    ctx = await require_workspace_member(
        workspace_id=workspace.id, user=user, session=db_session
    )
    assert ctx.user.id == user.id
    assert ctx.workspace_id == workspace.id
    assert ctx.member.role == "owner"


@pytest.mark.asyncio
async def test_non_member_is_rejected_with_404(db_session: AsyncSession) -> None:
    owner = await _register(db_session, "owner@example.com")
    outsider = await _register(db_session, "outsider@example.com")
    owner_ws, _ = (await list_workspaces_for_user(db_session, owner))[0]

    with pytest.raises(HTTPException) as exc:
        await require_workspace_member(
            workspace_id=owner_ws.id, user=outsider, session=db_session
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_unknown_workspace_is_rejected(db_session: AsyncSession) -> None:
    user = await _register(db_session, "ghost@example.com")
    with pytest.raises(HTTPException) as exc:
        await require_workspace_member(
            workspace_id=uuid.uuid4(), user=user, session=db_session
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_get_membership_returns_none_for_non_member(
    db_session: AsyncSession,
) -> None:
    owner = await _register(db_session, "o2@example.com")
    other = await _register(db_session, "u2@example.com")
    ws, _ = await create_workspace(db_session, owner, "Team")

    assert await get_membership(db_session, ws.id, owner.id) is not None
    assert await get_membership(db_session, ws.id, other.id) is None


@pytest.mark.asyncio
async def test_create_and_personal_workspace_ensure_share_creation_lock(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as setup:
        user = User(email="workspace-race@example.com", hashed_password="x")
        setup.add(user)
        await setup.commit()
        user_id = user.id

    create_reached_billing = asyncio.Event()
    release_create = asyncio.Event()
    ensure_attempted_lock = asyncio.Event()
    lock_subject = workspace_service.lock_subject

    async def observe_lock(
        session: AsyncSession, *, namespace: str, subject: str | uuid.UUID
    ) -> None:
        task = asyncio.current_task()
        if task is not None and task.get_name() == "ensure-personal":
            ensure_attempted_lock.set()
        await lock_subject(session, namespace=namespace, subject=subject)

    async def pause_billing(*_args: object, **_kwargs: object) -> None:
        create_reached_billing.set()
        await release_create.wait()

    monkeypatch.setattr(workspace_service, "lock_subject", observe_lock)
    monkeypatch.setattr(workspace_service, "ensure_user_billing", pause_billing)

    async def create_explicit_workspace() -> None:
        async with session_factory() as session:
            current_user = await session.get(User, user_id)
            assert current_user is not None
            await create_workspace(session, current_user, "Explicit")

    async def ensure_default_workspace() -> None:
        async with session_factory() as session:
            current_user = await session.get(User, user_id)
            assert current_user is not None
            await ensure_personal_workspace(session, current_user)
            await session.commit()

    create_task = asyncio.create_task(create_explicit_workspace())
    await create_reached_billing.wait()
    ensure_task = asyncio.create_task(
        ensure_default_workspace(), name="ensure-personal"
    )
    await ensure_attempted_lock.wait()
    assert not ensure_task.done()

    release_create.set()
    await asyncio.gather(create_task, ensure_task)

    async with session_factory() as session:
        membership_count = await session.scalar(
            select(func.count(WorkspaceMember.id)).where(
                WorkspaceMember.user_id == user_id
            )
        )
    assert membership_count == 1


def test_unauthenticated_current_user_rejected() -> None:
    """A missing session cookie yields 401 from get_current_user."""
    from app.api.deps import get_current_user

    with pytest.raises(HTTPException) as exc:
        asyncio.run(
            get_current_user(session_token=None, session=cast(AsyncSession, None))
        )
    assert exc.value.status_code == 401


def test_valid_token_shape() -> None:
    token = create_access_token(str(uuid.uuid4()))
    assert isinstance(token, str) and token.count(".") == 2
