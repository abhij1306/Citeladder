"""Small orchestration layer for durable, failure-tolerant onboarding."""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.brand_discovery import (
    BRAND_DISCOVERY_PROMPT_GENERATOR_VERSION,
    BRAND_DISCOVERY_VERSION,
    BUSINESS_TYPES,
    CAPTURE_METHOD_APPLICATION_MODEL,
    CAPTURE_METHOD_CRAWLER,
    CAPTURE_METHOD_USER,
    DISCOVERY_PROGRESS_TOTAL_STEPS,
    DISCOVERY_STATUS_FAILED,
    DISCOVERY_STATUS_PROJECT_CREATED,
    DISCOVERY_STATUS_READY,
    PRICE_TIERS,
    brand_discovery_settings,
)
from app.core.config.prompts import ONBOARDING_PROMPT_SET_NAME
from app.domain.projects.activation import start_initial_site_review
from app.domain.projects.discovery_schemas import (
    BrandDiscoveryComplete,
    BrandDiscoveryCreate,
)
from app.domain.projects.onboarding.industry_library import (
    industry_context,
    industry_names,
    subindustries_by_industry,
)
from app.domain.projects.onboarding.normalization import (
    InvalidWebsiteUrl,
    normalize_primary_market,
    normalize_website_url,
)
from app.domain.projects.onboarding.prompt_validation import (
    BRAND_DIAGNOSTIC,
    MARKET_VISIBILITY,
    validate_portfolio,
)
from app.domain.projects.onboarding.research import research_brand
from app.domain.projects.onboarding.site_resolution import (
    SiteNotFoundError,
    resolve_site,
)
from app.domain.projects.schemas import BrandInput, CompetitorInput, ProjectCreate
from app.domain.projects.service import create_project
from app.domain.prompts.service import prepare_prompt_inserts
from app.models.discovery import (
    BrandDiscovery,
    BrandDiscoveryTask,
    BrandResearchSnapshot,
)
from app.models.prompt import Prompt, PromptSet, Topic
from app.models.site_health import SiteCrawl

IDEMPOTENCY_KEY_REQUIRED = "Idempotency-Key is required"
logger = logging.getLogger(__name__)


class BrandDiscoveryError(ValueError):
    pass


def _progress(
    *,
    phase: str,
    completed_steps: int,
    pages_read: int = 0,
    competitors_found: int = 0,
    prompts_prepared: int = 0,
    previous: dict | None = None,
) -> dict:
    prior = previous or {}
    return {
        "phase": phase,
        "completed_steps": min(
            DISCOVERY_PROGRESS_TOTAL_STEPS,
            max(completed_steps, int(prior.get("completed_steps") or 0)),
        ),
        "total_steps": DISCOVERY_PROGRESS_TOTAL_STEPS,
        "pages_read": max(pages_read, int(prior.get("pages_read") or 0)),
        "competitors_found": max(
            competitors_found, int(prior.get("competitors_found") or 0)
        ),
        "prompts_prepared": max(
            prompts_prepared, int(prior.get("prompts_prepared") or 0)
        ),
        "updated_at": datetime.now(UTC).isoformat(),
    }


def discovery_catalog() -> dict[str, object]:
    return {
        "business_types": list(BUSINESS_TYPES),
        "price_tiers": list(PRICE_TIERS),
        "required_fields": ["brand_name", "website_url", "primary_market"],
        "optional_fields": ["industry", "subindustry", "language_code"],
        "capture_methods": [
            CAPTURE_METHOD_CRAWLER,
            CAPTURE_METHOD_APPLICATION_MODEL,
            CAPTURE_METHOD_USER,
        ],
        "maximum_competitors": brand_discovery_settings.maximum_competitors,
        "industries": industry_names(),
        "subindustries": subindustries_by_industry(),
        "prompt_cohorts": [MARKET_VISIBILITY, BRAND_DIAGNOSTIC],
    }


