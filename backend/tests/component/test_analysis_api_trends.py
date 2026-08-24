"""Cross-run visibility trend projection scenarios.

Seeds a workspace/project + audit through the ORM, runs the real worker (with a
MOCKED adapter — no network) so the analysis stage produces persisted rows +
one MetricSnapshot, then exercises the projection service + exports directly:

  - metrics + visibility + execution-evidence are PROJECTIONS: they read only
    persisted analysis and never call a provider (invariant 7 — asserted by
    patching ``build_adapter`` to raise before the projection calls);
  - derived rows carry provenance (``analyzer_version``) (invariant 4);
  - citation classification labels are persisted (owned/competitor/...);
  - CSV + Markdown exports render from persisted rows;
  - projections are workspace-scoped (a foreign workspace gets nothing).
"""

from __future__ import annotations

import uuid as _uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.audits import (
    AUDIT_STATUS_PARTIALLY_COMPLETED,
)
from app.core.config.provider_catalog import (
    ENGINE_CHATGPT,
    ENGINE_GEMINI,
    measurement_route,
)
from app.domain.analysis import trend_folding as analysis_trend_folding
from app.domain.analysis.errors import TrendQueryError
from app.domain.analysis.trends import get_visibility_trends
from app.workers.audit import execution as audit_execution
from tests.component.analysis_api_helpers import (
    _BRAND,
    _COMPETITOR,
    _PARTITION_IDENTITIES,
    _identity_of,
    _seed_partition_audits,
    _seed_snapshot,
    _trend_metrics,
)
from tests.component.audit_helpers import Seed, seed_audit_fixtures

# The model the PLANNER freezes for these audits. Read from the catalog rather
# than pinned as a literal: these assertions are about provenance travelling
# intact from the frozen route to the projection, not about which Gemini build
# is current, and a literal here goes stale on every model-version bump.
GEMINI_MODEL = measurement_route(ENGINE_GEMINI).transport_model


async def _seed_reference_snapshot(session: AsyncSession) -> Seed:
    seed = await seed_audit_fixtures(session, prompt_count=1)
    await _seed_snapshot(
        session,
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        completed_at=datetime(2026, 1, 5, tzinfo=UTC),
        metrics=_trend_metrics(
            brand_rate=1.0,
            owned_rate=0.5,
            competitor_rate=0.5,
            brand_count=4,
            competitor_count=2,
            total_completed=4,
        ),
        visibility_score=100.0,
        total_completed=4,
    )
    await session.commit()
    return seed


async def test_trends_raw_points_chronological_with_provenance(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The projection must never touch a provider (invariant 7).
    def _boom(**_: object):
        raise AssertionError("trend projection must not call a provider")

    monkeypatch.setattr(audit_execution, "build_adapter", _boom)

    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        # Seed out of order to prove the endpoint sorts chronologically.
        _, snap_late = await _seed_snapshot(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 3, 10, tzinfo=UTC),
            metrics=_trend_metrics(
                brand_rate=0.5,
                owned_rate=0.25,
                competitor_rate=1.0,
                brand_count=2,
                competitor_count=4,
                total_completed=4,
            ),
            visibility_score=50.0,
            total_completed=4,
        )
        # A partially-completed audit must still be included (eligibility rule).
        _, snap_early = await _seed_snapshot(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 1, 5, tzinfo=UTC),
            metrics=_trend_metrics(
                brand_rate=1.0,
                owned_rate=0.5,
                competitor_rate=0.5,
                brand_count=4,
                competitor_count=2,
                total_completed=4,
            ),
            visibility_score=100.0,
            total_completed=4,
            status=AUDIT_STATUS_PARTIALLY_COMPLETED,
        )
        await session.commit()

        points = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
    assert len(points) == 2
    # Chronological order (earliest first) despite insertion order.
    assert points[0].completed_at == datetime(2026, 1, 5, tzinfo=UTC)
    assert points[1].completed_at == datetime(2026, 3, 10, tzinfo=UTC)
    # Raw points carry the single snapshot as provenance + its versions.
    assert points[0].audit_id is not None
    assert points[0].source_snapshot_ids == [snap_early.id]
    assert points[0].analyzer_versions == ["b6-analysis-1"]
    assert points[0].scoring_rule_versions == ["scoring-v1"]
    assert points[0].spans_version_boundary is False
    assert points[0].logical_engine is None
    # Roadmap fields stay null (decision B-2 / invariant 9).
    assert points[0].sentiment is None
    assert points[0].avg_position is None
    assert all(
        r.sentiment is None and r.avg_position is None for r in points[0].rankings
    )
    # Headline values project the persisted snapshot exactly.
    assert points[0].visibility_score == 100.0
    assert points[0].brand_mention_rate == 1.0
    assert points[0].owned_citation_rate == 0.5
    _ = snap_late


