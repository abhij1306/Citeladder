"""Freeze typed Commerce measurement context into the shared Audit plan."""

from __future__ import annotations

import uuid
from collections import defaultdict

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


class CommerceContextError(ValueError):
    """A selected Commerce target cannot yield complete frozen evidence."""


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
    categories, products, competitors = await _target_evidence(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        targets=targets,
    )
    target_rows: list[dict] = []
    for target in targets:
        key = (target.target_kind, target.target_id)
        category = (
            categories.get(target.target_id)
            if target.target_kind == "category"
            else None
        )
        if category is None and target.target_kind == "category":
            raise CommerceContextError("Selected Commerce category is unavailable")
        if not products[key]:
            raise CommerceContextError(
                "Selected Commerce target has no active product evidence"
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
                    for product in products[key]
                ],
                "approved_competitors": [
                    {
                        "id": str(candidate.id),
                        "canonical_url": candidate.canonical_url,
                        "product_name": candidate.product_name,
                        "brand_name": candidate.brand_name,
                    }
                    for candidate in competitors[key]
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


async def _target_evidence(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    targets: list[CommercePromptTarget],
) -> tuple[
    dict[uuid.UUID, CommerceCategory],
    dict[tuple[str, uuid.UUID], list[CommerceProduct]],
    dict[tuple[str, uuid.UUID], list[CommerceCompetitorCandidate]],
]:
    product_ids = {
        target.target_id for target in targets if target.target_kind == "product"
    }
    category_ids = {
        target.target_id for target in targets if target.target_kind == "category"
    }
    categories: dict[uuid.UUID, CommerceCategory] = {}
    products: dict[tuple[str, uuid.UUID], list[CommerceProduct]] = defaultdict(list)
    competitors: dict[tuple[str, uuid.UUID], list[CommerceCompetitorCandidate]] = (
        defaultdict(list)
    )
    if product_ids:
        product_rows = await session.scalars(
            select(CommerceProduct).where(
                CommerceProduct.id.in_(product_ids),
                CommerceProduct.workspace_id == workspace_id,
                CommerceProduct.project_id == project_id,
                CommerceProduct.lifecycle_state == "active",
            )
        )
        for product in product_rows:
            products[("product", product.id)].append(product)
    if category_ids:
        category_rows = await session.scalars(
            select(CommerceCategory).where(
                CommerceCategory.id.in_(category_ids),
                CommerceCategory.workspace_id == workspace_id,
                CommerceCategory.project_id == project_id,
            )
        )
        categories = {category.id: category for category in category_rows}
        membership_rows = await session.execute(
            select(CommerceProductCategory.category_id, CommerceProduct)
            .join(
                CommerceProduct,
                CommerceProduct.id == CommerceProductCategory.product_id,
            )
            .where(
                CommerceProductCategory.category_id.in_(category_ids),
                CommerceProductCategory.workspace_id == workspace_id,
                CommerceProductCategory.project_id == project_id,
                CommerceProduct.workspace_id == workspace_id,
                CommerceProduct.project_id == project_id,
                CommerceProduct.lifecycle_state == "active",
            )
        )
        for category_id, product in membership_rows:
            products[("category", category_id)].append(product)
    target_ids = product_ids | category_ids
    if target_ids:
        candidate_rows = await session.scalars(
            select(CommerceCompetitorCandidate).where(
                CommerceCompetitorCandidate.target_id.in_(target_ids),
                CommerceCompetitorCandidate.workspace_id == workspace_id,
                CommerceCompetitorCandidate.project_id == project_id,
                CommerceCompetitorCandidate.state == "approved",
            )
        )
        for candidate in candidate_rows:
            competitors[(candidate.target_kind, candidate.target_id)].append(candidate)
    return categories, products, competitors