async def create_discovery(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    payload: BrandDiscoveryCreate,
    idempotency_key: str,
) -> BrandDiscovery:
    key = idempotency_key.strip()
    if not key:
        raise BrandDiscoveryError(IDEMPOTENCY_KEY_REQUIRED)
    existing = await session.scalar(
        select(BrandDiscovery).where(
            BrandDiscovery.workspace_id == workspace_id,
            BrandDiscovery.idempotency_key == key,
        )
    )
    if existing is not None:
        return existing
    try:
        primary_market = normalize_primary_market(payload.primary_market)
        normalized_url, _ = normalize_website_url(payload.website_url)
    except (InvalidWebsiteUrl, ValueError) as exc:
        raise BrandDiscoveryError(str(exc)) from exc
    requested_industry = payload.industry.strip()
    if requested_industry and requested_industry not in industry_names():
        raise BrandDiscoveryError("industry is not supported")
    selected_industry, context = industry_context(requested_industry)
    subindustry = payload.subindustry.strip() if selected_industry != "General" else ""
    allowed_subindustries = set(context.get("subindustries") or [])
    if subindustry and subindustry not in allowed_subindustries:
        raise BrandDiscoveryError("subindustry is not valid for the selected industry")
    row = BrandDiscovery(
        workspace_id=workspace_id,
        input_data={
            **payload.model_dump(),
            "website_url": normalized_url,
            "industry": selected_industry,
            "subindustry": subindustry,
            "primary_market": primary_market,
            "discovery_version": BRAND_DISCOVERY_VERSION,
        },
        idempotency_key=key,
        stage="queued",
        progress=_progress(phase="opening_website", completed_steps=0),
    )
    session.add(row)
    await session.flush()
    session.add(
        BrandDiscoveryTask(
            discovery_id=row.id,
            workspace_id=workspace_id,
            idempotency_key=f"brand-discovery:{row.id}",
        )
    )
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        replay = await session.scalar(
            select(BrandDiscovery).where(
                BrandDiscovery.workspace_id == workspace_id,
                BrandDiscovery.idempotency_key == key,
            )
        )
        if replay is not None:
            return replay
        raise
    await session.refresh(row)
    return row


async def get_discovery(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    discovery_id: uuid.UUID,
    for_update: bool = False,
) -> BrandDiscovery:
    statement = select(BrandDiscovery).where(
        BrandDiscovery.id == discovery_id,
        BrandDiscovery.workspace_id == workspace_id,
    )
    if for_update:
        statement = statement.with_for_update()
    row = await session.scalar(statement)
    if row is None:
        raise LookupError("Brand discovery not found")
    return row


async def process_discovery(session: AsyncSession, row: BrandDiscovery) -> None:
    """Resolve one site and always reach review unless URL/site existence fails."""
    data = dict(row.input_data)
    try:
        normalized_url, _ = normalize_website_url(str(data["website_url"]))
        site = await resolve_site(str(data["website_url"]), normalized_url)
    except InvalidWebsiteUrl:
        row.status = DISCOVERY_STATUS_FAILED
        row.stage = "failed"
        row.error_code = "invalid_url"
        row.error_detail = "The website URL is invalid"
        await session.commit()
        return
    except SiteNotFoundError:
        row.status = DISCOVERY_STATUS_FAILED
        row.stage = "failed"
        row.error_code = "site_not_found"
        row.error_detail = "The website could not be resolved"
        await session.commit()
        return
    row.input_data = {**data, "website_url": site.canonical_url}
    row.domains = [site.registrable_domain]
    row.progress = _progress(
        phase="understanding_business",
        completed_steps=1,
        pages_read=1,
        previous=row.progress,
    )
    await session.commit()

    selected_industry, context = industry_context(
        str(data.get("industry") or "General")
    )
    result = await research_brand(
        brand_name=str(data["brand_name"]),
        primary_market=str(data["primary_market"]),
        industry=selected_industry,
        subindustry=str(data.get("subindustry") or ""),
        language_code=str(data.get("language_code") or "en"),
        site=site,
        industry_context=context,
    )
    row.profile = result.profile
    row.competitors = result.competitors
    row.topics = result.topics
    row.prompt_suggestions = result.prompts
    row.evidence = result.evidence
    row.warnings = result.warnings
    row.gaps = []
    row.error_code = ""
    row.error_detail = ""
    row.status = DISCOVERY_STATUS_READY
    row.stage = "review"
    row.progress = _progress(
        phase="preparing_review",
        completed_steps=DISCOVERY_PROGRESS_TOTAL_STEPS - 1,
        pages_read=1,
        competitors_found=len(result.competitors),
        prompts_prepared=len(result.prompts),
        previous=row.progress,
    )
    session.add(
        BrandResearchSnapshot(
            workspace_id=row.workspace_id,
            discovery_id=row.id,
            research_version=BRAND_DISCOVERY_VERSION,
            provider=result.provider,
            model=result.model,
            method="direct_homepage+structured_model+industry_fallback",
            extracted_fields={
                "profile": result.profile,
                "competitors": result.competitors,
                "topics": result.topics,
                "prompts": result.prompts,
            },
            field_confidence=result.profile.get("field_confidence", {}),
            evidence=result.evidence,
            warnings=result.warnings,
        )
    )
    await session.commit()


