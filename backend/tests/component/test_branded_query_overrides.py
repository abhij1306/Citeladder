from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.demand.query_classification import (
    append_override,
    classify_project_query,
)
from app.models.brand import Brand, BrandAlias, OwnedDomain
from app.models.demand import BrandedQueryOverride
from app.models.project import Project
from app.models.user import User
from app.models.workspace import Workspace


async def test_latest_append_only_override_wins_and_stays_workspace_scoped(
    db_session: AsyncSession,
) -> None:
    workspace = Workspace(name="Brand query")
    foreign_workspace = Workspace(name="Foreign")
    actor = User(email="brand-query@example.com", hashed_password="x")
    db_session.add_all([workspace, foreign_workspace, actor])
    await db_session.flush()
    project = Project(
        workspace_id=workspace.id,
        name="Cube project",
        brand_name="Cube",
    )
    db_session.add(project)
    await db_session.flush()
    brand = Brand(project_id=project.id, name="Cube")
    brand.aliases = [BrandAlias(alias="Cube Inc")]
    db_session.add_all(
        [brand, OwnedDomain(project_id=project.id, domain="cube27.com")]
    )
    await db_session.flush()

    automatic = await classify_project_query(
        db_session,
        workspace_id=workspace.id,
        project_id=project.id,
        query="cube pricing",
    )
    assert automatic is not None and automatic.classification == "ambiguous"

    first = await append_override(
        db_session,
        workspace_id=workspace.id,
        project_id=project.id,
        actor_user_id=actor.id,
        query="cube pricing",
        classification="branded",
    )
    second = await append_override(
        db_session,
        workspace_id=workspace.id,
        project_id=project.id,
        actor_user_id=actor.id,
        query="cube pricing",
        classification="non_branded",
    )
    await db_session.commit()

    rows = list(
        (
            await db_session.scalars(
                select(BrandedQueryOverride).where(
                    BrandedQueryOverride.project_id == project.id
                )
            )
        ).all()
    )
    assert {row.id for row in rows} == {first.id, second.id}
    effective = await classify_project_query(
        db_session,
        workspace_id=workspace.id,
        project_id=project.id,
        query="Cube   Pricing",
    )
    assert effective is not None
    assert effective.classification == "non_branded"
    assert effective.override_id == second.id
    assert (
        await classify_project_query(
            db_session,
            workspace_id=foreign_workspace.id,
            project_id=project.id,
            query="cube pricing",
        )
        is None
    )
