"""Candidate review and persisted catalog comparison operations."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.commerce import (
    COMMERCE_CANDIDATE_KIND_COMPETITOR,
    COMMERCE_DISCOVERED_SKU_PREFIX,
    COMMERCE_EVIDENCE_LABEL_CATALOG,
    COMMERCE_EVIDENCE_LABEL_DISCOVERY,
    COMMERCE_MATCH_REASON_REVIEWED_DISCOVERY,
    COMMERCE_REVIEW_ACCEPTED,
    COMMERCE_REVIEW_REJECTED,
    commerce_intelligence_settings,
)
from app.core.config.products import PRODUCT_ORIGIN_DISCOVERED
from app.domain.commerce.intelligence import (
    CommerceConflictError,
    CommerceDiscoveryNotFoundError,
    CommerceReviewRequiredError,
    _candidate_in_workspace,
    _candidate_matches,
    _canonical,
    _competitor_entry,
    _product_entry,
    _project,
    _utcnow,
)
from app.domain.commerce.intelligence_schemas import (
    CommerceCandidateAcceptRequest,
    CommerceCandidateAcceptResponse,
    CommerceMatchDecision,
    CompetitorComparisonSnapshotResponse,
)
from app.domain.commerce.matching import match_candidate
from app.domain.products.completeness import product_completeness
from app.models.brand import Competitor
from app.models.commerce import (
    CommerceCandidateReview,
    CommerceDiscoveryCandidate,
    CompetitorComparisonSnapshot,
)
from app.models.product import CompetitorProduct, Product, ProductMetricSnapshot
from app.models.project import Project


async def accept_candidate(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    candidate_id: uuid.UUID,
    request: CommerceCandidateAcceptRequest,
) -> CommerceCandidateAcceptResponse:
    candidate = await _candidate_in_workspace(session, workspace_id, candidate_id)
    existing = await session.scalar(
        select(CommerceCandidateReview)
        .where(
            CommerceCandidateReview.candidate_id == candidate.id,
            CommerceCandidateReview.status == COMMERCE_REVIEW_ACCEPTED,
        )
        .order_by(CommerceCandidateReview.created_at.asc())
    )
    if existing is not None:
        return _existing_acceptance(candidate, existing, request)
    if request.status == COMMERCE_REVIEW_REJECTED:
        return await _reject_candidate(
            session, candidate=candidate, workspace_id=workspace_id, request=request
        )

    matches = await _candidate_matches(session, candidate)
    if matches and matches[0].review_required and request.target_id is None:
        raise CommerceReviewRequiredError(
            "Ambiguous deterministic match requires an explicit reviewed target"
        )
    selected = next(
        (item for item in matches if item.target_id == request.target_id), None
    )
    if request.target_id is not None and selected is None:
        raise CommerceReviewRequiredError(
            "The reviewed target does not match this discovery candidate"
        )
    product_id, competitor_product_id = await _materialize_candidate(
        session, candidate=candidate, request=request, selected=selected
    )
    review = await _persist_candidate_acceptance(
        session,
        candidate=candidate,
        workspace_id=workspace_id,
        request=request,
        selected=selected,
        product_id=product_id,
        competitor_product_id=competitor_product_id,
    )
    return CommerceCandidateAcceptResponse(
        review_id=review.id,
        candidate_id=candidate.id,
        status=review.status,
        product_id=product_id,
        competitor_product_id=competitor_product_id,
        match_reason=review.match_reason,
        match_confidence=review.match_confidence,
    )


def _existing_acceptance(
    candidate: CommerceDiscoveryCandidate,
    existing: CommerceCandidateReview,
    request: CommerceCandidateAcceptRequest,
) -> CommerceCandidateAcceptResponse:
    accepted_targets = {
        None,
        existing.target_product_id,
        existing.target_competitor_product_id,
    }
    if (
        request.status != COMMERCE_REVIEW_ACCEPTED
        or request.target_id not in accepted_targets
    ):
        raise CommerceConflictError("An accepted candidate mapping is immutable")
    return CommerceCandidateAcceptResponse(
        review_id=existing.id,
        candidate_id=candidate.id,
        status=existing.status,
        product_id=existing.target_product_id,
        competitor_product_id=existing.target_competitor_product_id,
        match_reason=existing.match_reason,
        match_confidence=existing.match_confidence,
    )


async def _reject_candidate(
    session: AsyncSession,
    *,
    candidate: CommerceDiscoveryCandidate,
    workspace_id: uuid.UUID,
    request: CommerceCandidateAcceptRequest,
) -> CommerceCandidateAcceptResponse:
    review = CommerceCandidateReview(
        candidate_id=candidate.id,
        workspace_id=workspace_id,
        project_id=candidate.project_id,
        status=request.status,
        review_note=request.review_note,
    )
    session.add(review)
    await session.commit()
    return CommerceCandidateAcceptResponse(
        review_id=review.id,
        candidate_id=candidate.id,
        status=review.status,
        product_id=None,
        competitor_product_id=None,
        match_reason="",
        match_confidence=0.0,
    )


async def _materialize_candidate(
    session: AsyncSession,
    *,
    candidate: CommerceDiscoveryCandidate,
    request: CommerceCandidateAcceptRequest,
    selected: CommerceMatchDecision | None,
) -> tuple[uuid.UUID | None, uuid.UUID | None]:
    if candidate.candidate_kind == COMMERCE_CANDIDATE_KIND_COMPETITOR:
        if selected is not None:
            return None, selected.target_id
        return None, await _new_competitor_product(
            session, candidate=candidate, request=request
        )
    if selected is not None:
        return selected.target_id, None
    return await _new_own_product(session, candidate=candidate), None


async def _new_competitor_product(
    session: AsyncSession,
    *,
    candidate: CommerceDiscoveryCandidate,
    request: CommerceCandidateAcceptRequest,
) -> uuid.UUID:
    competitor_id = request.competitor_id or candidate.competitor_id
    competitor = (
        await session.scalar(
            select(Competitor).where(
                Competitor.id == competitor_id,
                Competitor.project_id == candidate.project_id,
            )
        )
        if competitor_id
        else None
    )
    if competitor is None:
        raise CommerceDiscoveryNotFoundError("Competitor not found in this project")
    identity = dict(candidate.identity or {})
    product = CompetitorProduct(
        project_id=candidate.project_id,
        competitor_id=competitor.id,
        name=str(identity.get("name", "")),
        aliases=list(identity.get("aliases") or []),
        variants=list(identity.get("variants") or []),
        price=identity.get("price"),
        currency=str(identity.get("currency", "")),
        url=str(identity.get("url", "")),
        attributes=dict(identity.get("attributes") or {}),
        availability=str(identity.get("availability", "")),
        extraction_fresh_at=_utcnow(),
        source_candidate_id=candidate.id,
        source_artifact_id=candidate.artifact_id,
    )
    session.add(product)
    await session.flush()
    return product.id


async def _new_own_product(
    session: AsyncSession, *, candidate: CommerceDiscoveryCandidate
) -> uuid.UUID:
    identity = dict(candidate.identity or {})
    sku = str(identity.get("sku", "")) or (
        f"{COMMERCE_DISCOVERED_SKU_PREFIX}{candidate.id.hex[:12]}"
    )
    product = Product(
        project_id=candidate.project_id,
        sku=sku,
        name=str(identity.get("name", "")),
        aliases=list(identity.get("aliases") or []),
        variants=list(identity.get("variants") or []),
        price=identity.get("price"),
        currency=str(identity.get("currency", "")),
        url=str(identity.get("url", "")),
        attributes=dict(identity.get("attributes") or {}),
        origin=PRODUCT_ORIGIN_DISCOVERED,
        source_candidate_id=candidate.id,
        source_artifact_id=candidate.artifact_id,
    )
    session.add(product)
    await session.flush()
    return product.id


async def _persist_candidate_acceptance(
    session: AsyncSession,
    *,
    candidate: CommerceDiscoveryCandidate,
    workspace_id: uuid.UUID,
    request: CommerceCandidateAcceptRequest,
    selected: CommerceMatchDecision | None,
    product_id: uuid.UUID | None,
    competitor_product_id: uuid.UUID | None,
) -> CommerceCandidateReview:
    review = CommerceCandidateReview(
        candidate_id=candidate.id,
        workspace_id=workspace_id,
        project_id=candidate.project_id,
        status=COMMERCE_REVIEW_ACCEPTED,
        target_product_id=product_id,
        target_competitor_product_id=competitor_product_id,
        match_reason=(
            selected.reasons[0]
            if selected
            else COMMERCE_MATCH_REASON_REVIEWED_DISCOVERY
        ),
        match_confidence=(
            selected.confidence if selected else candidate.extraction_confidence
        ),
        review_note=request.review_note,
    )
    session.add(review)
    await session.commit()
    return review


def _snapshot_metrics(snapshot: ProductMetricSnapshot | None) -> dict[str, Any]:
    if snapshot is None:
        return {
            "mentions": 0,
            "sov": 0.0,
            "avg_rank": None,
            "price_accuracy": None,
            "attributes": {},
            "buyer_destinations": {},
        }
    metrics = snapshot.metrics or {}
    return {
        "mentions": snapshot.mention_count,
        "sov": snapshot.sov_share,
        "avg_rank": snapshot.avg_rank,
        "price_accuracy": snapshot.price_accuracy_rate,
        "attributes": metrics.get("attribute_dimension_frequency") or {},
        "buyer_destinations": metrics.get("buyer_destination_mix") or {},
    }


async def create_comparison_snapshot(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    competitor_id: uuid.UUID | None,
) -> CompetitorComparisonSnapshotResponse:
    await _project(session, workspace_id, project_id)
    own, competitors, snapshots = await _comparison_inputs(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        competitor_id=competitor_id,
    )
    own_metrics, competitor_metrics = _comparison_metric_maps(snapshots)
    rows = [
        _comparison_row(
            competitor_product,
            own=own,
            own_metrics=own_metrics,
            competitor_metrics=competitor_metrics,
        )
        for competitor_product in competitors[
            : commerce_intelligence_settings.comparison_max_entries
        ]
    ]
    truncated = len(competitors) > len(rows)
    comparison = {
        "coverage": {
            "own_total": len(own),
            "competitor_total": len(competitors),
            "matched": sum(1 for row in rows if row["own_product_id"]),
            "unmatched": sum(1 for row in rows if not row["own_product_id"]),
        },
        "items": rows,
    }
    snapshot = CompetitorComparisonSnapshot(
        workspace_id=workspace_id,
        project_id=project_id,
        competitor_id=competitor_id,
        source_catalog_ids={
            "products": [str(product.id) for product in own],
            "competitor_products": [str(product.id) for product in competitors],
        },
        source_artifact_ids=_comparison_artifact_ids(own, competitors),
        comparison=json.loads(_canonical(comparison)),
        truncated=truncated,
    )
    session.add(snapshot)
    await session.commit()
    return _comparison_response(snapshot)


async def _comparison_inputs(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    competitor_id: uuid.UUID | None,
) -> tuple[list[Product], list[CompetitorProduct], list[ProductMetricSnapshot]]:
    own = list(
        (
            await session.scalars(
                select(Product)
                .where(Product.project_id == project_id)
                .join(Project, Product.project_id == Project.id)
                .where(Project.workspace_id == workspace_id)
                .order_by(Product.id)
            )
        ).all()
    )
    competitors_stmt = (
        select(CompetitorProduct)
        .join(Project, CompetitorProduct.project_id == Project.id)
        .where(
            CompetitorProduct.project_id == project_id,
            Project.workspace_id == workspace_id,
        )
    )
    if competitor_id is not None:
        competitors_stmt = competitors_stmt.where(
            CompetitorProduct.competitor_id == competitor_id
        )
    competitors = list(
        (await session.scalars(competitors_stmt.order_by(CompetitorProduct.id))).all()
    )
    snapshots = list(
        (
            await session.scalars(
                select(ProductMetricSnapshot).where(
                    ProductMetricSnapshot.workspace_id == workspace_id,
                    ProductMetricSnapshot.project_id == project_id,
                )
            )
        ).all()
    )
    return own, competitors, snapshots


def _comparison_metric_maps(
    snapshots: list[ProductMetricSnapshot],
) -> tuple[
    dict[uuid.UUID, ProductMetricSnapshot], dict[uuid.UUID, ProductMetricSnapshot]
]:
    own_metrics = {
        item.product_id: item for item in snapshots if item.product_id is not None
    }
    competitor_metrics = {
        item.competitor_product_id: item
        for item in snapshots
        if item.competitor_product_id is not None
    }
    return own_metrics, competitor_metrics


def _matched_own_product(
    competitor_product: CompetitorProduct, own: list[Product]
) -> tuple[Product | None, Any | None]:
    matches = match_candidate(
        _competitor_entry(competitor_product),
        [_product_entry(product) for product in own],
    )
    selected = matches[0] if matches else None
    product = next(
        (item for item in own if selected and item.id == selected.target_id), None
    )
    return product, selected


def _own_attributes(own_product: Product | None) -> dict[str, Any]:
    return dict(own_product.attributes or {}) if own_product else {}


def _comparison_prices(
    own_product: Product | None, competitor_product: CompetitorProduct
) -> list[float | None]:
    return [
        float(own_product.price)
        if own_product and own_product.price is not None
        else None,
        float(competitor_product.price)
        if competitor_product.price is not None
        else None,
    ]


def _comparison_freshness(
    own_product: Product | None, competitor_product: CompetitorProduct
) -> list[str | None]:
    return [
        own_product.updated_at.isoformat() if own_product else None,
        competitor_product.extraction_fresh_at.isoformat()
        if competitor_product.extraction_fresh_at
        else None,
    ]


def _comparison_differences(
    own_product: Product | None, competitor_product: CompetitorProduct
) -> dict[str, Any]:
    own_attributes = _own_attributes(own_product)
    competitor_attributes = dict(competitor_product.attributes or {})
    return {
        "price": _comparison_prices(own_product, competitor_product),
        "availability": [
            str(own_attributes.get("availability", "")),
            competitor_product.availability,
        ],
        "variants": [
            list(own_product.variants or []) if own_product else [],
            list(competitor_product.variants or []),
        ],
        "identifiers": [own_attributes, competitor_attributes],
        "attributes": [own_attributes, competitor_attributes],
        "schema_readiness": product_completeness(own_product) if own_product else None,
        "freshness": _comparison_freshness(own_product, competitor_product),
    }


def _comparison_row(
    competitor_product: CompetitorProduct,
    *,
    own: list[Product],
    own_metrics: dict[uuid.UUID, ProductMetricSnapshot],
    competitor_metrics: dict[uuid.UUID, ProductMetricSnapshot],
) -> dict[str, Any]:
    own_product, selected = _matched_own_product(competitor_product, own)
    return {
        "competitor_product_id": str(competitor_product.id),
        "own_product_id": str(own_product.id) if own_product else None,
        "match": {
            "confidence": selected.confidence if selected else 0.0,
            "reasons": list(selected.reasons) if selected else [],
            "review_required": selected.review_required if selected else False,
        },
        "competitor": _competitor_entry(competitor_product),
        "own": _product_entry(own_product) if own_product else None,
        "differences": _comparison_differences(own_product, competitor_product),
        "ai_conversation": {
            "own": _snapshot_metrics(
                own_metrics.get(own_product.id) if own_product else None
            ),
            "competitor": _snapshot_metrics(
                competitor_metrics.get(competitor_product.id)
            ),
        },
        "evidence_kind": {
            "own": COMMERCE_EVIDENCE_LABEL_CATALOG,
            "competitor": (
                COMMERCE_EVIDENCE_LABEL_DISCOVERY
                if competitor_product.source_artifact_id
                else COMMERCE_EVIDENCE_LABEL_CATALOG
            ),
        },
    }


def _comparison_artifact_ids(
    own: list[Product], competitors: list[CompetitorProduct]
) -> list[str]:
    values = {
        *(product.source_artifact_id for product in own),
        *(product.source_artifact_id for product in competitors),
    }
    ordered = sorted(value for value in values if value is not None)
    return [str(value) for value in ordered]


def _comparison_response(
    snapshot: CompetitorComparisonSnapshot,
) -> CompetitorComparisonSnapshotResponse:
    source = dict(snapshot.source_catalog_ids or {})
    return CompetitorComparisonSnapshotResponse(
        id=snapshot.id,
        project_id=snapshot.project_id,
        competitor_id=snapshot.competitor_id,
        source_catalog_ids={
            key: [str(value) for value in values] for key, values in source.items()
        },
        source_artifact_ids=[
            str(value) for value in snapshot.source_artifact_ids or []
        ],
        matcher_version=snapshot.matcher_version,
        comparison_version=snapshot.comparison_version,
        comparison=dict(snapshot.comparison or {}),
        truncated=snapshot.truncated,
        created_at=snapshot.created_at,
    )


async def list_comparison_snapshots(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> list[CompetitorComparisonSnapshotResponse]:
    await _project(session, workspace_id, project_id)
    snapshots = list(
        (
            await session.scalars(
                select(CompetitorComparisonSnapshot)
                .where(
                    CompetitorComparisonSnapshot.workspace_id == workspace_id,
                    CompetitorComparisonSnapshot.project_id == project_id,
                )
                .order_by(
                    CompetitorComparisonSnapshot.created_at.desc(),
                    CompetitorComparisonSnapshot.id.desc(),
                )
            )
        ).all()
    )
    return [_comparison_response(snapshot) for snapshot in snapshots]
