# Product visibility projections (invariant 7 — persisted rows only).
#
# Every function here reads persisted rows (``ProductMetricSnapshot`` /
# ``ProductResponseAnalysis`` / ``ProductMention`` / ``MerchantMention`` /
# ``Audit``) and NEVER calls a provider and NEVER recomputes a score. They
# back the product visibility/evidence/export endpoints. All queries are
# workspace-scoped (invariant 5). Mirrors the focused ``domain/analysis`` reads.
#
# Mixed-version reads: a v2 re-score coexists with v1 rows. The projection
# prefers the current analyzer/rule snapshot per entry but still serves v1
# data, deriving ``price_mismatch_rate`` from the v1 price accuracy and
# falling back to ``match | mismatch | null`` relations (never inventing
# higher/lower direction for v1 evidence).
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.product_scoring import ProductScoringConfig
from app.analysis.product_service import build_product_scoring_config
from app.core.config.audits import (
    AUDIT_SCOPE_COMMERCE,
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
)
from app.core.config.commerce import (
    PRICE_RELATION_MATCH,
    PRICE_RELATION_MISMATCH,
)
from app.core.config.products import (
    PRODUCT_ANALYZER_VERSION,
    PRODUCT_SCORING_RULE_VERSION,
)
from app.core.config.provider_catalog import LOGICAL_ENGINES
from app.domain.analysis.errors import AnalysisNotFoundError, TrendQueryError
from app.domain.products.commerce_citations import commerce_citation_comparison
from app.domain.products.schemas import (
    FrozenPromptContext,
    ProductVisibilityEntry,
    ProductVisibilityResponse,
    ProductVisibilitySummary,
    ProductVisibilityTrendPoint,
    ProductVisibilityTrendResponse,
)
from app.models.audit import Audit, AuditPromptSnapshot, AuditTask
from app.models.product import (
    Product,
    ProductMention,
    ProductMetricSnapshot,
    ProductResponseAnalysis,
)
from app.models.project import Project

# A run is projection-eligible when fully or partially completed (mirror B6).
_DASHBOARD_STATUSES = (
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
)
_AUDIT_RECENCY_ORDER = (Audit.completed_at.desc().nullslast(), Audit.created_at.desc())

_AUDIT_NOT_FOUND = "Audit not found"

_EMPTY_DESTINATION_MIX: dict[str, Any] = {"total": 0, "by_kind": [], "by_domain": []}


async def _conversation_context(
    session: AsyncSession, *, audit_id: uuid.UUID
) -> dict[
    tuple[str, uuid.UUID], tuple[float | None, list[FrozenPromptContext], list[str]]
]:
    """Persisted prompt coverage/context per catalog entry (never inferred).

    The audit snapshot supplies frozen text/theme/intent, while mentions tell
    us which prompt slots actually discussed an entry. This is a projection of
    existing evidence rather than a new scoring pass.
    """
    prompt_count = int(
        await session.scalar(
            select(func.count())
            .select_from(AuditPromptSnapshot)
            .where(AuditPromptSnapshot.audit_id == audit_id)
        )
        or 0
    )
    rows = (
        await session.execute(
            select(ProductMention, AuditPromptSnapshot)
            .join(
                ProductResponseAnalysis,
                ProductResponseAnalysis.id == ProductMention.analysis_id,
            )
            .join(AuditTask, AuditTask.id == ProductResponseAnalysis.task_id)
            .join(
                AuditPromptSnapshot,
                AuditPromptSnapshot.id == AuditTask.prompt_snapshot_id,
            )
            .where(ProductMention.audit_id == audit_id)
        )
    ).all()
    grouped: dict[tuple[str, uuid.UUID], dict[int, FrozenPromptContext]] = {}
    for mention, prompt in rows:
        entry_id = mention.product_id
        if entry_id is None:
            continue
        grouped.setdefault(("product", entry_id), {})[prompt.prompt_index] = (
            FrozenPromptContext(
                prompt_index=prompt.prompt_index,
                text=prompt.text,
                theme=prompt.theme,
                intent=prompt.intent,
            )
        )
    return {
        key: (
            round(len(prompts) / prompt_count, 4) if prompt_count else None,
            [prompts[index] for index in sorted(prompts)],
            sorted({prompt.theme for prompt in prompts.values() if prompt.theme}),
        )
        for key, prompts in grouped.items()
    }


