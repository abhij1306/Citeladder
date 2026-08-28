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
    context = await session.scalar(
        select(BrandProfile.business_context).where(
            BrandProfile.workspace_id == workspace_id,
            BrandProfile.project_id == project_id,
        )
    )
    context = context if isinstance(context, dict) else {}
    # Secondary models count. Onboarding models composite businesses on purpose
    # -- "Urban Company is a marketplace AND a local service" -- so a brand that
    # sells a catalog alongside something else declares that in
    # `secondary_business_models`, and reading only the primary would deny it a
    # catalog it demonstrably has.
    secondary = context.get("secondary_business_models")
    models = [context.get("business_model")]
    models += secondary if isinstance(secondary, list) else []
    return any(sells_a_catalog(str(model or "")) for model in models)
