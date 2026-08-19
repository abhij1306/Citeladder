# Product-analysis persistence + finalize wiring (invariants 4/7/9).
#
# Sibling of ``analysis/service.py`` (brand level): the deterministic product
# analyzer pass runs over the same persisted ``RawResponseArtifact`` rows and
# writes sibling derived rows (``ProductResponseAnalysis`` / ``ProductMention``
# / ``ProductMetricSnapshot``) — it NEVER touches the brand-level
# ``ResponseAnalysis`` / ``BrandMention`` / ... rows.
#   - ``analyze_task_products`` scores ONE completed execution from its frozen
#     catalog + persisted answer (no provider call) and persists the derived
#     rows with raw-artifact provenance + product analyzer versions.
#     Idempotent per task; a no-op when the frozen catalog is empty.
#   - ``finalize_audit_product_analysis`` upserts one ``ProductMetricSnapshot``
#     per (audit, product) / (audit, competitor_product) from the persisted
#     analyses only (invariant 7), stamping the exact evidence set.
from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.product_scoring import (
    ProductScoringConfig,
    aggregate_product_run,
    score_product_execution,
)
from app.core.config.audits import TASK_STATUS_SUCCEEDED
from app.core.config.products import (
    PRODUCT_ANALYZER_VERSION,
    PRODUCT_SCORING_RULE_VERSION,
)
from app.models.audit import Audit, AuditTask, RawResponseArtifact
from app.models.product import (
    CompetitorProduct,
    MerchantMention,
    Product,
    ProductMention,
    ProductMetricSnapshot,
    ProductResponseAnalysis,
)


async def _live_entry_ids(
    session: AsyncSession, config: ProductScoringConfig
) -> tuple[set[str], set[str]]:
    """Frozen catalog ids that STILL exist as live rows.

    The frozen catalog in ``Audit.configuration`` is immutable (invariant 9),
    so an id in it may point at a product deleted after the audit was created.
    Writing such an id into a FK column raises a foreign-key violation that
    rolls back the whole task-persistence transaction, so the FK is nulled for
    missing rows — the snapshotted identity (``matched_name``/``matched_sku``,
    ``metrics["entry_id"]``) keeps the evidence attributable either way.
    """

    def _as_uuids(raw_ids: list[str]) -> list[uuid.UUID]:
        parsed = []
        for raw in raw_ids:
            try:
                parsed.append(uuid.UUID(raw))
            except ValueError:
                continue
        return parsed

    product_ids = _as_uuids([entry.id for entry in config.products])
    competitor_ids = _as_uuids([entry.id for entry in config.competitor_products])
    live_products: set[str] = set()
    live_competitors: set[str] = set()
    if product_ids:
        live_products = {
            str(row)
            for row in (
                await session.scalars(
                    select(Product.id).where(Product.id.in_(product_ids))
                )
            ).all()
        }
    if competitor_ids:
        live_competitors = {
            str(row)
            for row in (
                await session.scalars(
                    select(CompetitorProduct.id).where(
                        CompetitorProduct.id.in_(competitor_ids)
                    )
                )
            ).all()
        }
    return live_products, live_competitors


async def _persist_product_signals(
    session: AsyncSession,
    *,
    task: AuditTask,
    analysis: ProductResponseAnalysis,
    config: ProductScoringConfig,
    score: dict,
) -> None:
    live_products, live_competitors = await _live_entry_ids(session, config)
    await _persist_signal_rows(
        session,
        task=task,
        analysis=analysis,
        signals=score["products"],
        names={entry.id: entry.name for entry in config.products},
        skus={entry.id: entry.sku for entry in config.products},
        live_ids=live_products,
        is_product=True,
    )
    await _persist_signal_rows(
        session,
        task=task,
        analysis=analysis,
        signals=score["competitor_products"],
        names={entry.id: entry.name for entry in config.competitor_products},
        skus={},
        live_ids=live_competitors,
        is_product=False,
    )


