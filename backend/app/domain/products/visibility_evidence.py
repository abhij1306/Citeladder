"""Persisted product-evidence projection stages."""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
)
from app.core.config.commerce import (
    PRODUCT_ATTRIBUTE_EVIDENCE_NAMESPACE,
    PRODUCT_EVIDENCE_KIND_ATTRIBUTE_MENTION,
    PRODUCT_EVIDENCE_KIND_BUYER_DESTINATION,
    PRODUCT_EVIDENCE_KIND_PRODUCT_MENTION,
    SHOPPING_SURFACE_MEASUREMENT,
)
from app.core.config.products import (
    PRODUCT_EVIDENCE_DEFAULT_LIMIT,
    PRODUCT_EVIDENCE_MAX_LIMIT,
)
from app.core.config.provider_catalog import LOGICAL_ENGINES
from app.domain.analysis.errors import AnalysisNotFoundError, TrendQueryError
from app.domain.products.schemas import ProductEvidenceItem, ProductEvidenceResponse
from app.domain.products.service import ProductNotFoundError
from app.domain.products.visibility import _project_price_relation
from app.models.audit import Audit, AuditPromptSnapshot, AuditTask
from app.models.product import (
    MerchantMention,
    Product,
    ProductMention,
    ProductResponseAnalysis,
)
from app.models.project import Project

_DASHBOARD_STATUSES = (AUDIT_STATUS_COMPLETED, AUDIT_STATUS_PARTIALLY_COMPLETED)
_AUDIT_NOT_FOUND = "Audit not found"


def _evidence_common(
    *,
    analysis: ProductResponseAnalysis,
    prompt_snapshot: AuditPromptSnapshot,
    matched_name: str,
    matched_sku: str,
) -> dict[str, Any]:
    return {
        "analysis_id": analysis.id,
        "audit_id": analysis.audit_id,
        "task_id": analysis.task_id,
        "artifact_id": analysis.artifact_id,
        "logical_engine": analysis.logical_engine,
        "transport_model": analysis.transport_model,
        "prompt_text": prompt_snapshot.text or "",
        "prompt_index": analysis.prompt_index,
        "repetition": analysis.repetition,
        "shopping_surface": analysis.shopping_surface,
        "matched_name": matched_name,
        "matched_sku": matched_sku,
    }


async def _load_evidence_rows(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    audit_id: uuid.UUID | None,
    engine: str | None,
    surface: str,
    limit: int,
) -> tuple[
    list[
        tuple[
            ProductMention,
            ProductResponseAnalysis,
            AuditTask,
            AuditPromptSnapshot,
        ]
    ],
    bool,
]:
    stmt = (
        select(
            ProductMention,
            ProductResponseAnalysis,
            AuditTask,
            AuditPromptSnapshot,
        )
        .join(
            ProductResponseAnalysis,
            ProductResponseAnalysis.id == ProductMention.analysis_id,
        )
        .join(AuditTask, AuditTask.id == ProductResponseAnalysis.task_id)
        .join(
            AuditPromptSnapshot,
            AuditPromptSnapshot.id == AuditTask.prompt_snapshot_id,
        )
        .join(Audit, Audit.id == ProductMention.audit_id)
        .where(
            ProductMention.workspace_id == workspace_id,
            ProductMention.product_id == product_id,
            Audit.status.in_(_DASHBOARD_STATUSES),
            ProductResponseAnalysis.shopping_surface == surface,
        )
    )
    if audit_id is not None:
        stmt = stmt.where(ProductMention.audit_id == audit_id)
    if engine is not None:
        stmt = stmt.where(ProductResponseAnalysis.logical_engine == engine)
    rows = list(
        (
            await session.execute(
                stmt.order_by(
                    Audit.completed_at.desc().nullslast(),
                    Audit.created_at.desc(),
                    ProductResponseAnalysis.prompt_index.asc(),
                    ProductResponseAnalysis.logical_engine.asc(),
                    ProductResponseAnalysis.repetition.asc(),
                    ProductMention.id.asc(),
                ).limit(limit + 1)
            )
        ).all()
    )
    return (
        cast(
            list[
                tuple[
                    ProductMention,
                    ProductResponseAnalysis,
                    AuditTask,
                    AuditPromptSnapshot,
                ]
            ],
            rows[:limit],
        ),
        len(rows) > limit,
    )


async def _load_destinations(
    session: AsyncSession,
    *,
    analysis_ids: list[uuid.UUID],
    product_id: uuid.UUID,
) -> dict[uuid.UUID, list[MerchantMention]]:
    if not analysis_ids:
        return {}
    merchants = list(
        (
            await session.scalars(
                select(MerchantMention)
                .where(
                    MerchantMention.analysis_id.in_(analysis_ids),
                    MerchantMention.product_id == product_id,
                )
                .order_by(MerchantMention.created_at.asc(), MerchantMention.id.asc())
            )
        ).all()
    )
    grouped: dict[uuid.UUID, list[MerchantMention]] = {}
    for merchant in merchants:
        grouped.setdefault(merchant.analysis_id, []).append(merchant)
    return grouped


