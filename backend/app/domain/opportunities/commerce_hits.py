"""Retarget shared opportunities to typed Commerce catalog and shelf evidence."""

from __future__ import annotations

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.opportunities.detectors import DetectorHit
from app.core.config.opportunities import (
    COMMERCE_GAP_FACTOR,
    COMMERCE_VALUE_FACTOR,
    OPPORTUNITY_RULES_BY_ID,
    RULE_CATALOG_FIELDS_MISSING,
    RULE_CITED_ALTERNATIVES,
    RULE_PRODUCT_NOT_MENTIONED,
)
from app.models.analysis import Citation, ResponseAnalysis
from app.models.audit import AuditPromptSnapshot, AuditTask
from app.models.commerce import (
    CommerceProduct,
    CommerceProductObservation,
    CommercePromptTarget,
    CommerceShelfSnapshot,
)


def _hit(
    *,
    rule_id: str,
    target_key: str,
    evidence: dict,
    metric_ids: tuple[str, ...],
    analysis_ids: tuple[str, ...] = (),
) -> DetectorHit:
    return DetectorHit(
        rule_id=rule_id,
        target_key=target_key,
        target_prompt_id=None,
        target_url=None,
        target_theme=None,
        evidence=evidence,
        source_analysis_ids=analysis_ids,
        source_issue_ids=(),
        source_metric_ids=metric_ids,
        value_factor=COMMERCE_VALUE_FACTOR,
        gap_factor=COMMERCE_GAP_FACTOR,
    )


async def load_commerce_opportunity_hits(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    audit_id: uuid.UUID,
    project_id: uuid.UUID,
) -> list[DetectorHit]:
    snapshots = list(
        (
            await session.scalars(
                select(CommerceShelfSnapshot).where(
                    CommerceShelfSnapshot.workspace_id == workspace_id,
                    CommerceShelfSnapshot.project_id == project_id,
                    CommerceShelfSnapshot.audit_id == audit_id,
                )
            )
        ).all()
    )
    hits = _unmentioned_hits(snapshots, audit_id=audit_id)
    hits.extend(
        await _catalog_field_hits(
            session, workspace_id=workspace_id, project_id=project_id
        )
    )
    hits.extend(
        await _alternative_hits(session, snapshots=snapshots, audit_id=audit_id)
    )
    return sorted(hits, key=lambda row: (row.rule_id, row.target_key))


def _unmentioned_hits(
    snapshots: list[CommerceShelfSnapshot], *, audit_id: uuid.UUID
) -> list[DetectorHit]:
    rule = OPPORTUNITY_RULES_BY_ID[RULE_PRODUCT_NOT_MENTIONED]
    if not rule.enabled:
        return []
    return [
        _hit(
            rule_id=rule.rule_id,
            target_key=f"product:{row.target_id}",
            evidence={
                "product_id": str(row.target_id),
                "product_visibility": 0,
                "audit_id": str(audit_id),
            },
            metric_ids=(str(row.id),),
        )
        for row in snapshots
        if row.target_kind == "product" and row.product_visibility == 0
    ]


async def _catalog_field_hits(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[DetectorHit]:
    rule = OPPORTUNITY_RULES_BY_ID[RULE_CATALOG_FIELDS_MISSING]
    if not rule.enabled:
        return []
    products = list(
        await session.scalars(
            select(CommerceProduct).where(
                CommerceProduct.workspace_id == workspace_id,
                CommerceProduct.project_id == project_id,
                CommerceProduct.lifecycle_state == "active",
            )
        )
    )
    observations = list(
        await session.scalars(
            select(CommerceProductObservation).where(
                CommerceProductObservation.workspace_id == workspace_id,
                CommerceProductObservation.project_id == project_id,
            )
        )
    )
    by_product: dict[uuid.UUID, list[CommerceProductObservation]] = defaultdict(list)
    for observation in observations:
        by_product[observation.product_id].append(observation)
    hits = (
        _missing_field_hit(
            product, observations=by_product[product.id], rule_id=rule.rule_id
        )
        for product in products
    )
    return [hit for hit in hits if hit is not None]


def _missing_field_hit(
    product: CommerceProduct,
    *,
    observations: list[CommerceProductObservation],
    rule_id: str,
) -> DetectorHit | None:
    fields = ("name", "description", "brand", "price", "currency")
    missing = [field for field in fields if getattr(product, field) in (None, "")]
    if not missing or not observations:
        return None
    return _hit(
        rule_id=rule_id,
        target_key=f"product:{product.id}",
        evidence={
            "product_id": str(product.id),
            "product_name": product.name,
            "missing_fields": missing,
        },
        metric_ids=tuple(str(row.id) for row in observations),
    )


async def _alternative_hits(
    session: AsyncSession,
    *,
    snapshots: list[CommerceShelfSnapshot],
    audit_id: uuid.UUID,
) -> list[DetectorHit]:
    rule = OPPORTUNITY_RULES_BY_ID[RULE_CITED_ALTERNATIVES]
    if not rule.enabled:
        return []
    results: list[DetectorHit] = []
    categories = [
        row
        for row in snapshots
        if row.target_kind == "category" and row.product_visibility == 0
    ]
    for snapshot in categories:
        citations = await _category_citations(
            session, audit_id=audit_id, target_id=snapshot.target_id
        )
        if citations:
            results.append(
                _hit(
                    rule_id=rule.rule_id,
                    target_key=f"category:{snapshot.target_id}",
                    evidence={
                        "category_id": str(snapshot.target_id),
                        "third_party_citation_count": len(citations),
                        "product_visibility": 0,
                        "audit_id": str(audit_id),
                    },
                    metric_ids=(str(snapshot.id),),
                    analysis_ids=tuple(
                        dict.fromkeys(str(row.analysis_id) for row in citations)
                    ),
                )
            )
    return results


async def _category_citations(
    session: AsyncSession, *, audit_id: uuid.UUID, target_id: uuid.UUID
) -> list[Citation]:
    return list(
        await session.scalars(
            select(Citation)
            .join(ResponseAnalysis, ResponseAnalysis.id == Citation.analysis_id)
            .join(AuditTask, AuditTask.id == ResponseAnalysis.task_id)
            .join(
                AuditPromptSnapshot,
                AuditPromptSnapshot.id == AuditTask.prompt_snapshot_id,
            )
            .join(
                CommercePromptTarget,
                CommercePromptTarget.prompt_id == AuditPromptSnapshot.prompt_id,
            )
            .where(
                AuditTask.audit_id == audit_id,
                CommercePromptTarget.target_kind == "category",
                CommercePromptTarget.target_id == target_id,
                Citation.classification == "third_party",
            )
        )
    )
