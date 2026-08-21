"""Database-first brand-logo cache orchestration and asset reads."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from collections.abc import Collection
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TypeGuard

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.web_evidence.favicon import (
    FetchedBrandLogo,
    fetch_brand_logo,
)
from app.connectors.web_evidence.fetcher import SecureFetcher
from app.connectors.web_evidence.resolver import SystemDnsResolver
from app.connectors.web_evidence.url_policy import (
    UrlPolicyError,
    canonicalize,
    registrable_domain,
)
from app.core.config.brand_logos import (
    BRAND_LOGO_FAILURE_CACHE_SECONDS,
    BRAND_LOGO_FETCH_CONCURRENCY,
    BRAND_LOGO_REFRESH_TIMEOUT_SECONDS,
    BRAND_LOGO_STATUS_FAILED,
    BRAND_LOGO_STATUS_READY,
    BRAND_LOGO_SUCCESS_CACHE_SECONDS,
)
from app.models.brand import Brand, BrandLogoAsset, Competitor
from app.models.project import Project

from .service import brand_logo_url, competitor_logo_url, get_project

logger = logging.getLogger(__name__)


class BrandLogoNotFoundError(LookupError):
    """The requested project identity has no ready cached logo."""


@dataclass(slots=True)
class _LogoTarget:
    domain: str
    homepage_url: str
    brand_ids: list[uuid.UUID] = field(default_factory=list)
    competitor_ids: list[uuid.UUID] = field(default_factory=list)


def _target_identity(raw_url: str) -> tuple[str, str] | None:
    candidate = str(raw_url or "").strip()
    if not candidate:
        return None
    if "://" not in candidate:
        candidate = f"https://{candidate}"
    try:
        homepage = canonicalize(candidate)
    except UrlPolicyError:
        return None
    domain = registrable_domain(homepage)
    if not domain:
        return None
    return domain, homepage


def _project_targets(project: Project) -> dict[str, _LogoTarget]:
    targets: dict[str, _LogoTarget] = {}
    brand_identity = _target_identity(project.website_url)
    if project.brand is not None and brand_identity is not None:
        domain, homepage = brand_identity
        target = targets.setdefault(domain, _LogoTarget(domain, homepage))
        target.brand_ids.append(project.brand.id)

    for competitor in project.competitors:
        identity = next(
            (
                parsed
                for domain_value in list(competitor.domains or [])
                if (parsed := _target_identity(str(domain_value))) is not None
            ),
            None,
        )
        if identity is None:
            continue
        domain, homepage = identity
        target = targets.setdefault(domain, _LogoTarget(domain, homepage))
        target.competitor_ids.append(competitor.id)
    return targets


def _negative_cache_is_fresh(asset: BrandLogoAsset, now: datetime) -> bool:
    return (
        asset.status == BRAND_LOGO_STATUS_FAILED
        and asset.retry_after is not None
        and asset.retry_after > now
    )


def _ready_cache_is_fresh(asset: BrandLogoAsset, now: datetime) -> bool:
    return asset.fetched_at is not None and asset.fetched_at > now - timedelta(
        seconds=BRAND_LOGO_SUCCESS_CACHE_SECONDS
    )


def _is_ready_asset(
    asset: BrandLogoAsset | None,
) -> TypeGuard[BrandLogoAsset]:
    return bool(
        asset is not None
        and asset.status == BRAND_LOGO_STATUS_READY
        and asset.image_data
    )


def _attach_asset(project: Project, target: _LogoTarget, asset_id: uuid.UUID) -> None:
    if project.brand is not None and project.brand.id in target.brand_ids:
        project.brand.logo_asset_id = asset_id
    competitor_ids = set(target.competitor_ids)
    for competitor in project.competitors:
        if competitor.id in competitor_ids:
            competitor.logo_asset_id = asset_id


async def _fetch_missing(
    targets: list[_LogoTarget],
) -> dict[str, FetchedBrandLogo | None]:
    semaphore = asyncio.Semaphore(BRAND_LOGO_FETCH_CONCURRENCY)
    results: dict[str, FetchedBrandLogo | None] = {
        target.domain: None for target in targets
    }
    async with SecureFetcher(resolver=SystemDnsResolver()) as fetcher:

        async def fetch_one(target: _LogoTarget) -> None:
            async with semaphore:
                try:
                    results[target.domain] = await fetch_brand_logo(
                        target.homepage_url, fetcher=fetcher
                    )
                except Exception:
                    logger.exception(
                        "Unexpected brand logo fetch failure",
                        extra={"domain": target.domain},
                    )
                    results[target.domain] = None

        try:
            async with asyncio.timeout(BRAND_LOGO_REFRESH_TIMEOUT_SECONDS):
                await asyncio.gather(*(fetch_one(target) for target in targets))
        except TimeoutError:
            pass
    return results


async def _logo_assets_by_domain(
    session: AsyncSession, domains: Collection[str]
) -> dict[str, BrandLogoAsset]:
    rows = (
        (
            await session.execute(
                select(BrandLogoAsset)
                .where(BrandLogoAsset.domain.in_(domains))
                .execution_options(populate_existing=True)
            )
        )
        .scalars()
        .all()
    )
    return {asset.domain: asset for asset in rows}


async def _upsert_fetched_asset(
    session: AsyncSession,
    *,
    target: _LogoTarget,
    logo: FetchedBrandLogo | None,
    now: datetime,
    retry_after: datetime,
) -> None:
    values = {
        "id": uuid.uuid4(),
        "domain": target.domain,
        "status": (
            BRAND_LOGO_STATUS_READY if logo is not None else BRAND_LOGO_STATUS_FAILED
        ),
        "source_url": logo.source_url if logo is not None else "",
        "content_type": logo.content_type if logo is not None else "",
        "image_data": logo.image_data if logo is not None else None,
        "byte_size": len(logo.image_data) if logo is not None else 0,
        "sha256": (
            hashlib.sha256(logo.image_data).hexdigest() if logo is not None else ""
        ),
        "fetched_at": now,
        "retry_after": None if logo is not None else retry_after,
        "created_at": now,
        "updated_at": now,
    }
    insert_stmt = pg_insert(BrandLogoAsset).values(**values)
    update_values = {
        key: insert_stmt.excluded[key]
        for key in (
            "status",
            "source_url",
            "content_type",
            "image_data",
            "byte_size",
            "sha256",
            "fetched_at",
            "retry_after",
            "updated_at",
        )
    }
    upsert = insert_stmt.on_conflict_do_update(
        index_elements=["domain"],
        set_=update_values,
        where=(
            None
            if logo is not None
            else BrandLogoAsset.status != BRAND_LOGO_STATUS_READY
        ),
    )
    await session.execute(upsert)


async def refresh_project_logos(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> Project:
    """Attach cached logos first; crawl only domains without a usable cache row."""
    project = await get_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    targets = _project_targets(project)
    if not targets:
        await session.commit()
        return project

    cached = await _logo_assets_by_domain(session, targets.keys())
    now = datetime.now(UTC)
    missing: list[_LogoTarget] = []
    for domain, target in targets.items():
        asset = cached.get(domain)
        if _is_ready_asset(asset):
            _attach_asset(project, target, asset.id)
            if not _ready_cache_is_fresh(asset, now):
                missing.append(target)
        elif asset is None or not _negative_cache_is_fresh(asset, now):
            missing.append(target)

    # Release the database transaction before external I/O. Cache hits are
    # already attached and committed even if every missing domain later fails.
    await session.commit()
    if not missing:
        return await get_project(
            session, workspace_id=workspace_id, project_id=project_id
        )

    fetched = await _fetch_missing(missing)
    now = datetime.now(UTC)
    retry_after = now + timedelta(seconds=BRAND_LOGO_FAILURE_CACHE_SECONDS)
    for target in missing:
        await _upsert_fetched_asset(
            session,
            target=target,
            logo=fetched[target.domain],
            now=now,
            retry_after=retry_after,
        )

    assets = await _logo_assets_by_domain(
        session, [target.domain for target in missing]
    )
    for target in missing:
        asset = assets.get(target.domain)
        if _is_ready_asset(asset):
            _attach_asset(project, target, asset.id)
    await session.commit()
    return await get_project(session, workspace_id=workspace_id, project_id=project_id)


async def get_project_logo_asset(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    competitor_id: uuid.UUID | None = None,
) -> BrandLogoAsset:
    if competitor_id is None:
        stmt = (
            select(BrandLogoAsset)
            .join(Brand, Brand.logo_asset_id == BrandLogoAsset.id)
            .join(Project, Project.id == Brand.project_id)
            .where(
                Project.id == project_id,
                Project.workspace_id == workspace_id,
                BrandLogoAsset.status == BRAND_LOGO_STATUS_READY,
                BrandLogoAsset.image_data.is_not(None),
            )
        )
    else:
        stmt = (
            select(BrandLogoAsset)
            .join(Competitor, Competitor.logo_asset_id == BrandLogoAsset.id)
            .join(Project, Project.id == Competitor.project_id)
            .where(
                Project.id == project_id,
                Project.workspace_id == workspace_id,
                Competitor.id == competitor_id,
                BrandLogoAsset.status == BRAND_LOGO_STATUS_READY,
                BrandLogoAsset.image_data.is_not(None),
            )
        )
    asset = await session.scalar(stmt)
    if asset is None:
        raise BrandLogoNotFoundError("Brand logo not found")
    return asset


def get_project_logo_urls(project: Project) -> dict[uuid.UUID, str]:
    """Project ready logo URLs by stable brand or competitor identity."""
    urls: dict[uuid.UUID, str] = {}
    if project.brand is not None and project.brand.logo_asset_id is not None:
        urls[project.brand.id] = brand_logo_url(project.id)
    for competitor in project.competitors:
        if competitor.logo_asset_id is not None:
            urls[competitor.id] = competitor_logo_url(project.id, competitor.id)
    return urls
