"""Freeze typed Commerce measurement context into the shared Audit plan."""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.commerce_catalog import (
    COMMERCE_PROMPT_TEMPLATE_VERSION,
    COMMERCE_RECOMMENDATION_MATCHER_VERSION,
    COMMERCE_RECOMMENDATION_PARSER_VERSION,
    COMMERCE_SHELF_FORMULA_VERSION,
)
from app.models.commerce import (
    CommerceCategory,
    CommerceCompetitorCandidate,
    CommerceProduct,
    CommerceProductCategory,
    CommercePromptTarget,
)


async def freeze_commerce_context(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    prompt_ids: list[uuid.UUID],
) -> dict:
    targets = list(
        (
            await session.scalars(
                select(CommercePromptTarget).where(
                    CommercePromptTarget.workspace_id == workspace_id,
                    CommercePromptTarget.project_id == project_id,
                    CommercePromptTarget.prompt_id.in_(prompt_ids),
                    CommercePromptTarget.approved_at.is_not(None),
                )
            )
        ).all()
    )
    target_rows: list[dict] = []
    for target in targets:
        products_stmt = select(CommerceProduct).where(
            CommerceProduct.workspace_id == workspace_id,
            CommerceProduct.project_id == project_id,
            CommerceProduct.lifecycle_state == "active",
        )
        if target.target_kind == "product":
            products_stmt = products_stmt.where(CommerceProduct.id == target.target_id)
            category = None
        else:
            products_stmt = products_stmt.join(
                CommerceProductCategory,
                CommerceProductCategory.product_id == CommerceProduct.id,
            ).where(CommerceProductCategory.category_id == target.target_id)
            category = await session.scalar(
                select(CommerceCategory).where(
                    CommerceCategory.id == target.target_id,
                    CommerceCategory.workspace_id == workspace_id,
                    CommerceCategory.project_id == project_id,
                )
            )
        products = list((await session.scalars(products_stmt)).all())
        competitors = list(
            (
                await session.scalars(
                    select(CommerceCompetitorCandidate).where(
                        CommerceCompetitorCandidate.workspace_id == workspace_id,
                        CommerceCompetitorCandidate.project_id == project_id,
                        CommerceCompetitorCandidate.target_kind == target.target_kind,
                        CommerceCompetitorCandidate.target_id == target.target_id,
                        CommerceCompetitorCandidate.state == "approved",
                    )
                )
            ).all()
        )
        target_rows.append(
            {
                "kind": target.target_kind,
                "id": str(target.target_id),
                "category": (
                    {"id": str(category.id), "name": category.name}
                    if category is not None
                    else None
                ),
                "products": [
                    {
                        "id": str(product.id),
                        "canonical_url": product.canonical_url,
                        "name": product.name,
                        "brand": product.brand,
                        "sku": product.sku,
                        "gtin": product.gtin,
                        "mpn": product.mpn,
                        "price": float(product.price)
                        if product.price is not None
                        else None,
                        "currency": product.currency,
                        "attributes": product.attributes,
                        "field_sources": product.field_sources,
                    }
                    for product in products
                ],
                "approved_competitors": [
                    {
                        "id": str(candidate.id),
                        "canonical_url": candidate.canonical_url,
                        "product_name": candidate.product_name,
                        "brand_name": candidate.brand_name,
                    }
                    for candidate in competitors
                ],
            }
        )
    return {
        "targets": target_rows,
        "prompt_target_ids": [str(target.id) for target in targets],
        "template_version": COMMERCE_PROMPT_TEMPLATE_VERSION,
        "parser_version": COMMERCE_RECOMMENDATION_PARSER_VERSION,
        "matcher_version": COMMERCE_RECOMMENDATION_MATCHER_VERSION,
        "formula_version": COMMERCE_SHELF_FORMULA_VERSION,
    }