def _project_price_relation(
    price_relation: str | None, price_matches_catalog: bool | None
) -> str | None:
    """Mixed-version relation read: persisted v2 relation, else v1 fallback.

    Returns the persisted ``price_relation`` when non-null; otherwise maps
    the legacy boolean (True -> ``match``, False -> ``mismatch``, None ->
    null). Higher/lower direction is NEVER inferred for v1 rows.
    """
    if price_relation is not None:
        return price_relation
    if price_matches_catalog is True:
        return PRICE_RELATION_MATCH
    if price_matches_catalog is False:
        return PRICE_RELATION_MISMATCH
    return None


def _normalize_aggregate(aggregate: dict[str, Any]) -> dict[str, Any]:
    """Project one persisted aggregate dict into the pinned response shape.

    Applies the mixed-version rule: a v1 aggregate (no persisted
    ``price_relation_counts``) reads an empty relation-count map and derives
    ``price_mismatch_rate`` from its price accuracy (null when that is
    null); v2 aggregates serve their persisted values.
    """
    relation_counts = aggregate.get("price_relation_counts")
    price_accuracy = aggregate.get("price_accuracy_rate")
    if relation_counts:
        mismatch_rate = aggregate.get("price_mismatch_rate")
    else:
        # v1 fallback: direction was never persisted, so only the derived
        # mismatch rate is available.
        relation_counts = {}
        mismatch_rate = None if price_accuracy is None else round(1 - price_accuracy, 4)
    return {
        "mention_count": int(aggregate.get("mention_count") or 0),
        "sov_share": float(aggregate.get("sov_share") or 0.0),
        "avg_rank": aggregate.get("avg_rank"),
        "rank_distribution": dict(aggregate.get("rank_distribution") or {}),
        "price_mention_count": int(aggregate.get("price_mention_count") or 0),
        "price_accuracy_rate": price_accuracy,
        "win_rate": aggregate.get("win_rate"),
        "price_relation_counts": dict(relation_counts),
        "price_mismatch_rate": mismatch_rate,
        "attribute_dimension_frequency": {
            str(group): dict(dimensions)
            for group, dimensions in (
                aggregate.get("attribute_dimension_frequency") or {}
            ).items()
        },
        "buyer_destination_mix": aggregate.get("buyer_destination_mix")
        or dict(_EMPTY_DESTINATION_MIX),
    }


def _overall_metrics(snapshot: ProductMetricSnapshot) -> dict[str, Any]:
    metrics = snapshot.metrics or {}
    return _normalize_aggregate(
        {
            **metrics,
            "mention_count": snapshot.mention_count,
            "sov_share": snapshot.sov_share,
            "avg_rank": snapshot.avg_rank,
            "rank_distribution": dict(snapshot.rank_distribution or {}),
            "price_mention_count": snapshot.price_mention_count,
            "price_accuracy_rate": snapshot.price_accuracy_rate,
            "win_rate": snapshot.win_rate,
            "price_mismatch_rate": snapshot.price_mismatch_rate,
        }
    )


def _entry_metrics(
    snapshot: ProductMetricSnapshot,
    engine: str | None = None,
) -> dict[str, Any]:
    """One snapshot's entry metrics, engine-sliced (persisted only).

    With ``engine=None`` the overall snapshot columns are served. With an
    engine the PERSISTED per-engine aggregate (written at finalize) is
    served. Missing data reads as a zero-filled aggregate — never a
    recompute (invariant 7).
    """
    if engine is None:
        return _overall_metrics(snapshot)
    scope: dict[str, Any] = ((snapshot.metrics or {}).get("per_engine") or {}).get(
        engine
    ) or {}
    return _normalize_aggregate(scope)


def _is_current_version(snapshot: ProductMetricSnapshot) -> bool:
    return (
        snapshot.product_analyzer_version == PRODUCT_ANALYZER_VERSION
        and snapshot.product_scoring_rule_version == PRODUCT_SCORING_RULE_VERSION
    )


