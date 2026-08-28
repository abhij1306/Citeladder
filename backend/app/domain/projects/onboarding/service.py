"""Small orchestration layer for durable, failure-tolerant onboarding."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.brand_discovery import (
    BRAND_DISCOVERY_PROMPT_GENERATOR_VERSION,
    BRAND_DISCOVERY_PROMPT_VALIDATION_VERSION,
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
from app.core.config.prompts import (
    ONBOARDING_PROMPT_SET_NAME,
    PROMPT_COHORT_BRAND_DIAGNOSTIC,
    PROMPT_COHORT_COMPARISON,
    PROMPT_COHORT_CORE,
)
from app.core.config.visibility_prompts import (
    BUYER_QUERY_ARCHETYPE_VERSION,
    VISIBILITY_TOPIC_MAX,
)
from app.domain.projects.discovery_schemas import (
    BrandDiscoveryComplete,
    BrandDiscoveryCreate,
    DiscoveryProfile,
    DiscoveryTopic,
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
from app.domain.projects.onboarding.portfolio_generation import (
    generate_portfolio,
)
from app.domain.projects.onboarding.research import research_brand
from app.domain.projects.onboarding.site_resolution import (
    SiteNotFoundError,
    resolve_site,
)
from app.domain.projects.onboarding.topic_admission import confirmed_offering_topics
from app.domain.projects.schemas import BrandInput, CompetitorInput, ProjectCreate
from app.domain.projects.service import create_project
from app.domain.prompts.portfolio_validation import brand_terms
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
        "prompt_cohorts": [
            PROMPT_COHORT_CORE,
            PROMPT_COHORT_BRAND_DIAGNOSTIC,
            PROMPT_COHORT_COMPARISON,
        ],
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

    selected_industry, _context = industry_context(
        str(data.get("industry") or "General")
    )

    async def _finding_competitors() -> None:
        row.progress = _progress(
            phase="finding_competitors",
            completed_steps=2,
            previous=row.progress,
        )
        await session.commit()

    result = await research_brand(
        brand_name=str(data["brand_name"]),
        primary_market=str(data["primary_market"]),
        industry=selected_industry,
        subindustry=str(data.get("subindustry") or ""),
        language_code=str(data.get("language_code") or "en"),
        site=site,
        on_competitor_phase=_finding_competitors,
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
        pages_read=result.pages_read,
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
            method="first_party+keenable+structured_models",
            extracted_fields={
                "profile": result.profile,
                "competitive_signature": result.competitive_signature,
                "competitors": result.competitors,
                "competitor_verdicts": result.competitor_verdicts,
                "topics": result.topics,
                "offerings": result.offerings,
                "evidence_manifest": result.evidence_manifest,
                "model_calls": result.model_calls,
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
) -> uuid.UUID | None:
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
    return research_snapshot_id


def _generated_topics(
    project_id: uuid.UUID, discovery_topics: list[DiscoveryTopic]
) -> list[Topic]:
    return [
        Topic(
            id=topic.topic_id,
            project_id=project_id,
            name=topic.name,
            description=topic.description,
            origin="generated",
        )
        for topic in discovery_topics
    ]


def _generated_prompts(
    *,
    prompt_set_id: uuid.UUID,
    discovery_id: uuid.UUID,
    prompts: list[dict],
    topics: list[Topic],
    provider: str,
    model: str,
    research_snapshot_id: uuid.UUID | None,
) -> list[Prompt]:
    topics_by_id = {str(topic.id): topic for topic in topics}
    generated: list[Prompt] = []
    for item in prompts:
        topic = topics_by_id.get(str(item["topic_id"]))
        generated.append(
            Prompt(
                prompt_set_id=prompt_set_id,
                topic_id=topic.id if topic else None,
                text=str(item["text"]),
                theme=topic.name if topic else "",
                intent=str(item["intent"]),
                buyer_stage=str(item.get("buyer_stage") or ""),
                prompt_intent=str(item.get("prompt_intent") or ""),
                cohort=str(item["cohort"]),
                branded=str(item["cohort"]) != PROMPT_COHORT_CORE,
                origin="generated",
                generation_evidence={
                    "generator_version": BRAND_DISCOVERY_PROMPT_GENERATOR_VERSION,
                    "buyer_query_archetype_version": BUYER_QUERY_ARCHETYPE_VERSION,
                    "buyer_query_archetype": str(item.get("archetype") or ""),
                    "buyer_query_slot_id": str(item.get("slot_id") or ""),
                    "discovery_id": str(discovery_id),
                    "provider": provider,
                    "model": model,
                    "research_snapshot_id": (
                        str(research_snapshot_id) if research_snapshot_id else None
                    ),
                    "validation_version": BRAND_DISCOVERY_PROMPT_VALIDATION_VERSION,
                },
            )
        )
    return generated


async def _persist_project(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    row: BrandDiscovery,
    payload: BrandDiscoveryComplete,
    prompts: list[dict],
    discovery_topics: list[DiscoveryTopic],
    prompt_provider: str,
    prompt_model: str,
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
    research_snapshot_id = await _attach_research_source_artifacts(
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
    topics = _generated_topics(project.id, discovery_topics)
    session.add_all(topics)
    prompt_rows = _generated_prompts(
        prompt_set_id=prompt_set.id,
        discovery_id=row.id,
        prompts=prompts,
        topics=topics,
        provider=prompt_provider,
        model=prompt_model,
        research_snapshot_id=research_snapshot_id,
    )
    retained = [
        item for item in prompt_rows if item.normalized_text_hash in approved_hashes
    ]
    if len(retained) != len(prompts):
        raise BrandDiscoveryError("Reviewed prompts must remain unique")
    session.add_all(retained)
    return project.id


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
    existing_crawl = (
        await session.get(SiteCrawl, row.initial_crawl_id)
        if row.initial_crawl_id is not None
        else None
    )
    return row, existing_crawl


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
    )
    replay = await _completion_replay(session, row=row, idempotency_key=key)
    if replay is not None:
        return replay
    if row.status != DISCOVERY_STATUS_READY:
        raise BrandDiscoveryError("Discovery is not ready for completion")
    (
        domains,
        competitors,
        discovery_topics,
        brand_name,
        primary_market,
        profile_sources,
    ) = _confirmed_portfolio_inputs(row, payload=payload)

    # The provider call must not run inside a database transaction or while a
    # discovery row is locked. Re-resolve and lock immediately before writes.
    await session.commit()
    (
        prompts,
        prompt_provider,
        prompt_model,
        prompt_warnings,
    ) = await _generate_confirmed_portfolio(
        payload=payload,
        topics=discovery_topics,
        brand_name=brand_name,
        primary_market=primary_market,
        competitors=competitors,
    )
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
    row.domains = domains
    row.competitors = competitors
    confirmed_profile = payload.profile.model_dump()
    row.profile = confirmed_profile
    row.topics = [topic.model_dump(mode="json") for topic in discovery_topics]
    row.prompt_suggestions = prompts
    # A topic that produced no usable prompt is reported, not fatal. The topic
    # still exists and the user can write a prompt for it by hand.
    row.warnings = list(dict.fromkeys([*row.warnings, *prompt_warnings]))
    row.input_data = {**row.input_data, "completion_idempotency_key": key}
    project_id = await _persist_project(
        session,
        workspace_id=workspace_id,
        row=row,
        payload=payload,
        prompts=prompts,
        discovery_topics=discovery_topics,
        prompt_provider=prompt_provider,
        prompt_model=prompt_model,
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


def _confirmed_portfolio_inputs(
    row: BrandDiscovery,
    *,
    payload: BrandDiscoveryComplete,
) -> tuple[
    list[str],
    list[dict],
    list[DiscoveryTopic],
    str,
    str,
    dict[str, dict[str, str]],
]:
    domains = _confirmed_domains(payload.domains)
    competitors = _confirmed_competitors(
        payload.competitors,
        brand_name=str(row.input_data["brand_name"]),
        owned_domains=domains,
    )
    try:
        topics = [DiscoveryTopic.model_validate(item) for item in row.topics]
    except (TypeError, ValueError):
        topics = []
    if not topics:
        topics = confirmed_offering_topics(payload.profile.products_services)
    topics = topics[:VISIBILITY_TOPIC_MAX]
    brand_name = str(row.input_data["brand_name"])
    primary_market = str(row.input_data["primary_market"])
    profile_sources = _reviewed_profile_sources(payload.profile.model_dump())
    return (
        domains,
        competitors,
        topics,
        brand_name,
        primary_market,
        profile_sources,
    )


def _category_vocabulary(
    profile: DiscoveryProfile, topics: list[DiscoveryTopic]
) -> list[str]:
    """The words this business's own category uses.

    Confirmed at review, so it is the user's vocabulary rather than a guess.
    A brand token that also appears here is category language and must stay
    usable in organic prompts -- see `brand_terms`.
    """
    return [
        *[profile.category],
        *profile.category_options,
        *profile.category_aliases,
        *profile.category_terms,
        *profile.products_services,
        *[topic.name for topic in topics],
    ]


async def _generate_confirmed_portfolio(
    *,
    payload: BrandDiscoveryComplete,
    topics: list[DiscoveryTopic],
    brand_name: str,
    primary_market: str,
    competitors: list[dict],
) -> tuple[list[dict], str, str, list[str]]:
    result = await generate_portfolio(
        brand_name=brand_name,
        brand_terms=brand_terms(
            brand_name,
            [],
            _category_vocabulary(payload.profile, topics),
        ),
        primary_market=primary_market,
        profile=payload.profile.model_dump(),
        competitors=[competitor["name"] for competitor in competitors],
        competitor_terms=[
            term
            for competitor in competitors
            for term in [competitor["name"], *competitor.get("aliases", [])]
        ],
        topics=topics,
    )
    if not result.prompts:
        detail = ", ".join(result.errors) or "generation_failed"
        raise BrandDiscoveryError(f"Initial prompt generation failed: {detail}")
    return list(result.prompts), result.provider, result.model, list(result.errors)
