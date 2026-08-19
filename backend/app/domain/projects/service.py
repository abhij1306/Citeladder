# Project + normalized brand-identity service (workspace-scoped, invariant 5).
#
# Every read/write filters by ``workspace_id`` (never ``user_id``). The service
# owns translating the flat create/update payload into the normalized brand
# rows (B-1) and back, and reuses ``normalization.py`` for benchmark-mode
# canonicalization.
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config.api import API_V1_PREFIX
from app.core.config.brand_profile import (
    BRAND_PROFILE_REVIEW_CONFIRMED,
    BRAND_PROFILE_REVIEW_UNREVIEWED,
    BRAND_PROFILE_SOURCE_MANUAL,
)
from app.core.config.entitlements import KEY_PROJECT_SLOTS
from app.core.config.projects import MAX_PROJECT_COMPETITORS
from app.domain.entitlements.enforcement import (
    enforce_occupancy,
    lock_workspace_capacity,
)
from app.domain.projects.normalization import (
    clean_profile_products,
    normalize_benchmark_mode,
)
from app.domain.projects.schemas import (
    BrandResponse,
    CompetitorResponse,
    ProjectResponse,
)
from app.domain.prompts.mappers import prompt_set_to_response
from app.models.brand import (
    Brand,
    BrandAlias,
    BrandProfile,
    Competitor,
    OwnedDomain,
    UnintendedDomain,
)
from app.models.project import Project
from app.models.prompt import PromptSet


class ProjectNotFoundError(LookupError):
    """Raised when a project is missing or not in the caller's workspace."""


def brand_logo_url(project_id: uuid.UUID) -> str:
    return f"{API_V1_PREFIX}/projects/{project_id}/logo"


def competitor_logo_url(project_id: uuid.UUID, competitor_id: uuid.UUID) -> str:
    return f"{API_V1_PREFIX}/projects/{project_id}/competitors/{competitor_id}/logo"


def _loaded_project_query():
    """A select over ``Project`` with all brand-identity rows eager-loaded."""
    return select(Project).options(
        selectinload(Project.brand).selectinload(Brand.aliases),
        selectinload(Project.brand).selectinload(Brand.profile),
        selectinload(Project.competitors),
        selectinload(Project.owned_domains),
        selectinload(Project.unintended_domains),
        selectinload(Project.prompt_sets).selectinload(PromptSet.prompts),
    )


def _clean_list(values: list[str] | None) -> list[str]:
    return [str(v).strip() for v in (values or []) if str(v).strip()]


def _brand_response(project: Project) -> BrandResponse:
    brand = project.brand
    return BrandResponse(
        aliases=[alias.alias for alias in brand.aliases] if brand is not None else [],
        logo_url=(
            brand_logo_url(project.id)
            if brand is not None and brand.logo_asset_id is not None
            else None
        ),
    )


def _competitor_responses(project: Project) -> list[CompetitorResponse]:
    return [
        CompetitorResponse(
            id=competitor.id,
            name=competitor.name,
            aliases=list(competitor.aliases or []),
            domains=list(competitor.domains or []),
            logo_url=(
                competitor_logo_url(project.id, competitor.id)
                if competitor.logo_asset_id is not None
                else None
            ),
        )
        for competitor in project.competitors
    ]


def project_to_response(project: Project) -> ProjectResponse:
    """Project the normalized rows back into the flat response DTO."""
    return ProjectResponse(
        id=project.id,
        workspace_id=project.workspace_id,
        name=project.name,
        brand_name=(
            project.brand.name if project.brand is not None else project.brand_name
        ),
        brand=_brand_response(project),
        website_url=project.website_url,
        industry=project.industry,
        subindustry=project.subindustry,
        primary_market=project.primary_market,
        owned_domains=[d.domain for d in project.owned_domains],
        unintended_domains=[d.domain for d in project.unintended_domains],
        competitors=_competitor_responses(project),
        prompt_sets=[prompt_set_to_response(ps) for ps in project.prompt_sets],
        country_code=project.country_code,
        language_code=project.language_code,
        benchmark_mode=project.benchmark_mode,
        default_repetitions=project.default_repetitions,
        created_at=project.created_at,
        updated_at=project.updated_at,
    )