def select_current_snapshots(
    snapshots: list[ProductMetricSnapshot],
) -> dict[str, ProductMetricSnapshot]:
    """One snapshot per frozen entry id; the CURRENT version wins ties.

    v1 and v2 snapshots coexist for the same entry (widened unique
    indexes); the projection serves the current version when both exist
    and falls back to the v1 row otherwise (v1 rows are never mutated).

    Order-independent: the input list may be in any order, since selection
    is by version, not position.
    """
    by_entry: dict[str, ProductMetricSnapshot] = {}
    for snapshot in snapshots:
        entry_id = _snapshot_entry_id(snapshot)
        existing = by_entry.get(entry_id)
        if existing is None or (
            _is_current_version(snapshot) and not _is_current_version(existing)
        ):
            by_entry[entry_id] = snapshot
    return by_entry


ConversationContext = dict[
    tuple[str, uuid.UUID], tuple[float | None, list[FrozenPromptContext], list[str]]
]


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _top_three(metrics: dict[str, Any]) -> int:
    distribution = metrics["rank_distribution"]
    return int(distribution.get("top_1") or 0) + int(distribution.get("top_2_3") or 0)


async def _analysis_count(
    session: AsyncSession, *, audit_id: uuid.UUID, engine: str | None
) -> int:
    statement = (
        select(func.count())
        .select_from(ProductResponseAnalysis)
        .where(ProductResponseAnalysis.audit_id == audit_id)
    )
    if engine is not None:
        statement = statement.where(ProductResponseAnalysis.logical_engine == engine)
    return int(await session.scalar(statement) or 0)


def _engine_coverage(snapshot: ProductMetricSnapshot, engine: str | None) -> int:
    per_engine = (snapshot.metrics or {}).get("per_engine") or {}
    if engine is not None:
        aggregate = per_engine.get(engine) or {}
        return int(int(aggregate.get("mention_count") or 0) > 0)
    return sum(
        int(int((aggregate or {}).get("mention_count") or 0) > 0)
        for aggregate in per_engine.values()
    )


def _own_visibility_entries(
    config: ProductScoringConfig,
    by_entry: dict[str, ProductMetricSnapshot],
    sliced: dict[str, dict[str, Any]],
    conversation: ConversationContext,
    total_analyses: int,
    previous_visibility: dict[uuid.UUID, float],
    engine: str | None,
) -> list[ProductVisibilityEntry]:
    projected: list[ProductVisibilityEntry] = []
    for entry in config.products:
        snapshot = by_entry.get(entry.id)
        if snapshot is None:
            continue
        metrics = sliced[entry.id]
        coverage, prompts, themes = (
            conversation.get(("product", snapshot.product_id), (None, [], []))
            if snapshot.product_id is not None
            else (None, [], [])
        )
        projected.append(
            ProductVisibilityEntry(
                product_id=snapshot.product_id,
                sku=entry.sku,
                name=entry.name,
                category=str((entry.attributes or {}).get("category") or ""),
                product_analyzer_version=snapshot.product_analyzer_version,
                mention_count=metrics["mention_count"],
                sov_share=metrics["sov_share"],
                avg_rank=metrics["avg_rank"],
                rank_distribution=metrics["rank_distribution"],
                price_mention_count=metrics["price_mention_count"],
                price_accuracy_rate=metrics["price_accuracy_rate"],
                win_rate=metrics["win_rate"],
                price_mismatch_rate=metrics["price_mismatch_rate"],
                price_relation_counts=metrics["price_relation_counts"],
                attribute_dimension_frequency=metrics["attribute_dimension_frequency"],
                buyer_destination_mix=metrics["buyer_destination_mix"],
                prompt_coverage=coverage,
                frozen_prompt_context=prompts,
                conversation_themes=themes,
                visibility_rate=_rate(metrics["mention_count"], total_analyses),
                top_three_rate=_rate(_top_three(metrics), total_analyses),
                engine_coverage=_engine_coverage(snapshot, engine),
                visibility_delta=(
                    round(
                        _rate(metrics["mention_count"], total_analyses)
                        - previous_visibility[snapshot.product_id],
                        4,
                    )
                    if snapshot.product_id in previous_visibility
                    else None
                ),
            )
        )
    return projected