@pytest.mark.asyncio
async def test_trends_response_and_mention_sov_and_rankings(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await _seed_reference_snapshot(session)
        points = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
    point = points[0]
    # Response-level SOV = brand_rate / (brand_rate + competitor_rate) = 1/1.5.
    assert point.sov.response == pytest.approx(round(1.0 / 1.5, 4))
    # Mention-level SOV = brand_count / total_mentions = 4/6.
    assert point.sov.mention == pytest.approx(round(4 / 6, 4))
    # Rankings: brand row first (highest SOV), competitor present.
    brand_rows = [r for r in point.rankings if r.is_brand]
    assert len(brand_rows) == 1
    assert brand_rows[0].name == _BRAND
    assert brand_rows[0].mention_count == 4
    competitor_rows = [r for r in point.rankings if not r.is_brand]
    assert competitor_rows[0].name == _COMPETITOR
    assert competitor_rows[0].mention_count == 2


@pytest.mark.asyncio
async def test_trends_date_and_engine_filtering(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    per_engine_gemini = {
        ENGINE_GEMINI: _trend_metrics(
            brand_rate=1.0,
            owned_rate=0.5,
            competitor_rate=0.5,
            brand_count=4,
            competitor_count=2,
            total_completed=4,
        )
    }
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        # In-window audit that measured gemini only.
        await _seed_snapshot(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 10, tzinfo=UTC),
            metrics=_trend_metrics(
                brand_rate=0.75,
                owned_rate=0.5,
                competitor_rate=0.5,
                brand_count=3,
                competitor_count=2,
                total_completed=4,
                per_engine=per_engine_gemini,
            ),
            visibility_score=75.0,
            total_completed=4,
        )
        # Out-of-window audit (before the from bound) — must be excluded.
        await _seed_snapshot(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2025, 12, 1, tzinfo=UTC),
            metrics=_trend_metrics(
                brand_rate=0.5,
                owned_rate=0.25,
                competitor_rate=1.0,
                brand_count=2,
                competitor_count=4,
                total_completed=4,
                per_engine=per_engine_gemini,
            ),
            visibility_score=50.0,
            total_completed=4,
        )
        await session.commit()

        # Date filter: only the Feb audit is in range.
        windowed = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            from_at=datetime(2026, 1, 1, tzinfo=UTC),
            to_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
        assert len(windowed) == 1
        assert windowed[0].completed_at == datetime(2026, 2, 10, tzinfo=UTC)

        # Engine filter: gemini slice is present on both; chatgpt slice missing
        # on every snapshot -> the engine-filtered series is empty.
        gemini = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            logical_engine=ENGINE_GEMINI,
        )
        assert len(gemini) == 2
        assert all(p.logical_engine == ENGINE_GEMINI for p in gemini)
        chatgpt = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            logical_engine=ENGINE_CHATGPT,
        )
        assert chatgpt == []


