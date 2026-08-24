"""Persisted visibility-evidence projection and isolation scenarios.

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
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.audits import (
    AUDIT_STATUS_COMPLETED,
)
from app.core.config.provider_catalog import (
    ENGINE_CHATGPT,
    ENGINE_GEMINI,
    measurement_route,
)
from app.domain.analysis.errors import AnalysisNotFoundError, TrendQueryError
from app.domain.analysis.evidence import (
    get_visibility_evidence,
)
from app.domain.analysis.schemas import VisibilityFanoutState
from app.models.analysis import (
    ResponseAnalysis,
)
from app.models.audit import (
    Audit,
    RawResponseArtifact,
)
from app.workers.audit import execution as audit_execution
from tests.component.analysis_api_helpers import _event, _seed_evidence_execution
from tests.component.audit_helpers import seed_audit_fixtures

# The model the PLANNER freezes for these audits. Read from the catalog rather
# than pinned as a literal: these assertions are about provenance travelling
# intact from the frozen route to the projection, not about which Gemini build
# is current, and a literal here goes stale on every model-version bump.
GEMINI_MODEL = measurement_route(ENGINE_GEMINI).transport_model


async def test_evidence_projects_mentions_citations_and_queries(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persisted mentions/citations + artifact query text are projected as-is."""

    def _boom(**_: object):
        raise AssertionError("evidence projection must not call a provider")

    monkeypatch.setattr(audit_execution, "build_adapter", _boom)

    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            transport_model=GEMINI_MODEL,
            artifact_events=[
                _event(0, "best crm software", call_id="c1"),
                _event(1, "crm pricing", call_id="c1", query_sequence=1),
            ],
            search_query_count=2,
            brand_mentions=[("Acme Corp", 0)],
            competitor_mentions=["Globex"],
            citations=[
                ("https://acme.com/", "acme.com", "owned"),
                ("https://globex.com/", "globex.com", "competitor"),
            ],
        )
        await session.commit()

        result = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
    assert result.truncated is False
    assert len(result.items) == 1
    item = result.items[0]
    # Query fanout: real query text from the artifact -> queries_available.
    assert item.state == VisibilityFanoutState.QUERIES_AVAILABLE
    assert item.query_text_available is True
    assert item.event_source == "raw_artifact"
    assert [e.query for e in item.search_events] == [
        "best crm software",
        "crm pricing",
    ]
    assert item.search_query_count == 2
    # Persisted mentions projected (never inferred).
    brand = [m for m in item.mentions if m.kind == "brand"]
    competitor = [m for m in item.mentions if m.kind == "competitor"]
    assert brand[0].name == "Acme Corp"
    assert brand[0].first_offset == 0
    assert brand[0].analyzer_version == "b6-analysis-1"
    assert competitor[0].name == "Globex"
    # Classified citations projected.
    classifications = {c.classification for c in item.citations}
    assert classifications == {"owned", "competitor"}
    # Provenance ids present.
    assert item.analysis_id is not None
    assert item.task_id is not None
    assert item.artifact_id is not None
    assert item.prompt_snapshot_id is not None
    # Frozen measurement provenance (inv. 4/7): the frozen mode column, and
    # retrieval unrecorded when nothing froze it — never inferred from live
    # config. Vocabulary lock: no ``mode`` alias.
    assert item.logical_engine == ENGINE_GEMINI
    assert item.transport_model == GEMINI_MODEL
    assert item.retrieval_enabled is None
    assert "mode" not in item.model_dump()


@pytest.mark.asyncio
async def test_evidence_artifact_first_then_task_fallback(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Prefer artifact events; fall back to task events when artifact empty."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        # Artifact present but with NO event payload -> fall back to task copy.
        await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            prompt_index=0,
            artifact_events=[],
            task_events=[_event(0, "fallback query")],
        )
        await session.commit()
        result = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
    by_index = {i.prompt_index: i for i in result.items}
    assert by_index[0].event_source == "audit_task"
    assert [e.query for e in by_index[0].search_events] == ["fallback query"]


@pytest.mark.asyncio
async def test_evidence_malformed_entries_ignored_and_empty_preserved(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Malformed stored entries are skipped; empty query strings preserved."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            artifact_events=[
                "not-a-dict",
                123,
                None,
                _event(0, ""),  # empty query preserved (count-only event)
                _event(1, "real query"),
            ],
            search_query_count=2,
        )
        await session.commit()
        result = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
    item = result.items[0]
    # Only the two well-formed dict entries survive; text never fabricated.
    assert [e.query for e in item.search_events] == ["", "real query"]
    assert item.state == VisibilityFanoutState.QUERIES_AVAILABLE