async def _persist_signal_rows(
    session: AsyncSession,
    *,
    task: AuditTask,
    analysis: ProductResponseAnalysis,
    signals: list[dict],
    names: dict[str, str],
    skus: dict[str, str],
    live_ids: set[str],
    is_product: bool,
) -> None:
    key = "product_id" if is_product else "competitor_product_id"
    for item in signals:
        if not item.get("mentioned"):
            continue
        entry_id = str(item[key])
        live_id = uuid.UUID(entry_id) if entry_id in live_ids else None
        session.add(
            _mention_row(
                task=task,
                analysis=analysis,
                signals=item,
                product_id=live_id if is_product else None,
                competitor_product_id=live_id if not is_product else None,
                matched_name=names.get(entry_id, ""),
                matched_sku=skus.get(entry_id, ""),
            )
        )
        for row in _merchant_rows(
            task=task,
            analysis=analysis,
            signals=item,
            product_id=live_id if is_product else None,
            competitor_product_id=live_id if not is_product else None,
        ):
            session.add(row)


def build_product_scoring_config(configuration: dict | None) -> ProductScoringConfig:
    """Build the product scorer config from the audit's FROZEN catalog.

    The planner froze the catalog into ``configuration`` at creation (via
    ``project_product_identity``); scoring reads that frozen copy, never the
    live catalog (determinism, invariant 9).
    """
    return ProductScoringConfig.from_project(configuration or {})


async def analyze_task_products(
    session: AsyncSession,
    *,
    task: AuditTask,
    config: ProductScoringConfig,
) -> ProductResponseAnalysis | None:
    """Score one completed execution's product signals and persist them.

    Deterministic + idempotent per (task, current analyzer/rule version
    pair): an existing CURRENT-version analysis for this task is returned
    unchanged, while a persisted v1 row never blocks a v2 re-score (D1). A
    task with no answer text still yields an analysis row (all-false
    signals) so provenance is complete. No-op (returns None) when the
    frozen catalog is empty. Caller owns the commit.
    """
    existing = await session.scalar(
        select(ProductResponseAnalysis).where(
            ProductResponseAnalysis.task_id == task.id,
            ProductResponseAnalysis.product_analyzer_version
            == PRODUCT_ANALYZER_VERSION,
            ProductResponseAnalysis.product_scoring_rule_version
            == PRODUCT_SCORING_RULE_VERSION,
        )
    )
    if existing is not None:
        return existing
    if not config.products and not config.competitor_products:
        return None

    # Score the PERSISTED artifact text (invariant 7); ``task.answer_text``
    # is only the fallback for legacy fixture rows with no artifact.
    answer_text = task.answer_text or ""
    if task.result_artifact_id is not None:
        artifact = await session.get(RawResponseArtifact, task.result_artifact_id)
        if artifact is not None:
            answer_text = artifact.answer_text or ""

    score = score_product_execution(answer_text=answer_text, config=config)
    analysis = ProductResponseAnalysis(
        workspace_id=task.workspace_id,
        audit_id=task.audit_id,
        task_id=task.id,
        artifact_id=task.result_artifact_id,
        product_analyzer_version=PRODUCT_ANALYZER_VERSION,
        product_scoring_rule_version=PRODUCT_SCORING_RULE_VERSION,
        logical_engine=task.logical_engine,
        transport_provider=task.transport_provider,
        transport_model=task.transport_model,
        prompt_index=task.prompt_index,
        repetition=task.repetition,
        shopping_surface=task.shopping_surface,
        own_product_mention_count=score["own_product_mention_count"],
        competitor_product_mention_count=score["competitor_product_mention_count"],
        products_with_price_match=score["products_with_price_match"],
        score=score,
    )
    session.add(analysis)
    await session.flush()  # assign analysis.id for child rows

    await _persist_product_signals(
        session, task=task, analysis=analysis, config=config, score=score
    )
    return analysis


def _mention_row(
    *,
    task: AuditTask,
    analysis: ProductResponseAnalysis,
    signals: dict,
    product_id: uuid.UUID | None,
    competitor_product_id: uuid.UUID | None,
    matched_name: str,
    matched_sku: str,
) -> ProductMention:
    return ProductMention(
        workspace_id=task.workspace_id,
        audit_id=task.audit_id,
        analysis_id=analysis.id,
        artifact_id=task.result_artifact_id,
        product_analyzer_version=PRODUCT_ANALYZER_VERSION,
        product_id=product_id,
        competitor_product_id=competitor_product_id,
        matched_name=matched_name,
        matched_sku=matched_sku,
        first_offset=signals.get("first_offset"),
        rank_position=signals.get("rank_position"),
        price_text=str(signals.get("price_text") or "")[:64],
        price_value=signals.get("price_value"),
        price_currency=str(signals.get("price_currency") or "")[:3],
        price_matches_catalog=signals.get("price_matches_catalog"),
        price_relation=signals.get("price_relation"),
        # Persist only the pinned {dimension, group, text, offset} shape.
        attribute_mentions=[
            {
                "dimension": str(item.get("dimension") or ""),
                "group": str(item.get("group") or ""),
                "text": str(item.get("text") or ""),
                "offset": item.get("offset"),
            }
            for item in signals.get("attribute_mentions") or []
        ],
    )


