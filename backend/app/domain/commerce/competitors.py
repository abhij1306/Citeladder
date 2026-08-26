"""Optional competitor discovery, deterministic validation, and decisions."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.commerce_competitors import (
    CompetitorProviderUnavailable,
    tavily_search,
)
from app.connectors.web_evidence.contracts import FetchError, FetchRequest
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.resolver import SystemDnsResolver
from app.core.config.commerce_catalog import (
    COMMERCE_COMPETITOR_EXCLUDED_PATH_TOKENS,
    COMMERCE_COMPETITOR_RESULT_LIMIT,
    COMMERCE_SECOND_HAND_TOKENS,
)
from app.core.config.site_health_acquisition import FETCH_PURPOSE_ANALYZE
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.domain.commerce.schemas import (
    CommerceTarget,
    CompetitorCandidateResponse,
    DiscoveryResponse,
)
from app.domain.commerce.service import CommerceNotFoundError, require_project
from app.domain.site_health.normalization import canonical_identity
from app.models.analytics import AnalyticsTask
from app.models.brand import OwnedDomain
from app.models.commerce import (
    CommerceCategory,
    CommerceCompetitorAttempt,
    CommerceCompetitorCandidate,
    CommerceProduct,
)
from app.models.project import Project


def _utcnow() -> datetime:
    return datetime.now(UTC)


async def _target_name(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    target: CommerceTarget,
) -> str:
    model = CommerceCategory if target.kind == "category" else CommerceProduct
    row = await session.scalar(
        select(model).where(
            model.id == target.id,
            model.workspace_id == workspace_id,
            model.project_id == project_id,
        )
    )
    if row is None:
        raise CommerceNotFoundError(f"Commerce {target.kind} not found")
    return str(row.name if isinstance(row, (CommerceCategory, CommerceProduct)) else "")


async def enqueue_discoveries(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    targets: list[CommerceTarget],
) -> DiscoveryResponse:
    project = await require_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    task_ids: list[uuid.UUID] = []
    locale = "-".join(
        value for value in (project.language_code, project.country_code) if value
    )
    for target in targets:
        name = await _target_name(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            target=target,
        )
        key = f"commerce:competitors:{target.kind}:{target.id}"
        task = await session.scalar(
            select(AnalyticsTask).where(AnalyticsTask.idempotency_key == key)
        )
        if task is None:
            task = AnalyticsTask(
                workspace_id=workspace_id,
                project_id=project_id,
                task_kind="commerce_competitor_discovery",
                payload={
                    "target": target.model_dump(mode="json"),
                    "target_name": name,
                    "locale": locale,
                },
                idempotency_key=key,
                status=TASK_STATUS_QUEUED,
            )
            session.add(task)
            await session.flush()
        task_ids.append(task.id)
    await session.commit()
    return DiscoveryResponse(task_ids=task_ids)


async def list_candidates(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> list[CompetitorCandidateResponse]:
    await require_project(session, workspace_id=workspace_id, project_id=project_id)
    rows = list(
        (
            await session.scalars(
                select(CommerceCompetitorCandidate)
                .where(
                    CommerceCompetitorCandidate.workspace_id == workspace_id,
                    CommerceCompetitorCandidate.project_id == project_id,
                )
                .order_by(CommerceCompetitorCandidate.created_at.desc())
            )
        ).all()
    )
    return [CompetitorCandidateResponse.model_validate(row) for row in rows]


async def decide_candidate(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    candidate_id: uuid.UUID,
    decision: str,
) -> CompetitorCandidateResponse:
    row = await session.scalar(
        select(CommerceCompetitorCandidate).where(
            CommerceCompetitorCandidate.id == candidate_id,
            CommerceCompetitorCandidate.workspace_id == workspace_id,
            CommerceCompetitorCandidate.project_id == project_id,
        )
    )
    if row is None:
        raise CommerceNotFoundError("Competitor candidate not found")
    row.state = decision
    row.decision_at = _utcnow()
    await session.commit()
    return CompetitorCandidateResponse.model_validate(row)


def _host(value: str) -> str:
    return (urlsplit(value).hostname or "").casefold().removeprefix("www.")


def _owned(host: str, owned_hosts: set[str]) -> bool:
    return any(host == value or host.endswith(f".{value}") for value in owned_hosts)


async def _owned_hosts(session: AsyncSession, *, project: Project) -> set[str]:
    values = set(
        await session.scalars(
            select(OwnedDomain.domain).where(OwnedDomain.project_id == project.id)
        )
    )
    values.add(_host(project.website_url))
    return {value for value in values if value}


def _precheck(
    item: dict[str, Any], *, owned_hosts: set[str]
) -> tuple[str, str, str] | None:
    raw_url = str(item.get("url") or "").strip()
    title = str(item.get("title") or "").strip()
    if not raw_url or not title:
        return None
    try:
        canonical = canonical_identity(raw_url)[0]
    except (TypeError, ValueError):
        return None
    lowered = f"{canonical} {title}".casefold()
    if _owned(_host(canonical), owned_hosts):
        return None
    if any(token in lowered for token in COMMERCE_COMPETITOR_EXCLUDED_PATH_TOKENS):
        return None
    if any(token in lowered for token in COMMERCE_SECOND_HAND_TOKENS):
        return None
    return canonical, title, str(item.get("content") or "")[:1000]


async def _verify_url(url: str) -> bool:
    request = FetchRequest(url=url, purpose=FETCH_PURPOSE_ANALYZE)
    try:
        async with SecureFetcher(resolver=SystemDnsResolver()) as fetcher:
            result = await fetcher.fetch(request, enforce_scope=False)
    except FetchError:
        return False
    return 200 <= result.status_code < 400 and bool(
        result.content_type.startswith("text/html")
    )


async def run_competitor_discovery(session_factory, task: AnalyticsTask) -> None:
    if task.project_id is None:
        raise ValueError("Commerce discovery task has no project")
    payload = dict(task.payload or {})
    target = CommerceTarget.model_validate(payload.get("target"))
    query = f"alternatives to {payload.get('target_name') or ''} product"
    locale = str(payload.get("locale") or "")
    status, error_code, results = await _provider_results(query, locale=locale)
    async with session_factory() as session:
        await _persist_discovery(
            session,
            task=task,
            target=target,
            query=query,
            locale=locale,
            status=status,
            error_code=error_code,
            results=results,
        )


async def _provider_results(
    query: str, *, locale: str
) -> tuple[str, str, list[dict[str, Any]]]:
    try:
        return "succeeded", "", await tavily_search(query, locale=locale)
    except CompetitorProviderUnavailable:
        return "unavailable", "provider_unavailable", []
    except Exception:
        return "failed", "provider_failed", []


async def _persist_discovery(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    target: CommerceTarget,
    query: str,
    locale: str,
    status: str,
    error_code: str,
    results: list[dict[str, Any]],
) -> None:
    if task.project_id is None:
        raise ValueError("Commerce discovery task has no project")
    project = await require_project(
        session, workspace_id=task.workspace_id, project_id=task.project_id
    )
    attempt_number = (
        int(
            await session.scalar(
                select(func.count()).where(CommerceCompetitorAttempt.task_id == task.id)
            )
        )
        or 0
    ) + 1
    attempt = CommerceCompetitorAttempt(
        workspace_id=task.workspace_id,
        project_id=task.project_id,
        task_id=task.id,
        target_kind=target.kind,
        target_id=target.id,
        attempt_number=attempt_number,
        query=query,
        locale=locale,
        status=status,
        result_payload=results,
        error_code=error_code,
    )
    session.add(attempt)
    await session.flush()
    if status == "succeeded":
        survivors = await _validated_survivors(
            results, owned_hosts=await _owned_hosts(session, project=project)
        )
        await _add_candidates(
            session, task=task, target=target, attempt=attempt, rows=survivors
        )
    await session.commit()


async def _validated_survivors(
    results: list[dict[str, Any]], *, owned_hosts: set[str]
) -> list[tuple[str, str, str]]:
    survivors: list[tuple[str, str, str]] = []
    for item in results:
        checked = _precheck(item, owned_hosts=owned_hosts)
        duplicate = checked is not None and any(
            checked[0] == row[0] for row in survivors
        )
        if checked is not None and not duplicate and await _verify_url(checked[0]):
            survivors.append(checked)
        if len(survivors) >= COMMERCE_COMPETITOR_RESULT_LIMIT:
            break
    return survivors


async def _add_candidates(
    session: AsyncSession,
    *,
    task: AnalyticsTask,
    target: CommerceTarget,
    attempt: CommerceCompetitorAttempt,
    rows: list[tuple[str, str, str]],
) -> None:
    for url, title, content in rows:
        existing = await session.scalar(
            select(CommerceCompetitorCandidate.id).where(
                CommerceCompetitorCandidate.project_id == task.project_id,
                CommerceCompetitorCandidate.target_kind == target.kind,
                CommerceCompetitorCandidate.target_id == target.id,
                CommerceCompetitorCandidate.canonical_url == url,
            )
        )
        if existing is None:
            session.add(
                CommerceCompetitorCandidate(
                    workspace_id=task.workspace_id,
                    project_id=task.project_id,
                    attempt_id=attempt.id,
                    target_kind=target.kind,
                    target_id=target.id,
                    canonical_url=url,
                    product_name=title,
                    evidence={"search_excerpt": content},
                )
            )
