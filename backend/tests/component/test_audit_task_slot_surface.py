"""M2a audit-task shopping-surface identity and isolation contracts."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import inspect, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.analysis.product_service import (
    analyze_task_products,
    build_product_scoring_config,
)
from app.analysis.service import analyze_task, build_scoring_config
from app.core.config.audits import (
    AUDIT_QUEUE_SPEC,
    AUDIT_STATUS_COMPLETED,
    TASK_STATUS_CANCELLED,
    TASK_STATUS_QUEUED,
)
from app.domain.audits.cancellation import cancel_audit
from app.domain.audits.reads import list_tasks
from app.models.analysis import ResponseAnalysis
from app.models.audit import Audit, AuditTask
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from tests.component.test_products_visibility_api import (
    _FIXTURE_SURFACE,
    _clone_surface_task,
    _headers,
    _persist_answer,
    _seed_catalog_user_and_audit,
)


@pytest.mark.asyncio
async def test_slot_constraint_columns_and_surface_identity(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    _seed, _product, _competitor, audit = await _seed_catalog_user_and_audit(
        client, session_factory
    )
    async with session_factory() as session:
        connection = await session.connection()

        def _constraints(sync_connection):
            schema = sync_connection.get_execution_options()["schema_translate_map"][
                None
            ]
            return inspect(sync_connection).get_unique_constraints(
                "audit_tasks", schema=schema
            )

        constraints = await connection.run_sync(_constraints)
        slot = next(row for row in constraints if row["name"] == "uq_audit_task_slot")
        assert slot["column_names"] == [
            "audit_id",
            "prompt_index",
            "repetition",
            "logical_engine",
            "shopping_surface",
        ]
        measurement = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert measurement is not None
        probe = _clone_surface_task(measurement, surface=_FIXTURE_SURFACE)
        session.add(probe)
        await session.flush()
        assert measurement.idempotency_key.endswith(":")
        assert probe.idempotency_key.endswith(f":{_FIXTURE_SURFACE}")
        duplicate = _clone_surface_task(measurement, surface=_FIXTURE_SURFACE)
        duplicate.idempotency_key = f"different:{uuid.uuid4()}"
        with pytest.raises(IntegrityError):
            async with session.begin_nested():
                session.add(duplicate)
                await session.flush()


@pytest.mark.asyncio
async def test_planner_freezes_disabled_gate_without_multiplying_slots(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed, _product, _competitor, audit = await _seed_catalog_user_and_audit(
        client, session_factory
    )
    assert audit.configuration["shopping_surfaces"] == []
    assert audit.shopping_surface_snapshots == []
    assert audit.requested_count == 1
    async with session_factory() as session:
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert len(tasks) == 1
        assert tasks[0].shopping_surface == ""
        assert tasks[0].idempotency_key == f"{audit.id}:0:0:{tasks[0].logical_engine}:"


@pytest.mark.asyncio
async def test_probe_gets_product_analysis_but_brand_paths_ignore_it(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    seed, _product, _competitor, audit = await _seed_catalog_user_and_audit(
        client, session_factory
    )
    async with session_factory() as session:
        stored = await session.get(Audit, audit.id)
        measurement = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert stored is not None and measurement is not None
        probe = _clone_surface_task(measurement, surface=_FIXTURE_SURFACE)
        session.add(probe)
        await session.flush()
        await _persist_answer(session, measurement)
        await _persist_answer(session, probe)
        brand = await analyze_task(
            session, task=measurement, config=build_scoring_config(stored.configuration)
        )
        product_probe = await analyze_task_products(
            session,
            task=probe,
            config=build_product_scoring_config(stored.configuration),
        )
        assert brand is not None and product_probe is not None
        assert product_probe.shopping_surface == _FIXTURE_SURFACE
        assert (
            await session.scalar(
                select(ResponseAnalysis).where(ResponseAnalysis.task_id == probe.id)
            )
            is None
        )
        # Even a defensive/legacy probe brand row must not leak into brand evidence.
        probe_brand = ResponseAnalysis(
            workspace_id=seed.workspace_id,
            audit_id=audit.id,
            task_id=probe.id,
            artifact_id=probe.result_artifact_id,
            analyzer_version="fixture-analysis",
            scoring_rule_version="fixture-rule",
            logical_engine=probe.logical_engine,
            transport_provider=probe.transport_provider,
            transport_model=probe.transport_model,
            prompt_index=0,
            repetition=0,
            shopping_surface=_FIXTURE_SURFACE,
            brand_mentioned=True,
            score={"brand_mentioned": True},
        )
        session.add(probe_brand)
        stored.status = AUDIT_STATUS_COMPLETED
        stored.completed_at = datetime.now(UTC)
        stored.completed_count = 1
        await session.commit()
        probe_id = probe.id

    headers = _headers(seed)
    evidence = await client.get(
        f"/api/v1/projects/{seed.project_id}/visibility/evidence",
        params={"audit_id": str(audit.id)},
        headers=headers,
    )
    export = await client.get(f"/api/v1/audits/{audit.id}/export.csv", headers=headers)
    detail = await client.get(f"/api/v1/executions/{probe_id}", headers=headers)
    assert evidence.status_code == export.status_code == detail.status_code == 200
    assert len(evidence.json()["items"]) == 1
    assert str(probe_id) not in export.text
    assert detail.json()["task_id"] == str(probe_id)


@pytest.mark.asyncio
async def test_executions_queue_and_cancel_paths_do_not_drop_probe_slots(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.config import commerce as commerce_config

    monkeypatch.setattr(
        commerce_config, "SHOPPING_SURFACES", {_FIXTURE_SURFACE: {"label": "Fixture"}}
    )
    seed, _product, _competitor, audit = await _seed_catalog_user_and_audit(
        client, session_factory
    )
    async with session_factory() as session:
        measurement = await session.scalar(
            select(AuditTask).where(AuditTask.audit_id == audit.id)
        )
        assert measurement is not None
        # Let deterministic queue order claim the probe first.
        measurement.randomized_position = 2
        probe = _clone_surface_task(measurement, surface=_FIXTURE_SURFACE)
        probe.randomized_position = 0
        probe.available_at = measurement.available_at - timedelta(seconds=1)
        session.add(probe)
        await session.commit()
        probe_id = probe.id

    queue = PostgresTaskQueue(session_factory, AUDIT_QUEUE_SPEC)
    [claimed] = await queue.claim(owner="surface-worker", limit=1)
    assert claimed.id == probe_id
    assert await queue.cancel(task_id=probe_id)

    headers = _headers(seed)
    default = await client.get(f"/api/v1/audits/{audit.id}/executions", headers=headers)
    explicit = await client.get(
        f"/api/v1/audits/{audit.id}/executions",
        params={"surface": _FIXTURE_SURFACE},
        headers=headers,
    )
    assert default.status_code == explicit.status_code == 200
    assert {row["shopping_surface"] for row in default.json()} == {""}
    assert [row["id"] for row in explicit.json()] == [str(probe_id)]

    # Whole-audit cancellation also terminalizes probe rows; it is intentionally
    # not measurement-filtered.
    async with session_factory() as session:
        measurement = await session.scalar(
            select(AuditTask).where(
                AuditTask.audit_id == audit.id, AuditTask.shopping_surface == ""
            )
        )
        probe = await session.get(AuditTask, probe_id)
        assert measurement is not None and probe is not None
        probe.status = TASK_STATUS_QUEUED
        await session.commit()
        await cancel_audit(session, workspace_id=seed.workspace_id, audit_id=audit.id)
    async with session_factory() as session:
        statuses = set(
            (
                await session.scalars(
                    select(AuditTask.status).where(AuditTask.audit_id == audit.id)
                )
            ).all()
        )
        assert statuses == {TASK_STATUS_CANCELLED}
