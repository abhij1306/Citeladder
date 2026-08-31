"""Accepted onboarding completion and worker-side project creation."""

from __future__ import annotations

import uuid
from time import perf_counter

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.brand_discovery import (
    DISCOVERY_PROGRESS_TOTAL_STEPS,
    DISCOVERY_STATUS_COMPLETING,
    DISCOVERY_STATUS_PROJECT_CREATED,
    DISCOVERY_STATUS_READY,
    TASK_KIND_BRAND_COMPLETION,
    brand_discovery_settings,
)
from app.domain.projects.discovery_schemas import (
    BrandDiscoveryComplete,
    DiscoveryTopic,
)
from app.domain.projects.offering_harvest import OfferingHarvest, OfferingNode
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
from app.domain.projects.onboarding.topic_admission import confirmed_offering_topics
from app.domain.projects.onboarding.topic_selection import select_topics
from app.models.discovery import (
    BrandDiscovery,
    BrandDiscoveryTask,
    BrandResearchSnapshot,
)
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

    domains, competitors, _, _, _, profile_sources = _confirmed_portfolio_inputs(
        row, payload=payload
    )
    topics: list[DiscoveryTopic] = []
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
        _,
        brand_name,
        primary_market,
        _,
    ) = _confirmed_portfolio_inputs(row, payload=payload)
    harvest, page_evidence = await _topic_context(session, row=row)
    await session.commit()

    topic_started = perf_counter()
    topic_selection = await select_topics(
        brand_name=brand_name,
        brand_aliases=[],
        competitors=[str(item["name"]) for item in competitors],
        business_category=payload.profile.category,
        business_aliases=[
            *payload.profile.category_aliases,
            *payload.profile.category_options,
        ],
        sector=payload.profile.sector,
        business_model=payload.profile.business_model,
        market=primary_market,
        harvest=harvest,
        page_evidence=page_evidence,
        allow_model_prior=payload.profile.has_reliable_prior(),
    )
    topic_duration_ms = int((perf_counter() - topic_started) * 1000)
    topics = topic_selection.topics or confirmed_offering_topics(
        payload.profile.products_services
    )
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
    row.warnings = list(
        dict.fromkeys([*row.warnings, *topic_selection.warnings, *warnings])
    )
    await _persist_generated_prompts(
        session,
        workspace_id=workspace_id,
        row=row,
        prompts=prompts,
        discovery_topics=topics,
        prompt_provider=provider,
        prompt_model=model,
        topic_provider=topic_selection.provider,
        topic_model=topic_selection.model,
        topic_duration_ms=topic_duration_ms,
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


async def _topic_context(
    session: AsyncSession, *, row: BrandDiscovery
) -> tuple[OfferingHarvest, list[dict[str, str]]]:
    fields = await _research_fields(session, row=row)
    return (
        _offering_harvest(fields.get("offerings")),
        _page_evidence(fields.get("evidence_manifest")),
    )


async def _research_fields(session: AsyncSession, *, row: BrandDiscovery) -> dict:
    snapshot = await session.scalar(
        select(BrandResearchSnapshot)
        .where(
            BrandResearchSnapshot.workspace_id == row.workspace_id,
            BrandResearchSnapshot.discovery_id == row.id,
        )
        .order_by(BrandResearchSnapshot.created_at.desc())
    )
    if snapshot is None or not isinstance(snapshot.extracted_fields, dict):
        return {}
    return snapshot.extracted_fields


def _offering_harvest(value: object) -> OfferingHarvest:
    items = value if isinstance(value, list) else []
    return OfferingHarvest(
        nodes=tuple(
            OfferingNode(
                ref=str(item.get("ref") or ""),
                label=str(item.get("label") or ""),
                path=str(item.get("path") or ""),
            )
            for item in items
            if isinstance(item, dict)
            and item.get("ref")
            and item.get("label")
            and item.get("path")
        )
    )


def _page_evidence(value: object) -> list[dict[str, str]]:
    items = value if isinstance(value, list) else []
    return [
        {
            "evidence_ref": str(item.get("evidence_ref") or ""),
            "url": str(item.get("source_url") or ""),
            "title": str(item.get("title") or ""),
            "text": str(item.get("text") or "")[
                : brand_discovery_settings.topic_evidence_max_chars_per_page
            ],
        }
        for item in items
        if isinstance(item, dict)
        and item.get("source_kind") == "first_party"
        and item.get("evidence_ref")
    ]