async def get_product_visibility(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None = None,
    engine: str | None = None,
) -> ProductVisibilityResponse:
    """Serve the selected-audit product dashboard projection.

    Defaults to the project's latest completed/partially-completed audit that
    has product snapshots when ``audit_id`` is omitted. Identity (sku/name/
    competitor_name) comes from the audit's FROZEN configuration so the
    projection survives later catalog deletes. Pure read of persisted rows;
    no provider call (invariant 7).

    ``engine`` slices every entry to its PERSISTED per-engine aggregate
    (stored in the snapshot at finalize) — still a pure projection, never a
    recompute. An unknown engine raises ``TrendQueryError`` (HTTP 422).
    """
    if engine is not None and engine not in LOGICAL_ENGINES:
        raise TrendQueryError(f"Unknown logical engine: {engine!r}")
    audit, snapshots = await _load_audit_and_snapshots(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        audit_id=audit_id,
    )

    config = build_product_scoring_config(audit.configuration)
    by_entry = select_current_snapshots(snapshots)

    sliced = {
        entry_id: _entry_metrics(snapshot, engine)
        for entry_id, snapshot in by_entry.items()
    }
    conversation = await _conversation_context(session, audit_id=audit.id)

    total_analyses = await _analysis_count(session, audit_id=audit.id, engine=engine)
    previous_visibility = await _previous_visibility_rates(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        before=cast(datetime, audit.completed_at),
        engine=engine,
    )
    products = _own_visibility_entries(
        config,
        by_entry,
        sliced,
        conversation,
        total_analyses,
        previous_visibility,
        engine,
    )
    # Response-level version label: the first catalog entry's selected
    # snapshot (deterministic catalog order). Row-level DTOs carry their own
    # version, so a mixed-version audit is still labelled correctly per row.
    selected_entry_ids = [entry.id for entry in config.products]
    selected = [
        by_entry[entry_id] for entry_id in selected_entry_ids if entry_id in by_entry
    ]
    if not selected:
        raise AnalysisNotFoundError("Product metrics not available for audit")
    first = selected[0]
    return ProductVisibilityResponse(
        project_id=project_id,
        audit_id=audit.id,
        audit_status=audit.status,
        product_analyzer_version=first.product_analyzer_version,
        product_scoring_rule_version=first.product_scoring_rule_version,
        total_mentions=sum(product.mention_count for product in products),
        total_analyses=total_analyses,
        summary=_visibility_summary(products, total_analyses),
        products=products,
        citation_comparison=await commerce_citation_comparison(
            session, audit=audit, config=config
        ),
        created_at=max(s.created_at for s in selected),
    )


def _visibility_summary(
    products: list[ProductVisibilityEntry],
    total_analyses: int,
) -> ProductVisibilitySummary:
    denominator = total_analyses * len(products)
    ranked = [entry for entry in products if entry.avg_rank is not None]
    rank_mentions = sum(entry.mention_count for entry in ranked)
    average_rank = (
        round(
            sum((entry.avg_rank or 0) * entry.mention_count for entry in ranked)
            / rank_mentions,
            2,
        )
        if rank_mentions
        else None
    )
    return ProductVisibilitySummary(
        products_tracked=len(products),
        products_visible=sum(entry.mention_count > 0 for entry in products),
        visibility_rate=_rate(
            sum(entry.mention_count for entry in products), denominator
        ),
        top_three_rate=_rate(
            sum(
                _top_three({"rank_distribution": entry.rank_distribution})
                for entry in products
            ),
            denominator,
        ),
        average_rank=average_rank,
    )


