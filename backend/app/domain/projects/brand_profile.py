"""Workspace-scoped BrandProfile reads and human-authored upserts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.brand_profile import (
    BRAND_PROFILE_FIELDS,
    BRAND_PROFILE_REVIEW_CONFIRMED,
    BRAND_PROFILE_REVIEW_EDITED,
    BRAND_PROFILE_SOURCE_MANUAL,
)

# ``clean_profile_products`` lives in ``normalization`` (its owner) because
# ``domain/projects/service`` needs it too and cannot import from this module
# without a cycle. Re-exported here so existing importers keep working.
from app.domain.projects.normalization import clean_profile_products
from app.domain.projects.schemas import (
    BrandProfileResponse,
    BrandProfileSourceArtifacts,
    BrandProfileSources,
)
from app.domain.projects.service import get_project
from app.models.brand import BrandProfile

__all__ = [
    "BrandProfileNotFoundError",
    "brand_profile_to_response",
    # Re-exported from ``normalization`` for the many existing importers.
    "clean_profile_products",
    "get_brand_profile",
    "upsert_manual_brand_profile",
]


class BrandProfileNotFoundError(LookupError):
    """Raised when a profile is absent or outside the caller's workspace."""


def brand_profile_to_response(profile: BrandProfile) -> BrandProfileResponse:
    sources = profile.sources or {}
    artifact_ids = profile.source_artifact_ids or {}
    return BrandProfileResponse(
        id=profile.id,
        workspace_id=profile.workspace_id,
        project_id=profile.project_id,
        brand_id=profile.brand_id,
        description=profile.description,
        positioning=profile.positioning,
        products_services=list(profile.products_services or []),
        target_audience=profile.target_audience,
        sources=BrandProfileSources(
            **{
                field: sources[field]
                for field in BRAND_PROFILE_FIELDS
                if field in sources
            }
        ),
        source_artifact_ids=BrandProfileSourceArtifacts(
            **{
                field: artifact_ids[field]
                for field in BRAND_PROFILE_FIELDS
                if field in artifact_ids
            }
        ),
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


async def get_brand_profile(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> BrandProfile:
    result = await session.execute(
        select(BrandProfile).where(
            BrandProfile.workspace_id == workspace_id,
            BrandProfile.project_id == project_id,
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise BrandProfileNotFoundError("Brand profile not found")
    return profile


async def upsert_manual_brand_profile(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    user_id: uuid.UUID,
    payload: Any,
) -> BrandProfile:
    """Apply human edits while preserving each field's original origin."""
    project = await get_project(
        session, workspace_id=workspace_id, project_id=project_id
    )
    if project.brand is None:
        raise BrandProfileNotFoundError("Project brand not found")

    profile = project.brand.profile
    if profile is None:
        profile = BrandProfile(
            workspace_id=workspace_id,
            project_id=project.id,
            brand_id=project.brand.id,
        )
        project.brand.profile = profile

    data = payload.model_dump(exclude_unset=True, exclude_none=True)
    sources = dict(profile.sources or {})
    artifact_ids = dict(profile.source_artifact_ids or {})
    for field, value in data.items():
        if field not in BRAND_PROFILE_FIELDS:
            continue
        if field == "products_services":
            value = clean_profile_products(value)
        else:
            value = value.strip()
        setattr(profile, field, value)
        prior = sources.get(field)
        origin = (
            prior.get("origin", BRAND_PROFILE_SOURCE_MANUAL)
            if isinstance(prior, dict)
            else BRAND_PROFILE_SOURCE_MANUAL
        )
        sources[field] = {
            "origin": origin,
            "review_state": (
                BRAND_PROFILE_REVIEW_EDITED
                if isinstance(prior, dict)
                else BRAND_PROFILE_REVIEW_CONFIRMED
            ),
            "reviewed_by": str(user_id),
            "reviewed_at": datetime.now(UTC).isoformat(),
        }
        artifact_ids.pop(field, None)
    profile.sources = sources
    profile.source_artifact_ids = artifact_ids

    await session.commit()
    return await get_brand_profile(
        session, workspace_id=workspace_id, project_id=project_id
    )