def _confirmed_domains(values: list[str]) -> list[str]:
    domains: list[str] = []
    for value in values:
        try:
            _, domain = normalize_website_url(value)
        except InvalidWebsiteUrl as exc:
            raise BrandDiscoveryError(
                "Confirmed domains must be public domains"
            ) from exc
        domains.append(domain)
    return list(dict.fromkeys(domains))


def _confirmed_competitors(
    items: list[CompetitorInput], *, brand_name: str, owned_domains: list[str]
) -> list[dict]:
    confirmed: list[dict] = []
    seen: set[str] = set()
    for item in items:
        key = item.name.strip().casefold()
        if key == brand_name.strip().casefold() or key in seen:
            raise BrandDiscoveryError(
                "Competitors must be unique and distinct from the brand"
            )
        domains = _confirmed_domains(item.domains)
        if set(domains).intersection(owned_domains):
            raise BrandDiscoveryError("A competitor cannot use an owned domain")
        seen.add(key)
        confirmed.append(item.model_copy(update={"domains": domains}).model_dump())
    return confirmed


def _reviewed_prompts(
    payload: BrandDiscoveryComplete,
    *,
    brand_name: str,
    primary_market: str,
    competitors: list[dict],
    context_terms: list[str],
) -> list[dict]:
    prompts = [
        {**prompt.model_dump(), "theme": group.topic}
        for group in payload.prompt_groups
        for prompt in group.prompts
    ]
    quality = validate_portfolio(
        prompts,
        brand_terms=[brand_name],
        competitor_terms=[
            term
            for competitor in competitors
            for term in [competitor["name"], *(competitor.get("aliases") or [])]
        ],
        primary_market=primary_market,
        context_terms=context_terms,
    )
    if quality.errors:
        raise BrandDiscoveryError(
            "Reviewed prompt portfolio must contain five neutral market and "
            "five branded diagnostic questions"
        )
    return list(quality.accepted)


async def _persist_project(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    row: BrandDiscovery,
    payload: BrandDiscoveryComplete,
    prompts: list[dict],
) -> uuid.UUID:
    data = row.input_data
    profile = payload.profile
    project = await create_project(
        session,
        workspace_id=workspace_id,
        payload=ProjectCreate(
            name=payload.name or str(data["brand_name"]),
            brand_name=str(data["brand_name"]),
            brand=BrandInput(),
            website_url=str(data["website_url"]),
            industry=str(data["industry"]),
            subindustry=str(data.get("subindustry") or ""),
            primary_market=str(data["primary_market"]),
            owned_domains=list(row.domains),
            competitors=[CompetitorInput(**item) for item in row.competitors],
            country_code=str(data["primary_market"]),
            language_code=str(data.get("language_code") or "en"),
            description=profile.description,
            positioning=profile.positioning,
            products_services=profile.products_services,
            target_audience=profile.target_audience,
        ),
        commit=False,
    )
    prompt_set = PromptSet(
        id=uuid.uuid4(), project_id=project.id, name=ONBOARDING_PROMPT_SET_NAME
    )
    session.add(prompt_set)
    approved_hashes = await prepare_prompt_inserts(
        session,
        workspace_id=workspace_id,
        prompt_set_id=prompt_set.id,
        texts=[str(item["text"]) for item in prompts],
    )
    topic_names_by_key: dict[str, str] = {}
    for item in prompts:
        name = str(item["theme"])
        topic_names_by_key.setdefault(name.casefold(), name)
    topic_names = list(topic_names_by_key.values())
    topics = [
        Topic(id=uuid.uuid4(), project_id=project.id, name=name, origin="generated")
        for name in topic_names
    ]
    session.add_all(topics)
    topic_ids = {item.name.casefold(): item.id for item in topics}
    prompt_rows = [
        Prompt(
            prompt_set_id=prompt_set.id,
            topic_id=topic_ids[str(item["theme"]).casefold()],
            text=str(item["text"]),
            theme=str(item["theme"]),
            intent=str(item["intent"]),
            cohort=str(item["cohort"]),
            branded=item["cohort"] == BRAND_DIAGNOSTIC,
            origin="generated",
            generation_evidence={
                "generator_version": BRAND_DISCOVERY_PROMPT_GENERATOR_VERSION,
                "discovery_id": str(row.id),
            },
        )
        for item in prompts
    ]
    retained = [
        item for item in prompt_rows if item.normalized_text_hash in approved_hashes
    ]
    if len(retained) != len(prompts):
        raise BrandDiscoveryError("Reviewed prompts must remain unique")
    session.add_all(retained)
    return project.id


