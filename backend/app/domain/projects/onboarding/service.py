"""Small orchestration layer for durable, failure-tolerant onboarding."""

from __future__ import annotations

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
from app.core.config.brand_profile import (
    BRAND_PROFILE_FIELDS,
    BRAND_PROFILE_REVIEW_UNREVIEWED,
    BRAND_PROFILE_SOURCE_AI_SUGGESTED,
)
from app.core.config.prompts import ONBOARDING_PROMPT_SET_NAME
from app.domain.projects.discovery_schemas import (
    BrandDiscoveryComplete,
    BrandDiscoveryCreate,
)
from app.domain.projects.onboarding.industry_library import (
    archetype_templates,
    industry_context,
    industry_names,
    subindustries_by_industry,
)
from app.domain.projects.onboarding.normalization import (
    InvalidWebsiteUrl,
    normalize_primary_market,
    normalize_website_url,
)
from app.domain.projects.onboarding.portfolio_generation import (
    generate_portfolio,
    portfolio_shortfall_warning,
)
from app.domain.projects.onboarding.prompt_generation import (
    fallback_portfolio,
    validated_portfolio,
)
from app.domain.projects.onboarding.prompt_validation import (
    BRAND_RELEVANT,
    MARKET_VISIBILITY,
    template_patterns,
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
from app.models.project import Project
from app.models.prompt import Prompt, PromptSet, Topic
from app.models.site_health.crawl import SiteCrawl

IDEMPOTENCY_KEY_REQUIRED = "Idempotency-Key is required"


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
        "prompt_cohorts": [MARKET_VISIBILITY, BRAND_RELEVANT],
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
    except ValueError as exc:
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
    row.prompt_suggestions = []
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
        prompts_prepared=0,
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


def _reviewed_profile_sources(confirmed: dict) -> dict[str, dict[str, str]]:
    """Record provenance for the brand-knowledge fields.

    None of these four are on the confirm screen any more -- it asks what you
    sell, who buys it and where, and the prose fields moved to the brand screen
    inside the app. So they cannot be stamped as reviewed: the client fills the
    empties from the confirmed category, and calling a generated string like
    "Buyers searching for ..." user-confirmed would make later consumers trust
    a sentence no user ever read. They stay AI-suggested and unreviewed until
    someone actually edits them where that work belongs.
    """
    return {
        field: {
            "origin": BRAND_PROFILE_SOURCE_AI_SUGGESTED,
            "review_state": BRAND_PROFILE_REVIEW_UNREVIEWED,
        }
        for field in BRAND_PROFILE_FIELDS
        if confirmed.get(field)
    }


async def _attach_research_source_artifacts(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    row: BrandDiscovery,
    project: Project,
    profile_sources: dict[str, dict[str, str]],
) -> None:
    research_snapshot_id = await session.scalar(
        select(BrandResearchSnapshot.id)
        .where(
            BrandResearchSnapshot.workspace_id == workspace_id,
            BrandResearchSnapshot.discovery_id == row.id,
        )
        .order_by(BrandResearchSnapshot.created_at.desc())
    )
    if research_snapshot_id and project.brand and project.brand.profile:
        project.brand.profile.source_artifact_ids = {
            field: str(research_snapshot_id) for field in profile_sources
        }


def _generated_topics(project_id: uuid.UUID, prompts: list[dict]) -> list[Topic]:
    names_by_key: dict[str, str] = {}
    for item in prompts:
        name = str(item["theme"])
        names_by_key.setdefault(name.casefold(), name)
    return [
        Topic(id=uuid.uuid4(), project_id=project_id, name=name, origin="generated")
        for name in names_by_key.values()
    ]


def _generated_prompts(
    *,
    prompt_set_id: uuid.UUID,
    discovery_id: uuid.UUID,
    prompts: list[dict],
    topics: list[Topic],
) -> list[Prompt]:
    topic_ids = {topic.name.casefold(): topic.id for topic in topics}
    return [
        Prompt(
            prompt_set_id=prompt_set_id,
            topic_id=topic_ids[str(item["theme"]).casefold()],
            text=str(item["text"]),
            theme=str(item["theme"]),
            intent=str(item["intent"]),
            cohort=str(item["cohort"]),
            branded=False,
            origin="generated",
            generation_evidence={
                "generator_version": BRAND_DISCOVERY_PROMPT_GENERATOR_VERSION,
                "discovery_id": str(discovery_id),
            },
        )
        for item in prompts
    ]


async def _persist_project(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    row: BrandDiscovery,
    payload: BrandDiscoveryComplete,
    prompts: list[dict],
    profile_sources: dict[str, dict[str, str]],
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
            business_context=_business_context(profile),
        ),
        commit=False,
        brand_profile_sources=profile_sources,
    )
    await _attach_research_source_artifacts(
        session,
        workspace_id=workspace_id,
        row=row,
        project=project,
        profile_sources=profile_sources,
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
    topics = _generated_topics(project.id, prompts)
    session.add_all(topics)
    prompt_rows = _generated_prompts(
        prompt_set_id=prompt_set.id,
        discovery_id=row.id,
        prompts=prompts,
        topics=topics,
    )
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
    reviewer_id: uuid.UUID,
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
        existing_crawl = (
            await session.get(SiteCrawl, row.initial_crawl_id)
            if row.initial_crawl_id is not None
            else None
        )
        return row, existing_crawl
    if row.status != DISCOVERY_STATUS_READY:
        raise BrandDiscoveryError("Discovery is not ready for completion")
    prompts, profile_sources = await _prepare_confirmed_portfolio(
        row, payload=payload, reviewer_id=reviewer_id
    )
    confirmed_profile = payload.profile.model_dump()
    row.profile = confirmed_profile
    row.topics = list(dict.fromkeys(str(item["theme"]) for item in prompts))
    row.prompt_suggestions = prompts
    row.input_data = {**row.input_data, "completion_idempotency_key": key}
    project_id = await _persist_project(
        session,
        workspace_id=workspace_id,
        row=row,
        payload=payload,
        prompts=prompts,
        profile_sources=profile_sources,
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

    return row, None


# The context fields that survive onboarding. `business_type` and `price_tier`
# were previously dropped on the floor at project creation -- collected, shown,
# confirmed, then silently discarded -- so every downstream consumer had to
# re-derive facts the user had already supplied.
_BUSINESS_CONTEXT_FIELDS = (
    "category",
    "category_aliases",
    "category_terms",
    "jobs_to_be_done",
    "sector",
    "business_model",
    "secondary_business_models",
    "market_scope",
    "buyer_register",
    "buyer_roles",
    "service_areas",
    "business_type",
    "price_tier",
    "knowledge_strength",
)


def _business_context(profile) -> dict:
    """Snapshot the confirmed context for persistence."""
    dumped = profile.model_dump()
    return {
        field: dumped[field] for field in _BUSINESS_CONTEXT_FIELDS if field in dumped
    }


async def _prepare_confirmed_portfolio(
    row: BrandDiscovery,
    *,
    payload: BrandDiscoveryComplete,
    reviewer_id: uuid.UUID,
) -> tuple[list[dict], dict[str, dict[str, str]]]:
    domains = _confirmed_domains(payload.domains)
    row.competitors = _confirmed_competitors(
        payload.competitors,
        brand_name=str(row.input_data["brand_name"]),
        owned_domains=domains,
    )
    row.domains = domains
    selected_industry, prompt_context = industry_context(
        str(row.input_data.get("industry") or "General")
    )
    competitor_terms = [
        term
        for competitor in row.competitors
        for term in [competitor["name"], *(competitor.get("aliases") or [])]
    ]
    context_terms = [
        payload.profile.target_audience,
        *payload.profile.products_services,
        *(prompt_context.get("use_cases") or []),
        *(prompt_context.get("topics") or []),
    ]
    fallback_prompts = fallback_portfolio(
        primary_market=str(row.input_data["primary_market"]),
        industry=selected_industry,
        industry_context=prompt_context,
        products_services=payload.profile.products_services,
        target_audience=payload.profile.target_audience,
        price_tier=payload.profile.price_tier,
    )
    # Ask the model to write the portfolio from the *confirmed* profile. The
    # templates below stay as the fallback for when that call fails; they are
    # also passed as banned patterns, so a model reply that merely reproduces a
    # template skeleton is rejected rather than accepted as "model-authored".
    brand_name = str(row.input_data["brand_name"])
    primary_market = str(row.input_data["primary_market"])
    model_prompts, shortfall_reason = await generate_portfolio(
        brand_name=brand_name,
        primary_market=primary_market,
        profile=payload.profile.model_dump(),
        competitors=[competitor["name"] for competitor in row.competitors],
    )
    prompts = validated_portfolio(
        model_prompts,
        fallback_prompts=fallback_prompts,
        brand_name=brand_name,
        primary_market=primary_market,
        competitor_terms=competitor_terms,
        context_terms=context_terms,
        banned_patterns=template_patterns(archetype_templates()),
    )
    shortfall = portfolio_shortfall_warning(len(prompts), shortfall_reason)
    if shortfall:
        row.warnings = list(dict.fromkeys([*(row.warnings or []), shortfall]))
    profile_sources = _reviewed_profile_sources(payload.profile.model_dump())
    return prompts, profile_sources