@pytest.mark.asyncio
async def test_trends_weekly_and_monthly_bucketing_math(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        # Two snapshots in the SAME ISO week (Mon 2026-01-05 .. Sun 2026-01-11).
        await _seed_snapshot(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 1, 5, 9, tzinfo=UTC),  # Monday
            metrics=_trend_metrics(
                brand_rate=1.0,
                owned_rate=0.5,
                competitor_rate=0.5,
                brand_count=4,
                competitor_count=2,
                total_completed=4,
            ),
            visibility_score=100.0,
            total_completed=4,
        )
        await _seed_snapshot(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 1, 7, 9, tzinfo=UTC),  # Wednesday
            metrics=_trend_metrics(
                brand_rate=0.5,
                owned_rate=0.0,
                competitor_rate=1.0,
                brand_count=1,
                competitor_count=1,
                total_completed=2,
            ),
            visibility_score=50.0,
            total_completed=2,
        )
        await session.commit()

        weekly = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            granularity="week",
        )
        monthly = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            granularity="month",
        )

    assert len(weekly) == 1
    bucket = weekly[0]
    # UTC week boundary is the Monday 00:00.
    assert bucket.completed_at == datetime(2026, 1, 5, tzinfo=UTC)
    assert bucket.audit_id is None
    assert len(bucket.source_snapshot_ids) == 2
    # Completion-weighted brand rate: (1.0*4 + 0.5*2) / 6 = 5/6.
    assert bucket.brand_mention_rate == pytest.approx(round(5 / 6, 4))
    # Owned-citation rate: (0.5*4 + 0.0*2) / 6 = 2/6.
    assert bucket.owned_citation_rate == pytest.approx(round(2 / 6, 4))
    # Mention counts SUM before division: Acme 4+1=5, Globex 2+1=3, total 8.
    brand_row = next(r for r in bucket.rankings if r.is_brand)
    assert brand_row.mention_count == 5
    assert brand_row.share_of_voice == pytest.approx(round(5 / 8, 4))
    assert bucket.sov.mention == pytest.approx(round(5 / 8, 4))

    assert len(monthly) == 1
    assert monthly[0].completed_at == datetime(2026, 1, 1, tzinfo=UTC)
    assert len(monthly[0].source_snapshot_ids) == 2


@pytest.mark.asyncio
async def test_trends_mixed_version_strict_fallback_and_non_strict_marking(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        # Two same-week snapshots produced under DIFFERENT analyzer versions.
        await _seed_snapshot(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 1, 5, tzinfo=UTC),
            metrics=_trend_metrics(
                brand_rate=1.0,
                owned_rate=0.5,
                competitor_rate=0.5,
                brand_count=4,
                competitor_count=2,
                total_completed=4,
            ),
            visibility_score=100.0,
            total_completed=4,
            analyzer_version="b6-analysis-1",
        )
        await _seed_snapshot(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 1, 7, tzinfo=UTC),
            metrics=_trend_metrics(
                brand_rate=0.5,
                owned_rate=0.0,
                competitor_rate=1.0,
                brand_count=1,
                competitor_count=1,
                total_completed=2,
            ),
            visibility_score=50.0,
            total_completed=2,
            analyzer_version="b6-analysis-2",
        )
        await session.commit()

        # Strict (default): a version-crossing bucket makes the whole range
        # fall back to raw per-run points.
        strict = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            granularity="week",
        )
        assert len(strict) == 2
        assert all(p.audit_id is not None for p in strict)
        assert all(len(p.source_snapshot_ids) == 1 for p in strict)

        # Non-strict: the mixed bucket is emitted + flagged with both versions.
        # The flag is read where the bucketing happens, which now lives in
        # `trend_folding` after that module was split out of `service`.
        monkeypatch.setattr(
            analysis_trend_folding, "VISIBILITY_TRENDS_STRICT_VERSION_BUCKETS", False
        )
        marked = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            granularity="week",
        )
    assert len(marked) == 1
    assert marked[0].spans_version_boundary is True
    assert marked[0].analyzer_versions == ["b6-analysis-1", "b6-analysis-2"]
    assert len(marked[0].source_snapshot_ids) == 2


@pytest.mark.asyncio
async def test_trends_single_point_and_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        # No snapshots yet -> empty (not an error).
        empty = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
        assert empty == []

        await _seed_snapshot(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 1, 5, tzinfo=UTC),
            metrics=_trend_metrics(
                brand_rate=1.0,
                owned_rate=0.5,
                competitor_rate=0.5,
                brand_count=4,
                competitor_count=2,
                total_completed=4,
            ),
            visibility_score=100.0,
            total_completed=4,
        )
        await session.commit()
        one = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
        assert len(one) == 1