async def complete_discovery(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    discovery_id: uuid.UUID,
    payload: BrandDiscoveryComplete,
    idempotency_key: str,
) -> tuple[BrandDiscovery, SiteCrawl | None]:
    key = idempotency_key.strip()
    if not key:
        raise BrandDiscoveryError(IDEMPOTENCY_KEY_REQUIRED)
    row = await get_discovery(
        session,
        workspace_id=workspace_id,
        discovery_id=discovery_id,
        for_update=True,
    )
    existing_key = str(row.input_data.get("completion_idempotency_key") or "")
    if existing_key:
        if existing_key != key:
            raise BrandDiscoveryError(
                "Discovery was completed with another Idempotency-Key"
            )
        crawl = (
            await session.get(SiteCrawl, row.initial_crawl_id)
            if row.initial_crawl_id is not None
            else None
        )
        return row, crawl
    if row.status != DISCOVERY_STATUS_READY:
        raise BrandDiscoveryError("Discovery is not ready for completion")
    domains = _confirmed_domains(payload.domains)
    row.competitors = _confirmed_competitors(
        payload.competitors,
        brand_name=str(row.input_data["brand_name"]),
        owned_domains=domains,
    )
    row.domains = domains
    _, prompt_context = industry_context(
        str(row.input_data.get("industry") or "General")
    )
    prompts = _reviewed_prompts(
        payload,
        brand_name=str(row.input_data["brand_name"]),
        primary_market=str(row.input_data["primary_market"]),
        competitors=row.competitors,
        context_terms=[
            *payload.profile.products_services,
            *(prompt_context.get("use_cases") or []),
            *(prompt_context.get("topics") or []),
        ],
    )
    row.profile = payload.profile.model_dump()
    row.topics = list(dict.fromkeys(str(item["theme"]) for item in prompts))
    row.prompt_suggestions = prompts
    row.input_data = {**row.input_data, "completion_idempotency_key": key}
    project_id = await _persist_project(
        session,
        workspace_id=workspace_id,
        row=row,
        payload=payload,
        prompts=prompts,
    )
    row.project_id = project_id
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

    crawl: SiteCrawl | None = None
    try:
        crawl = await start_initial_site_review(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
        )
        row = await get_discovery(
            session,
            workspace_id=workspace_id,
            discovery_id=discovery_id,
            for_update=True,
        )
        row.initial_crawl_id = crawl.id
        await session.commit()
    except Exception:
        logger.exception(
            "Initial Site Health review deferred after onboarding",
            extra={"discovery_id": str(discovery_id), "project_id": str(project_id)},
        )
        await session.rollback()
        row = await get_discovery(
            session,
            workspace_id=workspace_id,
            discovery_id=discovery_id,
            for_update=True,
        )
        row.warnings = list(dict.fromkeys([*row.warnings, "site_health_deferred"]))
        await session.commit()
    return row, crawl