@pytest.mark.asyncio
async def test_evidence_count_only_retired_transport(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Retired transport count-only row: count present, no query text."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            logical_engine=ENGINE_CHATGPT,
            transport_provider="retired",
            transport_model="openai/gpt-5.4",
            search_used=True,
            search_query_count=3,
            # A parser can emit count-only empty-query events.
            artifact_events=[_event(0, ""), _event(1, "")],
            # An analysis with citations but no query strings stays count_only.
            citations=[("https://ref.com/", "ref.com", "third_party")],
        )
        await session.commit()
        result = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
    item = result.items[0]
    assert item.state == VisibilityFanoutState.COUNT_ONLY
    assert item.query_text_available is False
    assert item.search_query_count == 3
    # The persisted transport identity remains part of the evidence row.
    assert item.transport_provider == "retired"
    assert item.transport_model == "openai/gpt-5.4"
    assert len(item.citations) == 1


@pytest.mark.asyncio
async def test_evidence_no_search_state(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """No search signal + zero count + no query text -> no_search."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            search_used=False,
            search_query_count=0,
            artifact_events=[],
            task_events=[],
        )
        await session.commit()
        result = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
    item = result.items[0]
    assert item.state == VisibilityFanoutState.NO_SEARCH
    assert item.event_source == "none"
    assert item.search_events == []


@pytest.mark.asyncio
async def test_evidence_prompt_engine_audit_and_date_filters(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        prompt_a = seed.prompt_ids[0]
        # Gemini, prompt_a, Feb.
        audit_gemini, *_ = await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 10, tzinfo=UTC),
            logical_engine=ENGINE_GEMINI,
            prompt_id=prompt_a,
            artifact_events=[_event(0, "gemini query")],
        )
        # ChatGPT, no source prompt, January.
        await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 1, 10, tzinfo=UTC),
            logical_engine=ENGINE_CHATGPT,
            prompt_id=None,
            artifact_events=[_event(0, "chatgpt query")],
        )
        await session.commit()

        # Engine filter.
        gemini = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            logical_engine=ENGINE_GEMINI,
        )
        assert {i.logical_engine for i in gemini.items} == {ENGINE_GEMINI}

        # Prompt filter (source prompt on the frozen snapshot).
        by_prompt = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            prompt_id=prompt_a,
        )
        assert len(by_prompt.items) == 1
        assert by_prompt.items[0].prompt_id == prompt_a

        # Audit filter.
        by_audit = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            audit_id=audit_gemini.id,
        )
        assert len(by_audit.items) == 1
        assert by_audit.items[0].audit_id == audit_gemini.id

        # Date window (only Feb).
        windowed = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            from_at=datetime(2026, 2, 1, tzinfo=UTC),
            to_at=datetime(2026, 3, 1, tzinfo=UTC),
        )
        assert len(windowed.items) == 1
        assert windowed.items[0].logical_engine == ENGINE_GEMINI

        # Audit + date INTERSECT: the audit outside the window yields nothing.
        empty = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            audit_id=audit_gemini.id,
            from_at=datetime(2025, 1, 1, tzinfo=UTC),
            to_at=datetime(2025, 12, 31, tzinfo=UTC),
        )
        assert empty.items == []


@pytest.mark.asyncio
async def test_evidence_limit_truncation_and_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        # Three audits on distinct days.
        for day in (1, 2, 3):
            await _seed_evidence_execution(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                completed_at=datetime(2026, 2, day, tzinfo=UTC),
                artifact_events=[_event(0, f"day {day}")],
            )
        await session.commit()

        # limit=2 -> newest two, truncated True.
        limited = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            limit=2,
        )
        assert limited.truncated is True
        assert len(limited.items) == 2
        # Newest-first by completion.
        assert limited.items[0].completed_at == datetime(2026, 2, 3, tzinfo=UTC)
        assert limited.items[1].completed_at == datetime(2026, 2, 2, tzinfo=UTC)

        full = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            limit=100,
        )
        assert full.truncated is False
        assert len(full.items) == 3


@pytest.mark.asyncio
async def test_evidence_deterministic_order_within_audit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Within one audit, order by prompt index, engine, repetition."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=2)
        audit = Audit(
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            status=AUDIT_STATUS_COMPLETED,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            requested_count=3,
            completed_count=3,
        )
        session.add(audit)
        await session.flush()
        # Seed out of natural order.
        await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            prompt_index=1,
            repetition=0,
            audit=audit,
        )
        await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            prompt_index=0,
            repetition=1,
            audit=audit,
        )
        await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            prompt_index=0,
            repetition=0,
            audit=audit,
        )
        await session.commit()
        result = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
    order = [(i.prompt_index, i.repetition) for i in result.items]
    assert order == [(0, 0), (0, 1), (1, 0)]


@pytest.mark.asyncio
async def test_evidence_deleted_prompt_snapshot_readable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A deleted source prompt stays readable via frozen text + null id."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            prompt_id=None,  # source prompt deleted (SET NULL)
            prompt_text="frozen prompt text survives",
            artifact_events=[_event(0, "q")],
        )
        await session.commit()
        result = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
        # Not selectable by a current prompt id...
        by_prompt = await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            prompt_id=seed.prompt_ids[0],
        )
    item = result.items[0]
    assert item.prompt_id is None
    assert item.prompt_text == "frozen prompt text survives"
    assert by_prompt.items == []


@pytest.mark.asyncio
async def test_evidence_workspace_isolation_and_empty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            artifact_events=[_event(0, "q")],
        )
        await session.commit()
        # Foreign workspace sees nothing (invariant 5).
        foreign = await get_visibility_evidence(
            session,
            workspace_id=_uuid.uuid4(),
            project_id=seed.project_id,
        )
        assert foreign.items == []
        assert foreign.truncated is False


@pytest.mark.asyncio
async def test_evidence_cross_workspace_audit_404(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A selected audit outside the workspace/project must 404 (no leak)."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        other = await seed_audit_fixtures(session, prompt_count=1)
        other_audit, *_ = await _seed_evidence_execution(
            session,
            workspace_id=other.workspace_id,
            project_id=other.project_id,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            artifact_events=[_event(0, "q")],
        )
        await session.commit()
        with pytest.raises(AnalysisNotFoundError):
            await get_visibility_evidence(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                audit_id=other_audit.id,
            )


@pytest.mark.asyncio
async def test_evidence_invalid_query_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        await session.commit()
        with pytest.raises(TrendQueryError):
            await get_visibility_evidence(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                logical_engine="bing",
            )
        with pytest.raises(TrendQueryError):
            await get_visibility_evidence(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                from_at=datetime(2026, 3, 1, tzinfo=UTC),
                to_at=datetime(2026, 1, 1, tzinfo=UTC),
            )
        with pytest.raises(TrendQueryError):
            await get_visibility_evidence(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                from_at=datetime(2026, 3, 1),  # naive
            )
        with pytest.raises(TrendQueryError):
            await get_visibility_evidence(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                limit=0,
            )
        with pytest.raises(TrendQueryError):
            await get_visibility_evidence(
                session,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                limit=501,
            )


@pytest.mark.asyncio
async def test_evidence_never_calls_provider_and_is_read_only(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider factory patched to fail; row counts unchanged after read."""

    def _boom(**_: object):
        raise AssertionError("evidence read must never construct an adapter")

    monkeypatch.setattr(audit_execution, "build_adapter", _boom)

    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        await _seed_evidence_execution(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            completed_at=datetime(2026, 2, 1, tzinfo=UTC),
            artifact_events=[_event(0, "immutable query")],
            brand_mentions=[("Acme Corp", 0)],
            citations=[("https://acme.com/", "acme.com", "owned")],
        )
        await session.commit()

    async with session_factory() as session:
        before_analyses = await session.scalar(
            select(func.count()).select_from(ResponseAnalysis)
        )
        before_events = await session.scalar(
            select(RawResponseArtifact.search_events).limit(1)
        )
        await get_visibility_evidence(
            session,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
        )
        after_analyses = await session.scalar(
            select(func.count()).select_from(ResponseAnalysis)
        )
        after_events = await session.scalar(
            select(RawResponseArtifact.search_events).limit(1)
        )
    # A pure read: no derived rows created and stored events unchanged.
    assert before_analyses == after_analyses == 1
    assert before_events == after_events == [_event(0, "immutable query")]
