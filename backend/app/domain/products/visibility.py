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
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.product_scoring import ProductScoringConfig
from app.analysis.product_service import build_product_scoring_config
from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
)
from app.core.config.commerce import (
    PRICE_RELATION_MATCH,
    PRICE_RELATION_MISMATCH,
    SHOPPING_SURFACE_MEASUREMENT,
)
from app.core.config.products import (
    PRODUCT_ANALYZER_VERSION,
    PRODUCT_SCORING_RULE_VERSION,
)
from app.core.config.provider_catalog import LOGICAL_ENGINES
from app.domain.analysis.errors import AnalysisNotFoundError, TrendQueryError
from app.domain.products.schemas import (
    CompetitorProductVisibilityEntry,
    FrozenPromptContext,
    ProductVisibilityEntry,
    ProductVisibilityResponse,
)
from app.models.audit import Audit, AuditPromptSnapshot, AuditTask
from app.models.product import (
    ProductMention,
    ProductMetricSnapshot,
    ProductResponseAnalysis,
)

# A run is projection-eligible when fully or partially completed (mirror B6).
_DASHBOARD_STATUSES = (
    AUDIT_STATUS_COMPLETED,
    AUDIT_STATUS_PARTIALLY_COMPLETED,
)

# Single source for the repeated "audit missing" detail (asserted by tests).
_AUDIT_NOT_FOUND = "Audit not found"

# Zero-value fallbacks for the strict JSONB shapes (v1 rows / no data).
_EMPTY_DESTINATION_MIX: dict[str, Any] = {"total": 0, "by_kind": [], "by_domain": []}
_EMPTY_CO_PLACEMENT: dict[str, Any] = {"items": [], "truncated": False}


async def _conversation_context(
    session: AsyncSession, *, audit_id: uuid.UUID, surface: str
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
            .where(ProductResponseAnalysis.shopping_surface == surface)
        )
    ).all()
    grouped: dict[tuple[str, uuid.UUID], dict[int, FrozenPromptContext]] = {}
    for mention, prompt in rows:
        entry_id = mention.product_id or mention.competitor_product_id
        if entry_id is None:
            continue
        kind = "product" if mention.product_id is not None else "competitor_product"
        grouped.setdefault((kind, entry_id), {})[prompt.prompt_index] = (
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
        "competitor_co_placement": aggregate.get("competitor_co_placement")
        or dict(_EMPTY_CO_PLACEMENT),
    }


def _overall_metrics(snapshot: ProductMetricSnapshot) -> dict[str, Any]:
    metrics = snapshot.metrics or {}
    measurement = (metrics.get("per_surface") or {}).get(SHOPPING_SURFACE_MEASUREMENT)
    if measurement is not None:
        return _normalize_aggregate(measurement)
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
    surface: str = SHOPPING_SURFACE_MEASUREMENT,
) -> dict[str, Any]:
    """One snapshot's entry metrics, engine/surface-sliced (persisted only).

    With ``engine=None`` on the measurement surface the overall snapshot
    columns are served. With an engine the PERSISTED per-engine aggregate
    (written at finalize) is served; a non-empty surface reads
    ``metrics["per_surface"][surface]`` then its nested per-engine slice.
    Missing data reads as a zero-filled aggregate — never a recompute
    (invariant 7).
    """
    if surface == SHOPPING_SURFACE_MEASUREMENT and engine is None:
        # Current snapshots persist an exact measurement slice beside future
        # probe surfaces. Prefer it so probe analyses cannot inflate the
        # default dashboard; legacy snapshots without ``per_surface`` retain
        # their historical snapshot-column fallback.
        return _overall_metrics(snapshot)
    metrics = snapshot.metrics or {}
    if surface == SHOPPING_SURFACE_MEASUREMENT:
        scope: dict[str, Any] = metrics
    else:
        scope = (metrics.get("per_surface") or {}).get(surface) or {}
    if engine is not None:
        scope = (scope.get("per_engine") or {}).get(engine) or {}
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


async def _available_surfaces(
    session: AsyncSession, *, audit_id: uuid.UUID
) -> list[str]:
    """Distinct persisted analysis surfaces ∪ {""}: measurement first."""
    persisted = {
        str(surface)
        for surface in (
            await session.scalars(
                select(ProductResponseAnalysis.shopping_surface)
                .where(ProductResponseAnalysis.audit_id == audit_id)
                .distinct()
            )
        ).all()
    }
    persisted.add(SHOPPING_SURFACE_MEASUREMENT)
    return [SHOPPING_SURFACE_MEASUREMENT] + sorted(
        surface for surface in persisted if surface != SHOPPING_SURFACE_MEASUREMENT
    )