async def _previous_visibility_rates(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    before: datetime,
    engine: str | None,
) -> dict[uuid.UUID, float]:
    previous_audit_id = await session.scalar(
        select(Audit.id)
        .where(
            Audit.workspace_id == workspace_id,
            Audit.project_id == project_id,
            Audit.status.in_(_DASHBOARD_STATUSES),
            Audit.completed_at < before,
            select(ProductMetricSnapshot.id)
            .where(ProductMetricSnapshot.audit_id == Audit.id)
            .exists(),
        )
        .order_by(*_AUDIT_RECENCY_ORDER)
        .limit(1)
    )
    if previous_audit_id is None:
        return {}
    snapshots = list(
        (
            await session.scalars(
                select(ProductMetricSnapshot).where(
                    ProductMetricSnapshot.audit_id == previous_audit_id,
                    ProductMetricSnapshot.workspace_id == workspace_id,
                    ProductMetricSnapshot.product_id.is_not(None),
                )
            )
        ).all()
    )
    total = await _analysis_count(session, audit_id=previous_audit_id, engine=engine)
    return {
        snapshot.product_id: _rate(
            _entry_metrics(snapshot, engine)["mention_count"], total
        )
        for snapshot in select_current_snapshots(snapshots).values()
        if snapshot.product_id is not None
    }


async def get_product_visibility_trend(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    product_id: uuid.UUID,
    engine: str | None = None,
    limit: int = 3,
) -> ProductVisibilityTrendResponse:
    if engine is not None and engine not in LOGICAL_ENGINES:
        raise TrendQueryError(f"Unknown logical engine: {engine!r}")
    product = await session.scalar(
        select(Product)
        .join(Project, Product.project_id == Project.id)
        .where(
            Product.id == product_id,
            Product.project_id == project_id,
            Project.workspace_id == workspace_id,
        )
    )
    if product is None:
        raise AnalysisNotFoundError("Product not found")
    audit_ids = await _trend_audit_ids(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        product_id=product_id,
        limit=limit,
    )
    audits, selected = await _trend_sources(
        session, audit_ids=audit_ids, product_id=product_id
    )
    totals = await _trend_totals(session, audit_ids=audit_ids, engine=engine)
    points = _trend_points(
        audit_ids=audit_ids,
        audits=audits,
        snapshots=selected,
        totals=totals,
        engine=engine,
    )
    return ProductVisibilityTrendResponse(
        project_id=project_id,
        product_id=product.id,
        sku=product.sku,
        name=product.name,
        points=points,
    )


async def _trend_audit_ids(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    product_id: uuid.UUID,
    limit: int,
) -> list[uuid.UUID]:
    return list(
        (
            await session.scalars(
                select(Audit.id)
                .where(
                    Audit.workspace_id == workspace_id,
                    Audit.project_id == project_id,
                    Audit.status.in_(_DASHBOARD_STATUSES),
                    select(ProductMetricSnapshot.id)
                    .where(
                        ProductMetricSnapshot.audit_id == Audit.id,
                        ProductMetricSnapshot.product_id == product_id,
                    )
                    .exists(),
                )
                .order_by(*_AUDIT_RECENCY_ORDER)
                .limit(limit)
            )
        ).all()
    )


async def _trend_sources(
    session: AsyncSession,
    *,
    audit_ids: list[uuid.UUID],
    product_id: uuid.UUID,
) -> tuple[dict[uuid.UUID, Audit], dict[uuid.UUID, ProductMetricSnapshot]]:
    audits = {
        row.id: row
        for row in (
            await session.scalars(select(Audit).where(Audit.id.in_(audit_ids)))
        ).all()
    }
    snapshots = list(
        (
            await session.scalars(
                select(ProductMetricSnapshot).where(
                    ProductMetricSnapshot.audit_id.in_(audit_ids),
                    ProductMetricSnapshot.product_id == product_id,
                )
            )
        ).all()
    )
    selected: dict[uuid.UUID, ProductMetricSnapshot] = {}
    for snapshot in snapshots:
        existing = selected.get(snapshot.audit_id)
        if existing is None or (
            _is_current_version(snapshot) and not _is_current_version(existing)
        ):
            selected[snapshot.audit_id] = snapshot
    return audits, selected