def _merchant_rows(
    *,
    task: AuditTask,
    analysis: ProductResponseAnalysis,
    signals: dict,
    product_id: uuid.UUID | None,
    competitor_product_id: uuid.UUID | None,
) -> list[MerchantMention]:
    """One ``MerchantMention`` per sanitized destination in the signal.

    Same analysis/artifact/version provenance and the same nullable live
    catalog FK behavior as ``ProductMention`` (exactly one target FK set).
    """
    rows: list[MerchantMention] = []
    for destination in signals.get("merchant_mentions") or []:
        rows.append(
            MerchantMention(
                workspace_id=task.workspace_id,
                audit_id=task.audit_id,
                analysis_id=analysis.id,
                artifact_id=task.result_artifact_id,
                product_id=product_id,
                competitor_product_id=competitor_product_id,
                merchant_name=str(destination.get("merchant_name") or "")[:255],
                merchant_domain=str(destination.get("merchant_domain") or "")[:255],
                merchant_kind=str(destination.get("merchant_kind") or "")[:16],
                destination_url=str(destination.get("destination_url") or ""),
                price_text=str(destination.get("price_text") or "")[:64],
                price_value=destination.get("price_value"),
                price_currency=str(destination.get("price_currency") or "")[:3],
                product_analyzer_version=PRODUCT_ANALYZER_VERSION,
            )
        )
    return rows


def _is_current_version(analysis: ProductResponseAnalysis) -> bool:
    return (
        analysis.product_analyzer_version == PRODUCT_ANALYZER_VERSION
        and analysis.product_scoring_rule_version == PRODUCT_SCORING_RULE_VERSION
    )


def _select_aggregate_analyses(
    analyses: list[ProductResponseAnalysis],
) -> list[ProductResponseAnalysis]:
    """Select ONE persisted analysis per task for the v2 aggregate.

    Mixed-version input rule: prefer the exact current analyzer/rule pair;
    otherwise fall back to the task's legacy (v1) row. All rows are
    PRESERVED — this only chooses the aggregation input.
    """
    by_task: dict[uuid.UUID, list[ProductResponseAnalysis]] = {}
    for analysis in analyses:
        by_task.setdefault(analysis.task_id, []).append(analysis)
    selected: list[ProductResponseAnalysis] = []
    for task_analyses in by_task.values():
        current = [
            analysis for analysis in task_analyses if _is_current_version(analysis)
        ]
        if current:
            selected.append(current[0])
        else:
            selected.append(
                sorted(
                    task_analyses,
                    key=lambda analysis: (analysis.created_at, str(analysis.id)),
                )[0]
            )
    return selected


def _aggregate_by(
    analyses: list[ProductResponseAnalysis],
    config: ProductScoringConfig,
    *,
    surface: str | None = None,
) -> dict[str, dict[str, dict]]:
    """Group persisted analyses by engine (within ``surface`` when given)."""
    scoped = [
        analysis
        for analysis in analyses
        if surface is None or analysis.shopping_surface == surface
    ]
    grouped: dict[str, dict[str, dict]] = {}
    for engine in sorted({analysis.logical_engine for analysis in scoped}):
        grouped[engine] = aggregate_product_run(
            [
                analysis.score or {}
                for analysis in scoped
                if analysis.logical_engine == engine
            ],
            config,
        )
    return grouped