ConversationContext = dict[
    tuple[str, uuid.UUID], tuple[float | None, list[FrozenPromptContext], list[str]]
]


def _own_visibility_entries(
    config: ProductScoringConfig,
    by_entry: dict[str, ProductMetricSnapshot],
    sliced: dict[str, dict[str, Any]],
    conversation: ConversationContext,
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
                competitor_co_placement=metrics["competitor_co_placement"],
                prompt_coverage=coverage,
                frozen_prompt_context=prompts,
                conversation_themes=themes,
            )
        )
    return projected


def _competitor_visibility_entries(
    config: ProductScoringConfig,
    by_entry: dict[str, ProductMetricSnapshot],
    sliced: dict[str, dict[str, Any]],
    conversation: ConversationContext,
) -> list[CompetitorProductVisibilityEntry]:
    projected: list[CompetitorProductVisibilityEntry] = []
    for entry in config.competitor_products:
        snapshot = by_entry.get(entry.id)
        if snapshot is None:
            continue
        metrics = sliced[entry.id]
        coverage, prompts, themes = (
            conversation.get(
                ("competitor_product", snapshot.competitor_product_id),
                (None, [], []),
            )
            if snapshot.competitor_product_id is not None
            else (None, [], [])
        )
        projected.append(
            CompetitorProductVisibilityEntry(
                competitor_product_id=snapshot.competitor_product_id,
                competitor_name=entry.competitor,
                name=entry.name,
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
                competitor_co_placement=metrics["competitor_co_placement"],
                prompt_coverage=coverage,
                frozen_prompt_context=prompts,
                conversation_themes=themes,
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
    surface: str = SHOPPING_SURFACE_MEASUREMENT,
) -> ProductVisibilityResponse:
    """Serve the selected-audit product dashboard projection.

    Defaults to the project's latest completed/partially-completed audit that
    has product snapshots when ``audit_id`` is omitted. Identity (sku/name/
    competitor_name) comes from the audit's FROZEN configuration so the
    projection survives later catalog deletes. Pure read of persisted rows;
    no provider call (invariant 7).

    ``engine`` slices every entry to its PERSISTED per-engine aggregate
    (stored in the snapshot at finalize) — still a pure projection, never a
    recompute. ``surface`` selects the persisted per-surface aggregate
    (measurement "" by default; surfaces never aggregate together). An
    unknown engine raises ``TrendQueryError`` (HTTP 422).
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
        entry_id: _entry_metrics(snapshot, engine, surface)
        for entry_id, snapshot in by_entry.items()
    }
    conversation = await _conversation_context(
        session, audit_id=audit.id, surface=surface
    )

    products = _own_visibility_entries(config, by_entry, sliced, conversation)
    competitor_products = _competitor_visibility_entries(
        config, by_entry, sliced, conversation
    )

    total_analyses = await session.scalar(
        select(func.count())
        .select_from(ProductResponseAnalysis)
        .where(ProductResponseAnalysis.audit_id == audit.id)
        .where(ProductResponseAnalysis.shopping_surface == surface)
    )
    # Response-level version label: the first catalog entry's selected
    # snapshot (deterministic catalog order). Row-level DTOs carry their own
    # version, so a mixed-version audit is still labelled correctly per row.
    selected_entry_ids = [entry.id for entry in config.products]
    selected_entry_ids.extend(entry.id for entry in config.competitor_products)
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
        total_mentions=sum(m["mention_count"] for m in sliced.values()),
        total_analyses=int(total_analyses or 0),
        products=products,
        competitor_products=competitor_products,
        available_surfaces=await _available_surfaces(session, audit_id=audit.id),
        created_at=max(s.created_at for s in selected),
    )


def _snapshot_entry_id(snapshot: ProductMetricSnapshot) -> str:
    """Frozen catalog entry id for a snapshot.

    The live FK is SET NULL when the catalog row is deleted, so fall back to
    the frozen ``entry_id`` persisted in ``metrics`` at finalize time.
    """
    live = snapshot.product_id or snapshot.competitor_product_id
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
            has_snapshots,
        )
        .order_by(Audit.completed_at.desc().nullslast(), Audit.created_at.desc())
        .limit(1)
    )
