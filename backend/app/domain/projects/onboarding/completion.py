"""Accepted onboarding completion and worker-side project creation."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.brand_discovery import (
    DISCOVERY_PROGRESS_TOTAL_STEPS,
    DISCOVERY_STATUS_COMPLETING,
    DISCOVERY_STATUS_PROJECT_CREATED,
    DISCOVERY_STATUS_READY,
    TASK_KIND_BRAND_COMPLETION,
)
from app.domain.projects.discovery_schemas import BrandDiscoveryComplete
from app.domain.projects.onboarding.service import (
    IDEMPOTENCY_KEY_REQUIRED,
    BrandDiscoveryError,
    _confirmed_portfolio_inputs,
    _generate_confirmed_portfolio,
    _persist_generated_prompts,
    _persist_project_shell,
    _progress,
    get_discovery,
)
from app.models.discovery import BrandDiscovery, BrandDiscoveryTask
from app.models.site_health.crawl import SiteCrawl


async def _completion_replay(
    session: AsyncSession,
    *,
    row: BrandDiscovery,
    idempotency_key: str,
) -> tuple[BrandDiscovery, SiteCrawl | None] | None:
    existing_key = str(row.input_data.get("completion_idempotency_key") or "")
    if not existing_key:
        return None
    if existing_key != idempotency_key:
        raise BrandDiscoveryError(
            "Discovery was completed with another Idempotency-Key"
        )
    if row.status == DISCOVERY_STATUS_COMPLETING:
        await _ensure_completion_task(session, row=row, workspace_id=row.workspace_id)
        await session.commit()
    existing_crawl = (
        await session.get(SiteCrawl, row.initial_crawl_id)
        if row.initial_crawl_id is not None
        else None
    )
    return row, existing_crawl


async def _ensure_completion_task(
    session: AsyncSession, *, row: BrandDiscovery, workspace_id: uuid.UUID
) -> None:
    task = await session.scalar(
        select(BrandDiscoveryTask)
        .where(
            BrandDiscoveryTask.discovery_id == row.id,
            BrandDiscoveryTask.task_kind == TASK_KIND_BRAND_COMPLETION,
        )
        .with_for_update()
    )
    if task is None:
        session.add(
            BrandDiscoveryTask(
                discovery_id=row.id,
                workspace_id=workspace_id,
                task_kind=TASK_KIND_BRAND_COMPLETION,
                idempotency_key=f"brand-completion:{row.id}",
            )
        )
        await session.flush()


async def complete_discovery(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    discovery_id: uuid.UUID,
    payload: BrandDiscoveryComplete,
    idempotency_key: str,
    reviewer_id: uuid.UUID,
) -> tuple[BrandDiscovery, SiteCrawl | None]:
    """Freeze a confirmed review and enqueue its portfolio generation."""
    key = idempotency_key.strip()
    if not key:
        raise BrandDiscoveryError(IDEMPOTENCY_KEY_REQUIRED)
    row = await get_discovery(
        session,
        workspace_id=workspace_id,
        discovery_id=discovery_id,
        for_update=True,
    )
    replay = await _completion_replay(session, row=row, idempotency_key=key)
    if replay is not None:
        return replay
    if row.status != DISCOVERY_STATUS_READY:
        raise BrandDiscoveryError("Discovery is not ready for completion")

    domains, competitors, topics, _, _, profile_sources = _confirmed_portfolio_inputs(
        row, payload=payload
    )
    row.domains = domains
    row.competitors = competitors
    row.profile = payload.profile.model_dump()
    row.topics = [topic.model_dump(mode="json") for topic in topics]
    row.input_data = {
        **row.input_data,
        "completion_idempotency_key": key,
        "completion_payload": payload.model_dump(mode="json"),
        "completion_reviewer_id": str(reviewer_id),
    }
    row.status = DISCOVERY_STATUS_COMPLETING
    row.stage = "generating_prompts"
    row.error_code = ""
    row.error_detail = ""
    row.project_id = await _persist_project_shell(
        session,
        workspace_id=workspace_id,
        row=row,
        payload=payload,
        discovery_topics=topics,
        profile_sources=profile_sources,
    )
    await _ensure_completion_task(session, row=row, workspace_id=workspace_id)
    await session.commit()
    return row, None


async def run_completion(session: AsyncSession, row: BrandDiscovery) -> None:
    """Generate the accepted portfolio and fill its committed project shell."""
    workspace_id = row.workspace_id
    discovery_id = row.id
    payload = BrandDiscoveryComplete.model_validate(
        row.input_data.get("completion_payload") or {}
    )
    (
        domains,
        competitors,
        topics,
        brand_name,
        primary_market,
        _,
    ) = _confirmed_portfolio_inputs(row, payload=payload)
    await session.commit()

    prompts, provider, model, warnings = await _generate_confirmed_portfolio(
        payload=payload,
        topics=topics,
        brand_name=brand_name,
        primary_market=primary_market,
        competitors=competitors,
        domains=domains,
    )
    row = await get_discovery(
        session,
        workspace_id=workspace_id,
        discovery_id=discovery_id,
        for_update=True,
    )
    if row.status == DISCOVERY_STATUS_PROJECT_CREATED:
        return
    row.domains = domains
    row.competitors = competitors
    row.profile = payload.profile.model_dump()
    row.topics = [topic.model_dump(mode="json") for topic in topics]
    row.prompt_suggestions = prompts
    row.warnings = list(dict.fromkeys([*row.warnings, *warnings]))
    await _persist_generated_prompts(
        session,
        workspace_id=workspace_id,
        row=row,
        prompts=prompts,
        prompt_provider=provider,
        prompt_model=model,
    )
    row.status = DISCOVERY_STATUS_PROJECT_CREATED
    row.stage = "complete"
    row.progress = _progress(
        phase="complete",
        completed_steps=DISCOVERY_PROGRESS_TOTAL_STEPS,
        competitors_found=len(row.competitors),
        prompts_prepared=len(prompts),
        previous=row.progress,
    )
    await session.commit()
