"""ExecutionCostProjection persistence: append-only composite identity, two
pricing versions coexisting for one artifact, and the repricing CLI glue
against a real Postgres schema (no provider calls anywhere).
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.core.config.costs as costs_config
import scripts.reprice_execution_costs as reprice_cli
from app.core.config.audits import ATTEMPT_STATUS_SUCCEEDED, AUDIT_TRIGGER_MANUAL
from app.core.config.costs import (
    EXECUTION_COST_FORMULA_VERSION,
    PRICING_CATALOG_VERSION,
    PROJECTION_STATUS_COMPLETE,
    PROJECTION_STATUS_PARTIAL,
    ROUTE_CLAUDE,
    RoutePricing,
)
from app.core.config.provider_catalog import (
    ENGINE_CLAUDE,
    TRANSPORT_ANTHROPIC,
    measurement_route,
)
from app.domain.audits.cost_projection import append_repricing
from app.domain.audits.creation import create_audit
from app.models.audit import (
    AuditTask,
    ExecutionCostProjection,
    ProviderAttempt,
    RawResponseArtifact,
)
from tests.component.audit_helpers import seed_audit_fixtures

_USAGE = {
    "uncached_input_tokens": 1_000,
    "output_tokens": 500,
    "total_tokens": 1_500,
    "search_requests": 2,
}

_PRICED_V2 = RoutePricing(
    uncached_input_microusd_per_million=1_000_000,
    cached_input_microusd_per_million=None,
    output_microusd_per_million=4_000_000,
    reasoning_microusd_per_million=None,
    search_fee_microusd=35_000,
    currency="USD",
    effective_date="2026-06-01",
    pricing_version="test-priced-v2",
)

_MODEL = measurement_route(ENGINE_CLAUDE).transport_model


@pytest.fixture
async def seeded_artifact(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
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
        task_id = await session.scalar(
            select(AuditTask.id).where(AuditTask.audit_id == audit.id)
        )
        assert task_id is not None
        artifact = RawResponseArtifact(
            audit_id=audit.id,
            task_id=task_id,
            logical_engine=ENGINE_CLAUDE,
            transport_provider=TRANSPORT_ANTHROPIC,
            transport_model=_MODEL,
            answer_text="Acme is a great option.",
            usage=dict(_USAGE),
            latency_ms=5,
        )
        session.add(artifact)
        session.add(
            ProviderAttempt(
                task_id=task_id,
                audit_id=audit.id,
                attempt_number=1,
                logical_engine=ENGINE_CLAUDE,
                transport_provider=TRANSPORT_ANTHROPIC,
                transport_model=_MODEL,
                status=ATTEMPT_STATUS_SUCCEEDED,
                latency_ms=5,
            )
        )
        await session.commit()
        return audit.id, task_id, artifact.id


async def _projection_count(session: AsyncSession, artifact_id: uuid.UUID) -> int:
    count = await session.scalar(
        select(func.count())
        .select_from(ExecutionCostProjection)
        .where(ExecutionCostProjection.raw_response_artifact_id == artifact_id)
    )
    return int(count or 0)


async def test_append_repricing_inserts_once_by_composite_identity(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_artifact: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    audit_id, task_id, artifact_id = seeded_artifact
    async with session_factory() as session:
        first = await append_repricing(
            session,
            artifact_id=artifact_id,
            pricing_version=PRICING_CATALOG_VERSION,
            formula_version=EXECUTION_COST_FORMULA_VERSION,
        )
        await session.commit()
    async with session_factory() as session:
        # Replay of the same composite identity returns the existing row —
        # an append-only retry, never an update or a duplicate insert.
        replay = await append_repricing(
            session,
            artifact_id=artifact_id,
            pricing_version=PRICING_CATALOG_VERSION,
            formula_version=EXECUTION_COST_FORMULA_VERSION,
        )
        await session.commit()
        assert await _projection_count(session, artifact_id) == 1

    assert first is not None and replay is not None
    assert replay.id == first.id
    assert first.audit_id == audit_id
    assert first.task_id == task_id
    assert first.raw_response_artifact_id == artifact_id
    assert first.formula_version == EXECUTION_COST_FORMULA_VERSION
    assert first.pricing_version == PRICING_CATALOG_VERSION
    # Canonical usage is priced only where the exact route card is verified.
    assert first.uncached_input_tokens == 1_000
    assert first.output_tokens == 500
    assert first.total_tokens == 1_500
    assert first.search_requests == 2
    assert first.cached_input_tokens is None
    assert first.reasoning_tokens is None
    assert first.uncached_input_cost_microusd == 1_000
    assert first.output_cost_microusd == 2_500
    assert first.projected_total_cost_microusd is None
    assert first.provider_reported_cost_microusd is None
    assert first.projection_status == PROJECTION_STATUS_PARTIAL
    # Provenance: the actual persisted ProviderAttempt rows, not a budget.
    assert first.attempt_count == 1


async def test_two_pricing_versions_coexist_for_one_artifact(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_artifact: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setitem(
        costs_config._ROUTE_PRICING_CATALOGS,
        "test-priced-v2",
        {ROUTE_CLAUDE: _PRICED_V2},
    )
    _, _, artifact_id = seeded_artifact
    async with session_factory() as session:
        v1 = await append_repricing(
            session,
            artifact_id=artifact_id,
            pricing_version=PRICING_CATALOG_VERSION,
            formula_version=EXECUTION_COST_FORMULA_VERSION,
        )
        v2 = await append_repricing(
            session,
            artifact_id=artifact_id,
            pricing_version="test-priced-v2",
            formula_version=EXECUTION_COST_FORMULA_VERSION,
        )
        await session.commit()
        assert await _projection_count(session, artifact_id) == 2

    assert v1 is not None and v2 is not None
    assert v1.id != v2.id
    # The new row prices every applicable line under the verified card.
    assert v2.projection_status == PROJECTION_STATUS_COMPLETE
    assert v2.uncached_input_cost_microusd == 1_000
    assert v2.output_cost_microusd == 2_000
    assert v2.search_cost_microusd == 70_000
    assert v2.projected_total_cost_microusd == 73_000
    # The prior version's row is untouched (append-only).
    assert v1.projection_status == PROJECTION_STATUS_PARTIAL
    assert v1.projected_total_cost_microusd is None


async def test_append_repricing_returns_none_for_unknown_version_or_artifact(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_artifact: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
) -> None:
    _, _, artifact_id = seeded_artifact
    async with session_factory() as session:
        assert (
            await append_repricing(
                session,
                artifact_id=uuid.uuid4(),
                pricing_version=PRICING_CATALOG_VERSION,
                formula_version=EXECUTION_COST_FORMULA_VERSION,
            )
            is None
        )
        assert (
            await append_repricing(
                session,
                artifact_id=artifact_id,
                pricing_version="no-such-version",
                formula_version=EXECUTION_COST_FORMULA_VERSION,
            )
            is None
        )
        await session.rollback()


async def test_cli_dry_run_then_append_then_idempotent_rerun(
    session_factory: async_sessionmaker[AsyncSession],
    seeded_artifact: tuple[uuid.UUID, uuid.UUID, uuid.UUID],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(reprice_cli, "SessionLocal", session_factory)
    _, _, artifact_id = seeded_artifact
    base_args = [
        "--formula-version",
        EXECUTION_COST_FORMULA_VERSION,
        "--pricing-version",
        PRICING_CATALOG_VERSION,
    ]
    parser = reprice_cli.build_parser()

    # Dry-run reports but writes nothing.
    assert await reprice_cli._run(parser.parse_args([*base_args, "--dry-run"])) == 0
    async with session_factory() as session:
        assert await _projection_count(session, artifact_id) == 0

    # Real run appends exactly one row for the artifact.
    assert await reprice_cli._run(parser.parse_args(base_args)) == 0
    async with session_factory() as session:
        assert await _projection_count(session, artifact_id) == 1

    # A rerun sees the composite identity already projected and inserts none.
    assert await reprice_cli._run(parser.parse_args(base_args)) == 0
    async with session_factory() as session:
        assert await _projection_count(session, artifact_id) == 1