def _mention_items(
    *,
    mention: ProductMention,
    analysis: ProductResponseAnalysis,
    common: dict[str, Any],
) -> list[ProductEvidenceItem]:
    items = [
        ProductEvidenceItem(
            **common,
            evidence_id=mention.id,
            evidence_kind=PRODUCT_EVIDENCE_KIND_PRODUCT_MENTION,
            product_analyzer_version=mention.product_analyzer_version,
            created_at=mention.created_at,
            first_offset=mention.first_offset,
            rank_position=mention.rank_position,
            price_value=(
                float(mention.price_value) if mention.price_value is not None else None
            ),
            price_matches_catalog=mention.price_matches_catalog,
            price_relation=_project_price_relation(
                mention.price_relation, mention.price_matches_catalog
            ),
            price_text=mention.price_text,
            price_currency=mention.price_currency,
        )
    ]
    for attribute in mention.attribute_mentions or []:
        dimension = str(attribute.get("dimension") or "")
        offset = attribute.get("offset")
        items.append(
            ProductEvidenceItem(
                **common,
                evidence_id=uuid.uuid5(
                    PRODUCT_ATTRIBUTE_EVIDENCE_NAMESPACE,
                    f"{analysis.id}:{mention.id}:{dimension}:{offset}",
                ),
                evidence_kind=PRODUCT_EVIDENCE_KIND_ATTRIBUTE_MENTION,
                product_analyzer_version=mention.product_analyzer_version,
                created_at=mention.created_at,
                attribute_dimension=dimension,
                attribute_group=str(attribute.get("group") or ""),
                attribute_text=str(attribute.get("text") or ""),
                attribute_offset=offset,
            )
        )
    return items


def _destination_items(
    *,
    common: dict[str, Any],
    merchants: list[MerchantMention],
) -> list[ProductEvidenceItem]:
    return [
        ProductEvidenceItem(
            **common,
            evidence_id=merchant.id,
            evidence_kind=PRODUCT_EVIDENCE_KIND_BUYER_DESTINATION,
            product_analyzer_version=merchant.product_analyzer_version,
            created_at=merchant.created_at,
            merchant_name=merchant.merchant_name,
            merchant_domain=merchant.merchant_domain,
            merchant_kind=merchant.merchant_kind,
            destination_url=merchant.destination_url,
        )
        for merchant in merchants
    ]


async def get_product_evidence(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    product_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
    engine: str | None = None,
    surface: str = SHOPPING_SURFACE_MEASUREMENT,
    limit: int = PRODUCT_EVIDENCE_DEFAULT_LIMIT,
) -> ProductEvidenceResponse:
    """Project persisted product, attribute, and destination evidence."""
    if engine is not None and engine not in LOGICAL_ENGINES:
        raise TrendQueryError(f"Unknown logical engine: {engine!r}")
    if limit < 1 or limit > PRODUCT_EVIDENCE_MAX_LIMIT:
        raise TrendQueryError(
            f"'limit' must be between 1 and {PRODUCT_EVIDENCE_MAX_LIMIT}"
        )
    owning = await session.scalar(
        select(Product.id)
        .join(Project, Project.id == Product.project_id)
        .where(Product.id == product_id, Project.workspace_id == workspace_id)
    )
    if owning is None:
        raise ProductNotFoundError(f"Product {product_id} not found")
    if audit_id is not None:
        owning_audit = await session.scalar(
            select(Audit.id).where(
                Audit.id == audit_id, Audit.workspace_id == workspace_id
            )
        )
        if owning_audit is None:
            raise AnalysisNotFoundError(_AUDIT_NOT_FOUND)
    rows, truncated = await _load_evidence_rows(
        session,
        workspace_id=workspace_id,
        product_id=product_id,
        audit_id=audit_id,
        engine=engine,
        surface=surface,
        limit=limit,
    )
    destinations = await _load_destinations(
        session,
        analysis_ids=list({analysis.id for _, analysis, _, _ in rows}),
        product_id=product_id,
    )
    items: list[ProductEvidenceItem] = []
    emitted: set[uuid.UUID] = set()
    for mention, analysis, _task, prompt_snapshot in rows:
        common = _evidence_common(
            analysis=analysis,
            prompt_snapshot=prompt_snapshot,
            matched_name=mention.matched_name,
            matched_sku=mention.matched_sku,
        )
        items.extend(
            _mention_items(
                mention=mention,
                analysis=analysis,
                common=common,
            )
        )
        if analysis.id not in emitted:
            emitted.add(analysis.id)
            items.extend(
                _destination_items(
                    common=common,
                    merchants=destinations.get(analysis.id, []),
                )
            )
    return ProductEvidenceResponse(items=items, truncated=truncated)