async def _product_finalize_inputs(
    session: AsyncSession,
    *,
    audit: Audit,
    config: ProductScoringConfig,
) -> tuple[
    list[ProductResponseAnalysis],
    dict[str, dict],
    dict[str, dict[str, dict]],
    dict[str, dict[str, dict]],
    dict[str, dict[str, dict[str, dict]]],
]:
    succeeded_tasks = list(
        (
            await session.scalars(
                select(AuditTask)
                .where(AuditTask.audit_id == audit.id)
                .where(AuditTask.status == TASK_STATUS_SUCCEEDED)
            )
        ).all()
    )
    for task in succeeded_tasks:
        await analyze_task_products(session, task=task, config=config)
    await session.flush()
    analyses = _select_aggregate_analyses(
        list(
            (
                await session.scalars(
                    select(ProductResponseAnalysis).where(
                        ProductResponseAnalysis.audit_id == audit.id
                    )
                )
            ).all()
        )
    )
    aggregates = aggregate_product_run(
        [analysis.score or {} for analysis in analyses], config
    )
    per_engine = _aggregate_by(analyses, config)
    surfaces = sorted({analysis.shopping_surface for analysis in analyses})
    per_surface = {
        surface: aggregate_product_run(
            [
                analysis.score or {}
                for analysis in analyses
                if analysis.shopping_surface == surface
            ],
            config,
        )
        for surface in surfaces
    }
    per_surface_engine = {
        surface: _aggregate_by(analyses, config, surface=surface)
        for surface in surfaces
    }
    return analyses, aggregates, per_engine, per_surface, per_surface_engine


async def _persist_product_snapshots(
    session: AsyncSession,
    *,
    audit: Audit,
    analyses: list[ProductResponseAnalysis],
    aggregates: dict[str, dict],
    per_engine: dict[str, dict[str, dict]],
    per_surface: dict[str, dict[str, dict]],
    per_surface_engine: dict[str, dict[str, dict[str, dict]]],
    existing_snapshots: list[ProductMetricSnapshot],
    config: ProductScoringConfig,
) -> list[ProductMetricSnapshot]:
    by_entry = {
        str(
            (snapshot.metrics or {}).get("entry_id")
            or snapshot.product_id
            or snapshot.competitor_product_id
        ): snapshot
        for snapshot in existing_snapshots
        if snapshot.product_analyzer_version == PRODUCT_ANALYZER_VERSION
        and snapshot.product_scoring_rule_version == PRODUCT_SCORING_RULE_VERSION
    }
    live_products, live_competitors = await _live_entry_ids(session, config)
    snapshots: list[ProductMetricSnapshot] = []
    for entry_id, aggregate in aggregates.items():
        snapshots.append(
            _upsert_product_snapshot(
                session,
                audit=audit,
                entry_id=entry_id,
                aggregate=aggregate,
                analyses=analyses,
                existing=by_entry.get(entry_id),
                live_ids=(
                    live_products
                    if aggregate["kind"] == "product"
                    else live_competitors
                ),
                per_engine=per_engine,
                per_surface=per_surface,
                per_surface_engine=per_surface_engine,
            )
        )
    return snapshots


def _upsert_product_snapshot(
    session: AsyncSession,
    *,
    audit: Audit,
    entry_id: str,
    aggregate: dict,
    analyses: list[ProductResponseAnalysis],
    existing: ProductMetricSnapshot | None,
    live_ids: set[str],
    per_engine: dict[str, dict[str, dict]],
    per_surface: dict[str, dict[str, dict]],
    per_surface_engine: dict[str, dict[str, dict[str, dict]]],
) -> ProductMetricSnapshot:
    is_product = aggregate["kind"] == "product"
    evidence = [
        analysis
        for analysis in analyses
        if _mentions_entry(analysis.score or {}, entry_id, is_product)
    ]
    snapshot = existing or ProductMetricSnapshot(
        workspace_id=audit.workspace_id,
        audit_id=audit.id,
        project_id=audit.project_id,
    )
    if existing is None:
        session.add(snapshot)
    _apply_snapshot_fields(
        snapshot,
        entry_id=entry_id,
        aggregate=aggregate,
        is_product=is_product,
        is_live=entry_id in live_ids,
        evidence=evidence,
        per_engine=per_engine,
        per_surface=per_surface,
        per_surface_engine=per_surface_engine,
    )
    return snapshot


