"""Product analyzer pass: persisted-artifact re-score + snapshots (M2a).

There are no usable LLM provider credentials in this sandbox, so M2a scoring
verification NEVER drains a live audit or depends on ``build_adapter``:
planner-frozen audit/task rows are seeded directly (``create_audit`` makes no
provider calls), fixture answer text is persisted as immutable
``RawResponseArtifact`` rows, and the deterministic re-scoring path
(``analyze_task_products`` / ``finalize_audit_product_analysis``) is invoked
exactly like the worker invokes it on persist/finalize.

  - every succeeded task yields a CURRENT-version ``ProductResponseAnalysis``
    + one ``ProductMention`` per mentioned catalog entry, stamped with the
    exact v2 provenance literals (deliberate version lock, not config
    constants) and the v2 signal set (``price_relation``,
    ``attribute_mentions``, ``mentioned_entry_ids``);
  - scoring reads the PERSISTED artifact text, never the task's mutable copy;
  - finalize upserts one current-version ``ProductMetricSnapshot`` per entry
    with the v2 scalars + structured aggregates and stays idempotent;
  - a persisted v1 analysis/mention/snapshot is NEVER mutated by the v2
    re-score/finalize: v1 ids survive unchanged and v2 rows are added
    alongside (D1), with aggregation selecting only the current version;
  - an empty frozen catalog writes nothing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.product_service import (
    analyze_task_products,
    build_product_scoring_config,
    finalize_audit_product_analysis,
)
from app.core.config.audits import AUDIT_TRIGGER_MANUAL
from app.core.config.provider_catalog import ENGINE_GEMINI, TRANSPORT_GOOGLE
from app.core.config.task_queue import TASK_STATUS_SUCCEEDED
from app.domain.audits.creation import create_audit
from app.models.audit import Audit, AuditTask, RawResponseArtifact
from app.models.brand import Competitor
from app.models.product import (
    CompetitorProduct,
    MerchantMention,
    Product,
    ProductMention,
    ProductMetricSnapshot,
    ProductResponseAnalysis,
)
from tests.component.audit_helpers import seed_audit_fixtures

# Deliberate version lock: these literals must not drift with config edits.
_V2_ANALYZER = "product-analysis-2"
_V2_SCORING_RULE = "product-scoring-v2"
_V1_ANALYZER = "product-analysis-1"
_V1_SCORING_RULE = "product-scoring-v1"

_ANSWER = (
    "1. Acme VoltBike 500 — the best commuter pick at $2,499.00\n"
    "2. Globex CityBike 450 — a solid alternative at $2,399.00\n"
    "3. Something generic with no catalog entry"
)


async def _seed_with_catalog(session: AsyncSession, *, prompts: int = 2):
    seed = await seed_audit_fixtures(session, prompt_count=prompts)
    product = Product(
        project_id=seed.project_id,
        sku="AC-VB500",
        name="Acme VoltBike 500",
        aliases=["VoltBike"],
        price=Decimal("2499.00"),
        currency="USD",
        url="https://acme.com/p/voltbike",
    )
    session.add(product)
    competitor = await session.scalar(
        select(Competitor).where(Competitor.project_id == seed.project_id)
    )
    assert competitor is not None
    competitor_product = CompetitorProduct(
        project_id=seed.project_id,
        competitor_id=competitor.id,
        name="Globex CityBike 450",
        price=Decimal("2399.00"),
        currency="USD",
    )
    session.add(competitor_product)
    await session.commit()
    return seed, product, competitor_product


async def _plan_audit(
    session_factory: async_sessionmaker[AsyncSession], seed, *, reps: int = 1
) -> Audit:
    """Freeze the catalog + task slots through the planner (no provider)."""
    async with session_factory() as session:
        return await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            prompt_set_id=seed.prompt_set_id,
            repetitions=reps,
            random_seed="1",
        )


async def _persist_fixture_artifacts(
    session_factory: async_sessionmaker[AsyncSession],
    audit_id,
    *,
    answer_text: str = _ANSWER,
) -> list:
    """Persist one immutable artifact per task and mark each succeeded.

    ``task.answer_text`` stays EMPTY on purpose: scoring must read the
    persisted artifact text (invariant 7), never the task's mutable copy.
    """
    async with session_factory() as session:
        tasks = list(
            (
                await session.scalars(
                    select(AuditTask)
                    .where(AuditTask.audit_id == audit_id)
                    .order_by(AuditTask.prompt_index)
                )
            ).all()
        )
        for task in tasks:
            artifact = RawResponseArtifact(
                audit_id=task.audit_id,
                task_id=task.id,
                logical_engine=task.logical_engine,
                transport_provider=task.transport_provider,
                transport_model=task.transport_model,
                answer_text=answer_text,
                search_used=True,
                search_events=[],
                citations=[],
            )
            session.add(artifact)
            await session.flush()
            task.result_artifact_id = artifact.id
            task.status = TASK_STATUS_SUCCEEDED
            task.completed_at = datetime.now(UTC)
        await session.commit()
        return [task.id for task in tasks]


async def _rescore_and_finalize(
    session_factory: async_sessionmaker[AsyncSession], audit_id
):
    """Run the deterministic re-score + finalize exactly like the worker."""
    async with session_factory() as session:
        audit = await session.get(Audit, audit_id)
        assert audit is not None
        config = build_product_scoring_config(audit.configuration)
        tasks = list(
            (
                await session.scalars(
                    select(AuditTask).where(AuditTask.audit_id == audit_id)
                )
            ).all()
        )
        analyses = []
        for task in tasks:
            analysis = await analyze_task_products(session, task=task, config=config)
            if analysis is not None:
                analyses.append(analysis)
        snapshots = await finalize_audit_product_analysis(session, audit=audit)
        await session.commit()
        return audit, analyses, snapshots


@pytest.mark.asyncio
async def test_persisted_artifacts_rescore_to_v2_rows_and_snapshots(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed, product, competitor_product = await _seed_with_catalog(session, prompts=2)
    audit = await _plan_audit(session_factory, seed, reps=1)  # 2 tasks
    await _persist_fixture_artifacts(session_factory, audit.id)
    _audit, analyses, snapshots = await _rescore_and_finalize(session_factory, audit.id)

    async with session_factory() as session:
        # One current-version ProductResponseAnalysis per execution (inv 4).
        assert len(analyses) == 2
        # Identical persisted text -> byte-identical score dicts.
        assert analyses[0].score == analyses[1].score
        task_artifacts = {
            row.id: row.result_artifact_id
            for row in (
                await session.scalars(
                    select(AuditTask).where(AuditTask.audit_id == audit.id)
                )
            ).all()
        }
        for analysis in analyses:
            assert analysis.artifact_id == task_artifacts[analysis.task_id]
            assert analysis.product_analyzer_version == _V2_ANALYZER
            assert analysis.product_scoring_rule_version == _V2_SCORING_RULE
            assert analysis.logical_engine == ENGINE_GEMINI
            assert analysis.transport_provider == TRANSPORT_GOOGLE
            assert analysis.shopping_surface == ""
            assert analysis.own_product_mention_count == 1
            assert analysis.competitor_product_mention_count == 1
            assert analysis.products_with_price_match == 2
            # v2 execution signals: mentioned ids (own first, then
            # competitor) + per-entry price direction.
            assert analysis.score["mentioned_entry_ids"] == [
                str(product.id),
                str(competitor_product.id),
            ]
            own_signals = analysis.score["products"][0]
            assert own_signals["mentioned"] is True
            assert own_signals["price_relation"] == "match"
            assert own_signals["attribute_mentions"] == []

        # One ProductMention per mentioned entry per execution, v2 fields.
        mentions = list(
            (
                await session.scalars(
                    select(ProductMention).where(ProductMention.audit_id == audit.id)
                )
            ).all()
        )
        assert len(mentions) == 4
        own = [m for m in mentions if m.product_id == product.id]
        competitor = [
            m for m in mentions if m.competitor_product_id == competitor_product.id
        ]
        assert len(own) == 2
        assert len(competitor) == 2
        for mention in own:
            assert mention.matched_name == "Acme VoltBike 500"
            assert mention.matched_sku == "AC-VB500"
            assert mention.rank_position == 1
            assert mention.price_value == Decimal("2499.00")
            assert mention.price_currency == "USD"
            assert mention.price_matches_catalog is True
            # $2,499.00 equals the catalog price -> exact v2 direction.
            assert mention.price_relation == "match"
            assert mention.attribute_mentions == []
            assert mention.artifact_id is not None
            assert mention.product_analyzer_version == _V2_ANALYZER
            assert mention.workspace_id == seed.workspace_id
        for mention in competitor:
            assert mention.rank_position == 2
            assert mention.price_relation == "match"
            assert mention.product_analyzer_version == _V2_ANALYZER

        # The fixture answer has no URLs -> no buyer-destination rows.
        assert (
            await session.scalar(
                select(func.count())
                .select_from(MerchantMention)
                .where(MerchantMention.audit_id == audit.id)
            )
        ) == 0

        # One current-version ProductMetricSnapshot per catalog entry.
        assert len(snapshots) == 2
        own_snapshot = next(s for s in snapshots if s.product_id == product.id)
        competitor_snapshot = next(
            s for s in snapshots if s.competitor_product_id == competitor_product.id
        )
        assert own_snapshot.product_analyzer_version == _V2_ANALYZER
        assert own_snapshot.product_scoring_rule_version == _V2_SCORING_RULE
        assert own_snapshot.mention_count == 2
        assert own_snapshot.sov_share == 0.5
        assert own_snapshot.avg_rank == 1.0
        assert own_snapshot.rank_distribution["top_1"] == 2
        assert own_snapshot.price_mention_count == 2
        assert own_snapshot.price_accuracy_rate == 1.0
        # v2 scalars + structured aggregates.
        assert own_snapshot.win_rate == 1.0
        assert own_snapshot.price_mismatch_rate == 0.0
        metrics = own_snapshot.metrics
        assert metrics["entry_id"] == str(product.id)
        assert metrics["price_relation_counts"] == {
            "match": 2,
            "higher": 0,
            "lower": 0,
            "mismatch": 0,
        }
        assert metrics["attribute_dimension_frequency"] == {}
        assert metrics["buyer_destination_mix"] == {
            "total": 0,
            "by_kind": [],
            "by_domain": [],
        }
        co_placement = metrics["competitor_co_placement"]
        assert co_placement["truncated"] is False
        assert co_placement["items"] == [
            {
                "competitor_product_id": str(competitor_product.id),
                "competitor_name": "Globex",
                "product_name": "Globex CityBike 450",
                "count": 2,
            }
        ]
        # Per-engine + per-surface breakdowns (measurement-only gate).
        assert metrics["per_engine"][ENGINE_GEMINI]["mention_count"] == 2
        assert set(metrics["per_surface"].keys()) == {""}
        assert metrics["per_surface"][""]["mention_count"] == 2
        assert (
            metrics["per_surface"][""]["per_engine"][ENGINE_GEMINI]["mention_count"]
            == 2
        )
        assert len(own_snapshot.source_analysis_ids) == 2
        assert len(own_snapshot.source_artifact_ids) == 2
        assert competitor_snapshot.avg_rank == 2.0
        assert competitor_snapshot.sov_share == 0.5
        assert competitor_snapshot.win_rate == 0.0
        assert competitor_snapshot.price_mismatch_rate == 0.0

        # Finalize is idempotent: re-running reuses the same snapshot rows
        # and never duplicates analyses/mentions.
        snapshot_ids = {s.id for s in snapshots}
        refreshed = await session.get(Audit, audit.id)
        assert refreshed is not None
        again = await finalize_audit_product_analysis(session, audit=refreshed)
        await session.commit()
        assert {s.id for s in again} == snapshot_ids
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProductResponseAnalysis)
                .where(ProductResponseAnalysis.audit_id == audit.id)
            )
        ) == 2
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProductMention)
                .where(ProductMention.audit_id == audit.id)
            )
        ) == 4
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProductMetricSnapshot)
                .where(ProductMetricSnapshot.audit_id == audit.id)
            )
        ) == 2


@pytest.mark.asyncio
async def test_v1_rows_survive_v2_rescore_and_finalize(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """D1: a persisted v1 analysis/mention/snapshot is immutable history.

    Re-scoring the same task adds v2 rows ALONGSIDE the v1 rows; finalize
    creates a NEW v2 snapshot keyed on the current versions and never
    mutates the v1 snapshot; aggregation selects only the current version.
    """
    async with session_factory() as session:
        seed, product, _competitor_product = await _seed_with_catalog(
            session, prompts=1
        )
    audit = await _plan_audit(session_factory, seed, reps=1)  # 1 task
    task_ids = await _persist_fixture_artifacts(session_factory, audit.id)
    assert len(task_ids) == 1

    # Seed the v1 graph exactly as a pre-bump run persisted it.
    async with session_factory() as session:
        task = await session.get(AuditTask, task_ids[0])
        assert task is not None
        v1_analysis = ProductResponseAnalysis(
            workspace_id=seed.workspace_id,
            audit_id=audit.id,
            task_id=task.id,
            artifact_id=task.result_artifact_id,
            product_analyzer_version=_V1_ANALYZER,
            product_scoring_rule_version=_V1_SCORING_RULE,
            logical_engine=task.logical_engine,
            transport_provider=task.transport_provider,
            transport_model=task.transport_model,
            prompt_index=task.prompt_index,
            repetition=task.repetition,
            shopping_surface="",
            own_product_mention_count=1,
            competitor_product_mention_count=1,
            products_with_price_match=2,
            # v1 score shape: no mentioned_entry_ids / price_relation keys.
            score={
                "products": [],
                "competitor_products": [],
                "own_product_mention_count": 1,
                "competitor_product_mention_count": 1,
                "products_with_price_match": 2,
            },
        )
        session.add(v1_analysis)
        await session.flush()
        v1_mention = ProductMention(
            workspace_id=seed.workspace_id,
            audit_id=audit.id,
            analysis_id=v1_analysis.id,
            artifact_id=task.result_artifact_id,
            product_analyzer_version=_V1_ANALYZER,
            product_id=product.id,
            matched_name="Acme VoltBike 500",
            matched_sku="AC-VB500",
            first_offset=3,
            rank_position=1,
            price_text="$2,499.00",
            price_value=Decimal("2499.00"),
            price_currency="USD",
            price_matches_catalog=True,
            # price_relation / attribute_mentions predate the v1 columns.
        )
        session.add(v1_mention)
        v1_snapshot = ProductMetricSnapshot(
            workspace_id=seed.workspace_id,
            audit_id=audit.id,
            project_id=seed.project_id,
            product_id=product.id,
            product_analyzer_version=_V1_ANALYZER,
            product_scoring_rule_version=_V1_SCORING_RULE,
            mention_count=1,
            sov_share=0.5,
            avg_rank=1.0,
            rank_distribution={"top_1": 1, "top_3": 1, "top_10": 1, "unranked": 0},
            price_mention_count=1,
            price_accuracy_rate=1.0,
            metrics={"entry_id": str(product.id), "mention_count": 1},
            source_analysis_ids=[str(v1_analysis.id)],
            source_artifact_ids=[str(task.result_artifact_id)],
        )
        session.add(v1_snapshot)
        await session.commit()
        v1_analysis_id = v1_analysis.id
        v1_mention_id = v1_mention.id
        v1_snapshot_id = v1_snapshot.id
        v1_snapshot_metrics = dict(v1_snapshot.metrics or {})

    _audit, analyses, snapshots = await _rescore_and_finalize(session_factory, audit.id)

    async with session_factory() as session:
        # The re-score ADDED a v2 analysis; the v1 row is untouched (D1).
        assert len(analyses) == 1
        v2_analysis = analyses[0]
        assert v2_analysis.id != v1_analysis_id
        assert v2_analysis.product_analyzer_version == _V2_ANALYZER
        assert v2_analysis.product_scoring_rule_version == _V2_SCORING_RULE
        v1_row = await session.get(ProductResponseAnalysis, v1_analysis_id)
        assert v1_row is not None
        assert v1_row.product_analyzer_version == _V1_ANALYZER
        assert v1_row.product_scoring_rule_version == _V1_SCORING_RULE
        assert v1_row.score == {
            "products": [],
            "competitor_products": [],
            "own_product_mention_count": 1,
            "competitor_product_mention_count": 1,
            "products_with_price_match": 2,
        }
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProductResponseAnalysis)
                .where(ProductResponseAnalysis.task_id == task_ids[0])
            )
        ) == 2

        # The v1 mention row survives with its legacy (null) v2 fields.
        v1_mention_row = await session.get(ProductMention, v1_mention_id)
        assert v1_mention_row is not None
        assert v1_mention_row.product_analyzer_version == _V1_ANALYZER
        assert v1_mention_row.price_relation is None
        # The v2 mention is a NEW row carrying the v2 direction.
        v2_mentions = list(
            (
                await session.scalars(
                    select(ProductMention).where(
                        ProductMention.analysis_id == v2_analysis.id,
                        ProductMention.product_id == product.id,
                    )
                )
            ).all()
        )
        assert len(v2_mentions) == 1
        assert v2_mentions[0].id != v1_mention_id
        assert v2_mentions[0].price_relation == "match"

        # Finalize created a NEW v2 snapshot; the v1 snapshot is untouched.
        v2_own = next(s for s in snapshots if s.product_id == product.id)
        assert v2_own.id != v1_snapshot_id
        assert v2_own.product_analyzer_version == _V2_ANALYZER
        # Aggregation selected ONLY the v2 analysis: a double-counted
        # v1 + v2 selection would read 2, not 1.
        assert v2_own.mention_count == 1
        assert v2_own.win_rate == 1.0
        assert v2_own.price_mismatch_rate == 0.0
        assert v2_own.source_analysis_ids == [str(v2_analysis.id)]

        v1_snapshot_row = await session.get(ProductMetricSnapshot, v1_snapshot_id)
        assert v1_snapshot_row is not None
        assert v1_snapshot_row.product_analyzer_version == _V1_ANALYZER
        assert v1_snapshot_row.metrics == v1_snapshot_metrics
        assert v1_snapshot_row.mention_count == 1
        assert v1_snapshot_row.win_rate is None
        assert v1_snapshot_row.price_mismatch_rate is None

        # Three snapshots total: v1 own + v2 own + v2 competitor.
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProductMetricSnapshot)
                .where(ProductMetricSnapshot.audit_id == audit.id)
            )
        ) == 3


@pytest.mark.asyncio
async def test_empty_catalog_writes_no_product_rows(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=2)
    audit = await _plan_audit(session_factory, seed, reps=1)
    await _persist_fixture_artifacts(session_factory, audit.id)
    _audit, analyses, snapshots = await _rescore_and_finalize(session_factory, audit.id)

    assert analyses == []
    assert snapshots == []
    async with session_factory() as session:
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProductResponseAnalysis)
                .where(ProductResponseAnalysis.audit_id == audit.id)
            )
        ) == 0
        assert (
            await session.scalar(
                select(func.count())
                .select_from(ProductMetricSnapshot)
                .where(ProductMetricSnapshot.audit_id == audit.id)
            )
        ) == 0