def _apply_brand(project: Project, brand_name: str, aliases: list[str]) -> None:
    """(Re)build the brand + its aliases on a project in place.

    When a brand row already exists it is mutated in place (rather than
    replaced) so the ``uq_brand_project`` unique constraint is never briefly
    violated by an INSERT-before-DELETE ordering during an update.
    """
    brand = project.brand
    if brand is None:
        brand = Brand(name=brand_name)
        project.brand = brand
    else:
        brand.name = brand_name
    brand.aliases = [BrandAlias(alias=a) for a in _clean_list(aliases)]
    project.brand_name = brand_name


def _build_competitors(items: list[Any] | None) -> list[Competitor]:
    if len(items or []) > MAX_PROJECT_COMPETITORS:
        raise ValueError(
            f"A project can have at most {MAX_PROJECT_COMPETITORS} competitors"
        )
    competitors: list[Competitor] = []
    for item in items or []:
        name = str(getattr(item, "name", "") or "").strip()
        if not name:
            continue
        competitors.append(
            Competitor(
                name=name,
                aliases=_clean_list(list(getattr(item, "aliases", []) or [])),
                domains=_clean_list(list(getattr(item, "domains", []) or [])),
            )
        )
    return competitors


def _seed_manual_brand_profile(
    project: Project,
    *,
    workspace_id: uuid.UUID,
    payload: Any,
    sources: dict[str, dict[str, Any]] | None = None,
    reviewer_id: uuid.UUID | None = None,
) -> None:
    """Attach the human-authored brand profile to a freshly created project.

    Normalizes ONCE, then derives both the stored values and the source markers
    from the normalized form: a whitespace-only string (or a product list that
    cleans to empty) stores as empty and must NOT be recorded as a manually
    authored field — an empty "manual" marker would outrank a later AI
    suggestion for a field the human never actually filled in.

    A project with no brand has nothing to profile and is left untouched.
    """
    if project.brand is None:
        return
    profile_fields: dict[str, Any] = {
        "description": (payload.description or "").strip(),
        "positioning": (payload.positioning or "").strip(),
        "products_services": clean_profile_products(payload.products_services),
        "target_audience": (payload.target_audience or "").strip(),
    }
    project.brand.profile = BrandProfile(
        workspace_id=workspace_id,
        project_id=project.id,
        brand_id=project.brand.id,
        # Kept out of `profile_fields` deliberately: that dict drives the
        # per-field `sources` markers, and the business context is one
        # confirmed document rather than four independently reviewable fields.
        business_context=dict(getattr(payload, "business_context", None) or {}),
        **profile_fields,
        sources=sources
        if sources is not None
        else {
            field: {
                "origin": BRAND_PROFILE_SOURCE_MANUAL,
                "review_state": (
                    BRAND_PROFILE_REVIEW_CONFIRMED
                    if reviewer_id is not None
                    else BRAND_PROFILE_REVIEW_UNREVIEWED
                ),
                "reviewed_by": str(reviewer_id) if reviewer_id else None,
                "reviewed_at": datetime.now(UTC).isoformat() if reviewer_id else None,
            }
            for field, value in profile_fields.items()
            if value
        },
    )


