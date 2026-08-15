"""Query-evidence lifecycle, provenance, pagination, and authorization."""

from __future__ import annotations

import uuid
from datetime import date

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.integrations import (
    DATASET_GSC_QUERY_PAGE_DAILY,
    INTEGRATION_PROVIDER_GSC,
)
from app.domain.demand.query_evidence import (
    build_query_evidence,
)
from app.domain.demand.query_evidence_reads import list_query_evidence
from app.domain.site_health.normalization import url_hash
from app.models.demand import QueryEvidenceRow, QueryEvidenceSnapshot
from app.models.site_health import SiteUrl
from tests.component.analytics_helpers import (
    seed_ga4_import,
    seed_metric_row,
    seed_workspace_project,
)

_WINDOW = (date(2026, 7, 1), date(2026, 7, 14))
_PAGE = "https://example.com/guides/answer-engines"


async def _seed_rows(session: AsyncSession, *, count: int = 3):
    workspace_id, project_id = await seed_workspace_project(session)
    site_url = SiteUrl(
        workspace_id=workspace_id,
        project_id=project_id,
        normalized_url=_PAGE,
        url_hash=url_hash(_PAGE),
    )
    session.add(site_url)
    await session.flush()
    seed = await seed_ga4_import(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        dataset=DATASET_GSC_QUERY_PAGE_DAILY,
        window=_WINDOW,
        provider=INTEGRATION_PROVIDER_GSC,
    )
    for index in range(count):
        observed = _WINDOW[0].replace(day=_WINDOW[0].day + index)
        await seed_metric_row(
            session,
            seed=seed,
            row_date=observed,
            dimension_values=(
                f"AEO guide {index}",
                _PAGE,
                observed.strftime("%Y%m%d"),
            ),
            metrics={
                "impressions": 100 + index,
                "clicks": 10,
                "ctr": 0.1,
                "position": 7.5,
            },
            provider=INTEGRATION_PROVIDER_GSC,
        )
    await session.commit()
    return workspace_id, project_id, site_url, seed


async def test_projection_is_idempotent_resolved_and_source_linked(
    db_session: AsyncSession,
) -> None:
    workspace_id, project_id, site_url, seed = await _seed_rows(db_session)
    first = await build_query_evidence(
        db_session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    second = await build_query_evidence(
        db_session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    await db_session.commit()

    assert first.id == second.id
    assert first.state == "available"
    assert first.coverage["projected_row_count"] == 3
    rows = list(
        (
            await db_session.scalars(
                select(QueryEvidenceRow).where(QueryEvidenceRow.snapshot_id == first.id)
            )
        ).all()
    )
    assert {row.site_url_id for row in rows} == {site_url.id}
    assert {row.resolution_outcome for row in rows} == {"exact"}
    assert {row.source_artifact_id for row in rows} == {seed.artifact_id}
    assert {row.source_metric_row_id for row in rows} == set(seed.metric_row_ids)


async def test_changed_source_supersedes_and_pagination_is_stable(
    db_session: AsyncSession,
) -> None:
    workspace_id, project_id, _site_url, seed = await _seed_rows(db_session)
    first = await build_query_evidence(
        db_session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    page_one = await list_query_evidence(db_session, snapshot=first, limit=2)
    assert len(page_one.rows) == 2
    assert page_one.next_cursor is not None
    page_two = await list_query_evidence(
        db_session, snapshot=first, limit=2, cursor=page_one.next_cursor
    )
    assert len(page_two.rows) == 1
    assert {row.id for row in page_one.rows}.isdisjoint(row.id for row in page_two.rows)

    changed = date(2026, 7, 1)
    await seed_metric_row(
        db_session,
        seed=seed,
        row_date=changed,
        dimension_values=("AEO guide 0", _PAGE, changed.strftime("%Y%m%d")),
        metrics={"impressions": 200, "clicks": 20, "ctr": 0.1, "position": 6},
        resync_seq=1,
        provider=INTEGRATION_PROVIDER_GSC,
    )
    await db_session.commit()
    second = await build_query_evidence(
        db_session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
    )
    await db_session.commit()
    assert second.id != first.id
    assert second.supersedes_snapshot_id == first.id
    assert (
        await db_session.scalar(select(func.count()).select_from(QueryEvidenceSnapshot))
        == 2
    )


async def _register_project(client: httpx.AsyncClient, label: str) -> dict:
    email = f"query-evidence-{label}-{uuid.uuid4().hex}@example.com"
    assert (
        await client.post(
            "/api/v1/auth/register",
            json={"email": email, "password": "password123"},
        )
    ).status_code == 202
    assert (
        await client.post(
            "/api/v1/auth/login", json={"email": email, "password": "password123"}
        )
    ).status_code == 200
    response = await client.post("/api/v1/projects", json={"name": label})
    assert response.status_code == 201
    return response.json()


async def test_api_requires_window_rejects_bad_cursor_and_is_workspace_safe(
    client: httpx.AsyncClient, db_session: AsyncSession
) -> None:
    first = await _register_project(client, "first")
    snapshot = QueryEvidenceSnapshot(
        workspace_id=uuid.UUID(first["workspace_id"]),
        project_id=uuid.UUID(first["id"]),
        window_start=_WINDOW[0],
        window_end=_WINDOW[1],
        source_hash="a" * 64,
        state="observed_zero",
        source_metric_row_ids=[],
        source_artifact_ids=[],
        coverage={"projected_row_count": 0},
        limitations=[],
        analyzer_version="query-evidence-1",
        resolver_version="owned-page-resolver-1",
    )
    db_session.add(snapshot)
    await db_session.commit()
    prefix = f"/api/v1/projects/{first['id']}/demand/query-evidence"
    assert (await client.get(prefix)).status_code == 422
    response = await client.get(
        prefix,
        params={
            "window_start": _WINDOW[0].isoformat(),
            "window_end": _WINDOW[1].isoformat(),
            "cursor": "not-a-cursor",
        },
    )
    assert response.status_code == 422
    assert response.json()["detail"] == "query_evidence_cursor_invalid"
    summary = await client.get(
        f"{prefix}/summary",
        params={
            "window_start": _WINDOW[0].isoformat(),
            "window_end": _WINDOW[1].isoformat(),
        },
    )
    assert summary.status_code == 200
    assert summary.json()["snapshot"]["state"] == "observed_zero"

    second = await _register_project(client, "second")
    foreign = await client.get(
        f"/api/v1/projects/{first['id']}/demand/query-evidence/summary",
        params={
            "window_start": _WINDOW[0].isoformat(),
            "window_end": _WINDOW[1].isoformat(),
        },
    )
    assert second["workspace_id"] != first["workspace_id"]
    assert foreign.status_code == 404
