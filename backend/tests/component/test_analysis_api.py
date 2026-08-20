"""Analysis metrics, visibility, provenance, and export projections."""

from __future__ import annotations

import uuid as _uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.exports import audit_to_csv, audit_to_markdown
from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
    AUDIT_TRIGGER_MANUAL,
    MEASUREMENT_MODE_BENCHMARK,
    MEASUREMENT_MODE_PULSE,
    audit_settings,
)
from app.core.config.provider_catalog import (
    ENGINE_GEMINI,
    TRANSPORT_GOOGLE,
    measurement_route,
)
from app.domain.analysis import visibility as analysis_service
from app.domain.analysis.errors import AnalysisNotFoundError
from app.domain.analysis.evidence import (
    get_execution_evidence,
    load_export_bundle,
)
from app.domain.analysis.metrics import get_metrics
from app.domain.analysis.visibility import get_visibility
from app.domain.audits.creation import create_audit
from app.models.analysis import (
    BrandMention,
    Citation,
    CompetitorMention,
    MetricSnapshot,
    ResponseAnalysis,
)
from app.models.audit import (
    RawResponseArtifact,
)
from app.workers.audit import execution as audit_execution
from tests.component.analysis_api_helpers import (
    _run_completed_audit,
    _UsageStubAdapter,
)
from tests.component.analysis_api_helpers import (
    _stub_adapter as _stub_adapter,
)
from tests.component.audit_helpers import seed_audit_fixtures

# The model the PLANNER freezes for these audits. Read from the catalog rather
# than pinned as a literal: these assertions are about provenance travelling
# intact from the frozen route to the projection, not about which Gemini build
# is current, and a literal here goes stale on every model-version bump.
GEMINI_MODEL = measurement_route(ENGINE_GEMINI, "pulse").transport_model


def test_logo_lookup_distinguishes_same_named_brand_and_competitor() -> None:
    brand_id = _uuid.uuid4()
    competitor_id = _uuid.uuid4()
    logo_urls = {
        brand_id: "/brand-logo",
        competitor_id: "/competitor-logo",
    }
    identity_ids = {
        (True, "Shared name"): brand_id,
        (False, "Shared name"): competitor_id,
    }
    website_urls = {
        (True, "Shared name"): "brand.example",
        (False, "Shared name"): "competitor.example",
    }

    assert (
        analysis_service._logo_url_for_name(
            "Shared name", True, logo_urls, identity_ids
        )
        == "/brand-logo"
    )
    assert (
        analysis_service._logo_url_for_name(
            "Shared name", False, logo_urls, identity_ids
        )
        == "/competitor-logo"
    )
    assert (
        analysis_service._website_url_for_name("Shared name", True, website_urls)
        == "brand.example"
    )
    assert (
        analysis_service._website_url_for_name("Shared name", False, website_urls)
        == "competitor.example"
    )
    assert analysis_service._website_url_for_name("Missing", False, None) is None


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Acme.COM/path", "https://acme.com"),
        ("https://www.acme.com/products", "https://acme.com"),
        ("", None),
    ],
)
def test_logo_website_urls_are_normalized(value: str, expected: str | None) -> None:
    assert analysis_service._normalized_logo_website_url(value) == expected