async def create_project(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    payload: Any,
    commit: bool = True,
    brand_profile_sources: dict[str, dict[str, Any]] | None = None,
    reviewer_id: uuid.UUID | None = None,
) -> Project:
    """Create a project + its normalized brand identity in one transaction.

    Occupancy is enforced INSIDE the domain service (never an API precheck):
    the account-capacity advisory lock and the ``project_slots`` check run in
    the same transaction as the insert, so concurrent creates across the
    account's workspaces can never exceed the resolved allowance.
    """
    account_id = await lock_workspace_capacity(session, workspace_id)
    await enforce_occupancy(
        session,
        account_id=account_id,
        key=KEY_PROJECT_SLOTS,
        requested_delta=1,
        at=datetime.now(UTC),
    )
    project = Project(
        workspace_id=workspace_id,
        name=payload.name,
        website_url=payload.website_url,
        industry=payload.industry,
        subindustry=payload.subindustry,
        primary_market=payload.primary_market,
        country_code=payload.country_code,
        language_code=payload.language_code,
        benchmark_mode=normalize_benchmark_mode(payload.benchmark_mode),
        default_repetitions=payload.default_repetitions,
    )
    _apply_brand(project, payload.brand_name, payload.brand_aliases)
    project.competitors = _build_competitors(payload.competitors)
    project.owned_domains = [
        OwnedDomain(domain=d) for d in _clean_list(payload.owned_domains)
    ]
    project.unintended_domains = [
        UnintendedDomain(domain=d) for d in _clean_list(payload.unintended_domains)
    ]
    session.add(project)
    await session.flush()
    _seed_manual_brand_profile(
        project,
        workspace_id=workspace_id,
        payload=payload,
        sources=brand_profile_sources,
        reviewer_id=reviewer_id,
    )
    if not commit:
        return project
    await session.commit()
    return await get_project(session, workspace_id=workspace_id, project_id=project.id)


async def list_projects(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> list[Project]:
    result = await session.execute(
        _loaded_project_query()
        .where(Project.workspace_id == workspace_id)
        .order_by(Project.created_at.desc())
    )
    return list(result.scalars().unique().all())


async def get_project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> Project:
    result = await session.execute(
        _loaded_project_query().where(
            Project.id == project_id,
            Project.workspace_id == workspace_id,
        )
    )
    project = result.scalars().unique().one_or_none()
    if project is None:
        raise ProjectNotFoundError("Project not found")
    return project


async def update_project(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    payload: Any,
) -> Project:
    project = await get_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    data = payload.model_dump(exclude_unset=True)
    _apply_project_updates(project, payload, data)

    await session.commit()
    return await get_project(session, workspace_id=workspace_id, project_id=project_id)


def _apply_scalar_project_updates(project: Project, data: dict) -> None:
    for field in (
        "name",
        "website_url",
        "country_code",
        "industry",
        "subindustry",
        "primary_market",
        "language_code",
    ):
        value = data.get(field)
        if value is not None:
            setattr(project, field, value)


def _apply_brand_update(project: Project, payload: Any, data: dict) -> None:
    if data.get("brand_name") is None and payload.brand is None:
        return
    brand = project.brand
    new_name = (
        data["brand_name"]
        if data.get("brand_name") is not None
        else (brand.name if brand is not None else project.brand_name)
    )
    new_aliases = (
        payload.brand.aliases
        if payload.brand is not None
        else ([alias.alias for alias in brand.aliases] if brand is not None else [])
    )
    _apply_brand(project, new_name, new_aliases)


def _apply_collection_updates(project: Project, payload: Any, data: dict) -> None:
    if data.get("competitors") is not None:
        project.competitors = _build_competitors(payload.competitors)
    if data.get("owned_domains") is not None:
        project.owned_domains = [
            OwnedDomain(domain=domain) for domain in _clean_list(data["owned_domains"])
        ]
    if data.get("unintended_domains") is not None:
        project.unintended_domains = [
            UnintendedDomain(domain=domain)
            for domain in _clean_list(data["unintended_domains"])
        ]


def _apply_project_updates(project: Project, payload: Any, data: dict) -> None:
    _apply_scalar_project_updates(project, data)
    if data.get("benchmark_mode") is not None:
        project.benchmark_mode = normalize_benchmark_mode(data["benchmark_mode"])
    if data.get("default_repetitions") is not None:
        project.default_repetitions = data["default_repetitions"]
    _apply_brand_update(project, payload, data)
    _apply_collection_updates(project, payload, data)


async def delete_project(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> None:
    project = await get_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    await session.delete(project)
    await session.commit()