async def finalize_audit_product_analysis(
    session: AsyncSession, *, audit: Audit
) -> list[ProductMetricSnapshot]:
    """Upsert the per-(audit, entry) ``ProductMetricSnapshot`` rows.

    Defensively ensures every succeeded task has a CURRENT-version product
    analysis (mirror ``finalize_audit_analysis``; the succeeded-task query
    is deliberately unfiltered by surface — product analysis covers
    measurement and future probe rows), then aggregates from the SELECTED
    persisted analyses only (invariant 7): overall, per-engine, and
    per-surface (with nested per-engine) breakdowns. Only the
    current-version snapshot keyed by (entry_id, analyzer/rule version) is
    created/updated — a v1 snapshot is never mutated. Stamps the exact
    selected evidence set per snapshot (invariant 4). Idempotent. Caller
    owns the commit. Returns [] when the frozen catalog is empty (product
    analysis disabled for the audit).
    """
    config = build_product_scoring_config(audit.configuration)
    if not config.products and not config.competitor_products:
        return []

    (
        analyses,
        aggregates,
        per_engine,
        per_surface,
        per_surface_engine,
    ) = await _product_finalize_inputs(session, audit=audit, config=config)
    existing_snapshots = list(
        (
            await session.scalars(
                select(ProductMetricSnapshot).where(
                    ProductMetricSnapshot.audit_id == audit.id
                )
            )
        ).all()
    )
    return await _persist_product_snapshots(
        session,
        audit=audit,
        analyses=analyses,
        aggregates=aggregates,
        per_engine=per_engine,
        per_surface=per_surface,
        per_surface_engine=per_surface_engine,
        existing_snapshots=existing_snapshots,
        config=config,
    )


def _apply_snapshot_fields(
    snapshot: ProductMetricSnapshot,
    *,
    entry_id: str,
    aggregate: dict,
    is_product: bool,
    is_live: bool,
    evidence: list[ProductResponseAnalysis],
    per_engine: dict[str, dict[str, dict]],
    per_surface: dict[str, dict[str, dict]],
    per_surface_engine: dict[str, dict[str, dict[str, dict]]],
) -> None:
    """Write the aggregate onto a (new or existing) snapshot row."""
    # Same live-row guard as the mention rows: never write a FK pointing at a
    # catalog entry deleted after the audit was created.
    live_id = uuid.UUID(entry_id) if is_live else None
    snapshot.product_id = live_id if is_product else None
    snapshot.competitor_product_id = None if is_product else live_id
    snapshot.product_analyzer_version = PRODUCT_ANALYZER_VERSION
    snapshot.product_scoring_rule_version = PRODUCT_SCORING_RULE_VERSION
    snapshot.mention_count = int(aggregate["mention_count"])
    snapshot.sov_share = float(aggregate["sov_share"])
    snapshot.avg_rank = aggregate["avg_rank"]
    snapshot.rank_distribution = aggregate["rank_distribution"]
    snapshot.price_mention_count = int(aggregate["price_mention_count"])
    snapshot.price_accuracy_rate = aggregate["price_accuracy_rate"]
    snapshot.win_rate = aggregate["win_rate"]
    snapshot.price_mismatch_rate = aggregate["price_mismatch_rate"]
    snapshot.metrics = {
        # Frozen entry id: survives the SET NULL a catalog delete triggers on
        # the live FKs, so projections can still key the snapshot.
        "entry_id": entry_id,
        **aggregate,
        "per_engine": {
            engine: engine_aggregates.get(entry_id)
            for engine, engine_aggregates in per_engine.items()
        },
        # per_surface[surface]: the same aggregate shape plus a nested
        # per-engine slice (no extra snapshot row per surface).
        "per_surface": {
            surface: {
                **(surface_aggregates.get(entry_id) or {}),
                "per_engine": {
                    engine: engine_aggregates.get(entry_id)
                    for engine, engine_aggregates in per_surface_engine.get(
                        surface, {}
                    ).items()
                },
            }
            for surface, surface_aggregates in per_surface.items()
        },
    }
    snapshot.source_analysis_ids = [str(a.id) for a in evidence]
    snapshot.source_artifact_ids = [
        str(a.artifact_id) for a in evidence if a.artifact_id is not None
    ]


def _mentions_entry(score: dict, entry_id: str, is_product: bool) -> bool:
    section = "products" if is_product else "competitor_products"
    key = "product_id" if is_product else "competitor_product_id"
    return any(
        str(signals.get(key) or "") == entry_id and signals.get("mentioned")
        for signals in score.get(section) or []
    )
