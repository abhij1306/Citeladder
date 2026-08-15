from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.demand.page_equivalence import resolve_owned_page
from app.domain.site_health.normalization import url_hash
from app.models.project import Project
from app.models.site_health import SiteUrl
from app.models.workspace import Workspace


async def test_exact_resolution_is_workspace_and_project_scoped(
    db_session: AsyncSession,
) -> None:
    first = Workspace(name="Resolver one")
    second = Workspace(name="Resolver two")
    db_session.add_all([first, second])
    await db_session.flush()
    project = Project(workspace_id=first.id, name="First")
    foreign = Project(workspace_id=second.id, name="Second")
    db_session.add_all([project, foreign])
    await db_session.flush()
    normalized = "https://example.com/page"
    db_session.add_all(
        [
            SiteUrl(
                workspace_id=first.id,
                project_id=project.id,
                normalized_url=normalized,
                url_hash=url_hash(normalized),
            ),
            SiteUrl(
                workspace_id=second.id,
                project_id=foreign.id,
                normalized_url=normalized,
                url_hash=url_hash(normalized),
            ),
        ]
    )
    await db_session.commit()

    result = await resolve_owned_page(
        db_session,
        workspace_id=first.id,
        project_id=project.id,
        url=normalized,
    )

    assert result.outcome == "exact"
    assert len(result.candidates) == 1
    assert result.candidates[0].site_url_id == result.site_url_id
