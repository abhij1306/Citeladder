from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.demand.detector_source import classification_revision_material
from app.domain.demand.projection import QueryEvidenceInput
from app.domain.demand.query_classification import (
    append_override,
    classify_project_queries,
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
    db_session.add_all([brand, OwnedDomain(project_id=project.id, domain="cube27.com")])
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
    batch = await classify_project_queries(
        db_session,
        workspace_id=workspace.id,
        project_id=project.id,
        queries=["Cube Pricing", "independent research"],
    )
    assert batch["cube pricing"].override_id == second.id
    assert batch["independent research"].classification == "non_branded"
    evidence_material = await classification_revision_material(
        db_session,
        workspace_id=workspace.id,
        project_id=project.id,
        search_inputs=[],
        query_inputs=[
            QueryEvidenceInput(
                observed_date=date(2026, 7, 1),
                property_ref="sc-domain:cube27.com",
                normalized_query="cube pricing",
                resolved_page_url="https://cube27.com/pricing",
                resolution_outcome="exact",
                classification="non_branded",
                classifier_version="stale-input",
                classification_override_id=None,
                impressions=100,
                clicks=10,
                position=5.0,
                source_metric_row_id=str(uuid.uuid4()),
                source_artifact_id=str(uuid.uuid4()),
            )
        ],
    )
    assert evidence_material == [
        {
            "query": "cube pricing",
            "classification": "non_branded",
            "classifier_version": second.classifier_version,
            "override_id": str(second.id),
        }
    ]
    assert (
        await classify_project_query(
            db_session,
            workspace_id=foreign_workspace.id,
            project_id=project.id,
            query="cube pricing",
        )
        is None
    )