async def _trend_totals(
    session: AsyncSession,
    *,
    audit_ids: list[uuid.UUID],
    engine: str | None,
) -> dict[uuid.UUID, int]:
    totals_statement = select(ProductResponseAnalysis.audit_id, func.count()).where(
        ProductResponseAnalysis.audit_id.in_(audit_ids)
    )
    if engine is not None:
        totals_statement = totals_statement.where(
            ProductResponseAnalysis.logical_engine == engine
        )
    result = await session.execute(
        totals_statement.group_by(ProductResponseAnalysis.audit_id)
    )
    total_rows = result.all()
    return {audit_id: count for audit_id, count in total_rows}


def _trend_points(
    *,
    audit_ids: list[uuid.UUID],
    audits: dict[uuid.UUID, Audit],
    snapshots: dict[uuid.UUID, ProductMetricSnapshot],
    totals: dict[uuid.UUID, int],
    engine: str | None,
) -> list[ProductVisibilityTrendPoint]:
    points: list[ProductVisibilityTrendPoint] = []
    for audit_id in reversed(audit_ids):
        trend_snapshot = snapshots.get(audit_id)
        audit = audits.get(audit_id)
        if trend_snapshot is None or audit is None:
            continue
        metrics = _entry_metrics(trend_snapshot, engine)
        denominator = int(totals.get(audit_id) or 0)
        points.append(
            ProductVisibilityTrendPoint(
                audit_id=audit_id,
                observed_at=audit.completed_at or audit.created_at,
                visibility_rate=_rate(metrics["mention_count"], denominator),
                top_three_rate=_rate(_top_three(metrics), denominator),
                average_rank=metrics["avg_rank"],
            )
        )
    return points


def _snapshot_entry_id(snapshot: ProductMetricSnapshot) -> str:
    """Frozen catalog entry id for a snapshot.

    The live FK is SET NULL when the catalog row is deleted, so fall back to
    the frozen ``entry_id`` persisted in ``metrics`` at finalize time.
    """
    live = snapshot.product_id
    if live is not None:
        return str(live)
    return str((snapshot.metrics or {}).get("entry_id") or "")


async def _load_audit_and_snapshots(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    audit_id: uuid.UUID | None,
) -> tuple[Audit, list[ProductMetricSnapshot]]:
    """Resolve the audit + load its product snapshots (shared resolution).

    Defaults to the latest dashboard-eligible audit with product snapshots
    when ``audit_id`` is omitted. 404-class ``AnalysisNotFoundError`` when
    the audit is missing/cross-workspace or has no product snapshots.
    """
    if audit_id is None:
        audit_id = await _latest_product_audit_id(
            session, workspace_id=workspace_id, project_id=project_id
        )
        if audit_id is None:
            raise AnalysisNotFoundError(
                "No completed audit with product metrics for project"
            )
    audit = await session.scalar(
        select(Audit).where(
            Audit.id == audit_id,
            Audit.workspace_id == workspace_id,
            Audit.project_id == project_id,
        )
    )
    if audit is None:
        raise AnalysisNotFoundError(_AUDIT_NOT_FOUND)
    if audit.audit_scope != AUDIT_SCOPE_COMMERCE:
        raise AnalysisNotFoundError("Audit is not a Commerce audit")
    snapshots = list(
        (
            await session.scalars(
                select(ProductMetricSnapshot).where(
                    ProductMetricSnapshot.audit_id == audit.id,
                    ProductMetricSnapshot.workspace_id == workspace_id,
                )
            )
        ).all()
    )
    if not snapshots:
        raise AnalysisNotFoundError("Product metrics not available for audit")
    return audit, snapshots


async def _latest_product_audit_id(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> uuid.UUID | None:
    """Latest dashboard-eligible audit having >=1 product snapshot."""
    has_snapshots = (
        select(ProductMetricSnapshot.id)
        .where(ProductMetricSnapshot.audit_id == Audit.id)
        .exists()
    )
    return await session.scalar(
        select(Audit.id)
        .where(
            Audit.workspace_id == workspace_id,
            Audit.project_id == project_id,
            Audit.status.in_(_DASHBOARD_STATUSES),
            Audit.audit_scope == AUDIT_SCOPE_COMMERCE,
            has_snapshots,
        )
        .order_by(*_AUDIT_RECENCY_ORDER)
        .limit(1)
    )