@pytest.mark.asyncio
async def test_trends_workspace_isolation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await _seed_reference_snapshot(session)
        # A foreign workspace sees nothing (invariant 5).
        foreign = await get_visibility_trends(
            session,
            workspace_id=_uuid.uuid4(),
            project_id=seed.project_id,
        )
        assert foreign == []


@pytest.mark.asyncio
async def test_trends_invalid_query_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        await session.commit()
        with pytest.raises(TrendQueryError):
            await get_visibility_trends(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                granularity="daily",
            )
        with pytest.raises(TrendQueryError):
            await get_visibility_trends(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                logical_engine="bing",
            )
        with pytest.raises(TrendQueryError):
            await get_visibility_trends(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                from_at=datetime(2026, 3, 1, tzinfo=UTC),
                to_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        with pytest.raises(TrendQueryError):
            await get_visibility_trends(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                from_at=datetime(2026, 3, 1),  # naive
            )
        # An empty model id is a query error (HTTP 422), never a silent slice.
        with pytest.raises(TrendQueryError):
            await get_visibility_trends(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                transport_model="  ",
            )


async def test_trends_partition_by_measurement_identity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        snapshots = await _seed_partition_audits(
            session, workspace_id=seed.workspace_id, project_id=seed.project_id
        )
        await session.commit()

        raw = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            granularity="run",
        )
        weekly = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            granularity="week",
        )
        monthly = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            granularity="month",
        )

    expected_identities = {
        (model, retrieval) for model, retrieval, _ in _PARTITION_IDENTITIES
    }
    # Raw granularity: one point per run, each carrying its frozen identity.
    assert len(raw) == 6
    assert {_identity_of(p) for p in raw} == expected_identities
    assert all(p.audit_id is not None for p in raw)

    # Week + month fold WITHIN an identity only: four separate ordered series,
    # one per identity — never one blended bucket (no cross-partition folding).
    for points in (weekly, monthly):
        assert len(points) == 3
        assert {_identity_of(p) for p in points} == expected_identities
        for point in points:
            identity = _identity_of(point)
            expected = snapshots[identity]
            # The bucket folds exactly its own partition's snapshots...
            assert {str(sid) for sid in point.source_snapshot_ids} == {
                str(s.id) for s in expected
            }
            # ...so the folded visibility is the partition's own average
            # (completion-weighted; 1 completion per run) and never blends in
            # another mode/model/retrieval run.
            scores = [s.visibility_score for s in expected]
            assert point.visibility_score == pytest.approx(sum(scores) / len(scores))
            # Aggregate provenance: the partition's single frozen route.
            assert [p.transport_model for p in point.model_provenance] == [identity[0]]
            assert all(
                p.retrieval_enabled == identity[1] for p in point.model_provenance
            )
            assert "mode" not in point.model_dump()
    # Ordered by bucket boundary, then deterministically by identity.
    assert [(_identity_of(p)) for p in weekly] == sorted(
        {_identity_of(p) for p in weekly},
        key=lambda i: (i[0], str(i[1])),
    )


@pytest.mark.asyncio
async def test_trends_identity_slice_filters_before_folding(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        snapshots = await _seed_partition_audits(
            session, workspace_id=seed.workspace_id, project_id=seed.project_id
        )
        await session.commit()

        # A full identity slice at week granularity folds ONLY the slice.
        sliced = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            granularity="week",
            transport_model="model-a",
            retrieval_enabled=True,
        )
        assert len(sliced) == 1
        point = sliced[0]
        assert _identity_of(point) == ("model-a", True)
        assert point.visibility_score == pytest.approx(70.0)
        assert {str(sid) for sid in point.source_snapshot_ids} == {
            str(s.id) for s in snapshots[("model-a", True)]
        }

        # An unsliced run projection keeps every frozen identity.
        all_runs = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
        assert len(all_runs) == 6

        # A retrieval slice at run granularity selects exactly the matching
        # runs (retrieval-on across both models).
        retrieval_on = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            retrieval_enabled=True,
        )
        assert len(retrieval_on) == 4
        assert all(p.retrieval_enabled is True for p in retrieval_on)

        # A model-only slice excludes the other model's runs.
        model_b = await get_visibility_trends(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            transport_model="model-b",
        )
        assert len(model_b) == 2
        assert all(p.transport_model == "model-b" for p in model_b)
