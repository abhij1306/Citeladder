"""Workspace-scoped eligibility for commerce projections."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.brand_discovery import sells_a_catalog
from app.models.brand import BrandProfile


async def project_sells_catalog(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> bool:
    """Return whether the confirmed brand model supports a product catalog.

    Crawl page kinds cannot answer this: a SaaS blog index can structurally be
    a category page without representing anything buyers can purchase. Missing
    or unknown brand context therefore fails closed until onboarding confirms
    a catalog business model.
    """
    business_model = await session.scalar(
        select(BrandProfile.business_context["business_model"].astext).where(
            BrandProfile.workspace_id == workspace_id,
            BrandProfile.project_id == project_id,
        )
    )
    return sells_a_catalog(str(business_model or ""))