async def test_benchmark_fixture_persists_grounded_search_evidence(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    _seed, audit = await _run_completed_audit(
        session_factory, measurement_mode=MEASUREMENT_MODE_BENCHMARK
    )

    async with session_factory() as session:
        artifacts = list(
            (
                await session.scalars(
                    select(RawResponseArtifact).where(
                        RawResponseArtifact.audit_id == audit.id
                    )
                )
            ).all()
        )

    assert artifacts
    assert all(artifact.search_used is True for artifact in artifacts)
    assert all(artifact.search_events for artifact in artifacts)


@pytest.mark.asyncio
async def test_metrics_and_visibility_are_projections(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seed, audit = await _run_completed_audit(session_factory)

    # After finalize the projections must never touch a provider: make the
    # adapter factory explode so any provider call during a projection fails.
    def _boom(**_: object):
        raise AssertionError("projection must not call a provider (invariant 7)")

    monkeypatch.setattr(audit_execution, "build_adapter", _boom)

    async with session_factory() as session:
        # Audit reached COMPLETED with a populated snapshot.
        refreshed = await session.get(type(audit), audit.id)
        assert refreshed is not None
        assert refreshed.status == AUDIT_STATUS_COMPLETED

        metrics = await get_metrics(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert metrics.total_completed == 4
        # Composite: mentions 60 + qualified owned citations 15 + position 12.5.
        assert metrics.visibility_score == 87.5
        assert metrics.analyzer_version
        assert "share_of_voice" in metrics.metrics
        assert metrics.metrics["sentiment"] is None
        assert metrics.metrics["avg_position"] is None

        vis = await get_visibility(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
        assert vis.audit_id == audit.id
        assert vis.visibility_score == 87.5
        # Brand-vs-competitor rankings populated; brand row present.
        brand_rows = [r for r in vis.rankings if r.is_brand]
        assert len(brand_rows) == 1
        assert brand_rows[0].mention_rate == 1.0
        # Per-engine comparison for the single engine.
        assert len(vis.per_engine) == 1
        assert vis.per_engine[0].logical_engine == ENGINE_GEMINI
        # Measurement provenance (invariants 4/7): the frozen mode column and
        # the stable aggregate model-provenance list — retrieval comes from
        assert vis.measurement_mode == MEASUREMENT_MODE_PULSE
        assert [p.model_dump() for p in vis.model_provenance] == [
            {
                "logical_engine": ENGINE_GEMINI,
                "transport_provider": TRANSPORT_GOOGLE,
                "transport_model": GEMINI_MODEL,
                "retrieval_enabled": False,
            }
        ]
        # Vocabulary lock: no ``mode`` alias is ever emitted.
        assert "mode" not in vis.model_dump()
        # Roadmap fields present but null (decision B-2).
        assert vis.sentiment is None
        assert vis.avg_position is None


@pytest.mark.asyncio
async def test_provenance_and_citation_classification_persisted(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    _seed, audit = await _run_completed_audit(session_factory)

    async with session_factory() as session:
        analyses = list(
            (
                await session.scalars(
                    select(ResponseAnalysis).where(
                        ResponseAnalysis.audit_id == audit.id
                    )
                )
            ).all()
        )
        assert len(analyses) == 4
        # Every derived row references its artifact + analyzer version (inv. 4).
        for analysis in analyses:
            assert analysis.analyzer_version
            assert analysis.scoring_rule_version
            assert analysis.artifact_id is not None

        # Brand + competitor mentions recorded with provenance.
        brand_count = await session.scalar(
            select(func.count())
            .select_from(BrandMention)
            .where(BrandMention.audit_id == audit.id)
        )
        comp_count = await session.scalar(
            select(func.count())
            .select_from(CompetitorMention)
            .where(CompetitorMention.audit_id == audit.id)
        )
        assert brand_count == 4  # brand mentioned in all 4
        assert comp_count == 4  # Globex mentioned in all 4

        # Citation classification: owned (acme.com) + competitor (globex.com).
        citations = list(
            (
                await session.scalars(
                    select(Citation).where(Citation.audit_id == audit.id)
                )
            ).all()
        )
        assert all(c.analyzer_version for c in citations)
        owned = [c for c in citations if c.classification == "owned"]
        competitor = [c for c in citations if c.classification == "competitor"]
        assert owned and all(c.is_owned for c in owned)
        assert competitor and all(c.matched_competitor == "Globex" for c in competitor)


@pytest.mark.asyncio
async def test_execution_evidence_projection(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    seed, audit = await _run_completed_audit(session_factory)

    async with session_factory() as session:
        analysis = await session.scalar(
            select(ResponseAnalysis).where(ResponseAnalysis.audit_id == audit.id)
        )
        assert analysis is not None
        # Keyed on the execution (AuditTask) id, matching the id clients get
        # from GET /audits/{id}/executions — not the internal analysis id.
        evidence = await get_execution_evidence(
            session,
            workspace_id=seed.workspace_id,
            task_id=analysis.task_id,
        )
        assert evidence.brand_mentioned is True
        assert evidence.citation_count == 2
        assert len(evidence.citations) == 2
        assert "Globex" in evidence.competitors_mentioned
        # id/task_id are the execution id; analysis_id is the internal id.
        assert evidence.id == analysis.task_id
        assert evidence.task_id == analysis.task_id
        assert evidence.analysis_id == analysis.id
        # Execution-level provenance: the exact singular model plus the frozen
        # mode/retrieval state the call executed under (inv. 4/7, 10).
        assert evidence.transport_model == GEMINI_MODEL
        assert evidence.measurement_mode == MEASUREMENT_MODE_PULSE
        assert evidence.retrieval_enabled is False
        assert "mode" not in evidence.model_dump()
        # Roadmap fields present but null.
        assert evidence.sentiment is None
        assert evidence.avg_position is None

        # A foreign workspace cannot read the evidence (invariant 5).
        import uuid

        with pytest.raises(AnalysisNotFoundError):
            await get_execution_evidence(
                session,
                workspace_id=uuid.uuid4(),
                task_id=analysis.task_id,
            )


@pytest.mark.asyncio
async def test_exports_render_from_persisted_rows(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    seed, audit = await _run_completed_audit(session_factory)

    async with session_factory() as session:
        loaded_audit, tasks = await load_export_bundle(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert len(tasks) == 4

        csv_body = audit_to_csv(loaded_audit, tasks)
        assert "audit_id,prompt_index" in csv_body.splitlines()[0]
        # One header + one row per execution.
        assert len(csv_body.strip().splitlines()) == 1 + 4

        md_body = audit_to_markdown(loaded_audit, tasks)
        assert "# AI Search Visibility Benchmark" in md_body
        assert "## Headline Metrics" in md_body
        assert "## Methodology" in md_body


@pytest.mark.asyncio
async def test_metrics_not_found_for_unanalyzed_audit(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    # Seed + create but DON'T run the worker -> no MetricSnapshot yet.
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
    async with session_factory() as session:
        audit = await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            prompt_set_id=seed.prompt_set_id,
            repetitions=1,
            random_seed="1",
        )
    async with session_factory() as session:
        with pytest.raises(AnalysisNotFoundError):
            await get_metrics(
                session, workspace_id=seed.workspace_id, audit_id=audit.id
            )
        # No completed audit -> visibility 404s too.
        snapshot = await session.scalar(
            select(MetricSnapshot).where(MetricSnapshot.audit_id == audit.id)
        )
        assert snapshot is None
        with pytest.raises(AnalysisNotFoundError):
            await get_visibility(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
            )


@pytest.mark.asyncio
async def test_snapshot_records_source_provenance(
    session_factory: async_sessionmaker[AsyncSession],
    _stub_adapter,
) -> None:
    """The MetricSnapshot traces back to the exact evidence set (invariant 4).

    ``source_analysis_ids`` must equal the succeeded tasks' analysis ids and
    ``source_artifact_ids`` their raw response artifacts.
    """
    _seed, audit = await _run_completed_audit(session_factory)

    async with session_factory() as session:
        analyses = list(
            (
                await session.scalars(
                    select(ResponseAnalysis).where(
                        ResponseAnalysis.audit_id == audit.id
                    )
                )
            ).all()
        )
        snapshot = await session.scalar(
            select(MetricSnapshot).where(MetricSnapshot.audit_id == audit.id)
        )
        assert snapshot is not None
        assert snapshot.source_analysis_ids is not None
        assert snapshot.source_artifact_ids is not None
        expected_analysis_ids = {str(a.id) for a in analyses}
        expected_artifact_ids = {
            str(a.artifact_id) for a in analyses if a.artifact_id is not None
        }
        assert set(snapshot.source_analysis_ids) == expected_analysis_ids
        assert set(snapshot.source_artifact_ids) == expected_artifact_ids
        # Every succeeded analysis has an artifact in this fixture.
        assert len(snapshot.source_artifact_ids) == len(analyses)


async def test_aggregation_preserves_provider_usage(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persisted provider usage flows into the aggregate (not dropped as zero).

    Regression: immutable artifact usage was dropped while rebuilding the
    aggregate, so token/cost metrics were always zero.
    """
    monkeypatch.setattr(
        audit_execution, "build_adapter", lambda **_: _UsageStubAdapter()
    )
    monkeypatch.setattr(audit_settings, "min_request_interval_seconds", 0.0)
    monkeypatch.setattr(audit_settings, "heartbeat_interval_seconds", 3600.0)

    seed, audit = await _run_completed_audit(session_factory)

    async with session_factory() as session:
        metrics = await get_metrics(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        token_usage = metrics.metrics["token_usage"]
        # 4 executions * 100/50 tokens each.
        assert token_usage["input_tokens"] == 400
        assert token_usage["output_tokens"] == 200
        assert token_usage["total_tokens"] == 600

        cost = metrics.metrics["cost"]
        # 4 executions * $0.25 provider-reported each — previously always zero
        # because artifact usage was dropped when rebuilding the aggregate.
        assert cost["provider_reported_cost_usd"] == pytest.approx(1.0)
