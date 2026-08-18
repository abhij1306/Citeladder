"""Persistence and provenance tests for canonical AI-referral snapshots."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, time

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.analytics import (
    AI_REFERRAL_ANALYZER_VERSION,
    AI_REFERRAL_FORMULA_VERSION,
    AI_SOURCE_CHATGPT,
    AI_SOURCE_GEMINI,
    AI_SOURCE_OTHER,
    AI_SOURCE_PERPLEXITY,
)
from app.core.config.integrations_datasets import (
    DATASET_GA4_REFERRER_DAILY,
    DATASET_GA4_SOURCE_MEDIUM_DAILY,
)
from app.core.config.task_queue import TASK_STATUS_CANCELLED, TASK_STATUS_SUCCEEDED
from app.domain.analytics import ai_referrals_snapshot as snapshot_module
from app.domain.analytics.ai_referrals_snapshot import refresh_ai_referrals_snapshot
from app.domain.analytics.enqueue import enqueue_ai_referrals_snapshot_refresh
from app.domain.analytics.tasks import TaskCancelledError
from app.models.analytics import AiReferralsSnapshot, AnalyticsTask
from app.models.integrations import IntegrationConnection
from app.workers.analytics_worker import AnalyticsWorker
from tests.component.analytics_helpers import (
    DEFAULT_WINDOW,
    seed_ga4_import,
    seed_metric_row,
    seed_referral_classification,
    seed_referral_event,
    seed_workspace_project,
)

WINDOW = DEFAULT_WINDOW


def _occurred(day: date) -> datetime:
    return datetime.combine(day, time.min, tzinfo=UTC)


async def _classified_row(
    session: AsyncSession,
    *,
    seed,
    key: str,
    row_date: date,
    source: str,
    medium: str,
    sessions: int,
    is_ai: bool,
    ai_source: str,
    resync_seq: int = 0,
):
    row = await seed_metric_row(
        session,
        seed=seed,
        row_date=row_date,
        dimension_values=[source, medium, row_date.strftime("%Y%m%d")],
        metrics={"sessions": sessions},
        resync_seq=resync_seq,
    )
    event = await seed_referral_event(
        session,
        seed=seed,
        occurred_at=_occurred(row_date),
        utm_source=source,
        utm_medium=medium,
        source_metric_row_id=row.id,
    )
    classification = await seed_referral_classification(
        session,
        event=event,
        is_ai_referral=is_ai,
        ai_source=ai_source,
        matched_rule_id=f"{key}-rule" if is_ai else "",
    )
    return row, classification


async def _seed_canonical_chain(
    session: AsyncSession, *, workspace_id: uuid.UUID, project_id: uuid.UUID
) -> dict[str, object]:
    seed = await seed_ga4_import(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        dataset=DATASET_GA4_SOURCE_MEDIUM_DAILY,
    )
    classifications = []
    for values in (
        (
            "chatgpt",
            date(2026, 7, 20),
            "chatgpt.com",
            "referral",
            4,
            True,
            AI_SOURCE_CHATGPT,
        ),
        (
            "gemini",
            date(2026, 7, 21),
            "gemini.google.com",
            "referral",
            1,
            True,
            AI_SOURCE_GEMINI,
        ),
        ("other", date(2026, 7, 21), "google", "organic", 6, False, AI_SOURCE_OTHER),
        (
            "perplexity",
            date(2026, 7, 22),
            "perplexity.ai",
            "referral",
            2,
            True,
            AI_SOURCE_PERPLEXITY,
        ),
    ):
        _, classification = await _classified_row(
            session,
            seed=seed,
            key=values[0],
            row_date=values[1],
            source=values[2],
            medium=values[3],
            sessions=values[4],
            is_ai=values[5],
            ai_source=values[6],
        )
        classifications.append(classification)

    # An overlapping referrer-report fact remains immutable provenance, but
    # never enters canonical session sums.
    connection = await session.get(IntegrationConnection, seed.connection_id)
    assert connection is not None
    referrer_seed = await seed_ga4_import(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        dataset=DATASET_GA4_REFERRER_DAILY,
        connection=connection,
        resync_seq=1,
    )
    overlap = await seed_metric_row(
        session,
        seed=referrer_seed,
        row_date=date(2026, 7, 20),
        dimension_values=["https://chatgpt.com/c/abc", "20260720"],
        metrics={"sessions": 100},
    )
    overlap_event = await seed_referral_event(
        session,
        seed=referrer_seed,
        occurred_at=_occurred(date(2026, 7, 20)),
        referrer_url="https://chatgpt.com/c/abc",
        source_metric_row_id=overlap.id,
    )
    await seed_referral_classification(
        session,
        event=overlap_event,
        is_ai_referral=True,
        ai_source=AI_SOURCE_CHATGPT,
    )
    await session.commit()
    return {"seed": seed, "classification_ids": [row.id for row in classifications]}


async def _enqueue(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> AnalyticsTask:
    async with session_factory() as session:
        task_id = await enqueue_ai_referrals_snapshot_refresh(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            window_start=WINDOW[0],
            window_end=WINDOW[1],
            resync_seq=0,
        )
        await session.commit()
    assert task_id is not None
    async with session_factory() as session:
        task = await session.get(AnalyticsTask, task_id)
    assert task is not None
    return task


async def _snapshots(session: AsyncSession) -> dict[str, AiReferralsSnapshot]:
    rows = list((await session.scalars(select(AiReferralsSnapshot))).all())
    return {row.granularity: row for row in rows}


@pytest.mark.asyncio
async def test_refresh_builds_canonical_buckets_without_referrer_double_counting(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        workspace_id, project_id = await seed_workspace_project(session)
        evidence = await _seed_canonical_chain(
            session, workspace_id=workspace_id, project_id=project_id
        )
    task = await _enqueue(
        session_factory, workspace_id=workspace_id, project_id=project_id
    )

    await refresh_ai_referrals_snapshot(session_factory, task)

    async with session_factory() as session:
        snapshots = await _snapshots(session)
        assert set(snapshots) == {"day", "week", "month"}
        day = snapshots["day"]
        assert day.analyzer_version == AI_REFERRAL_ANALYZER_VERSION
        assert day.formula_version == AI_REFERRAL_FORMULA_VERSION
        assert [point["value"] for point in day.metrics["referral_volume"]] == [4, 1, 2]
        assert day.metrics["referral_share"][0]["value"] == pytest.approx(1.0)
        assert day.metrics["referral_share"][1]["value"] == pytest.approx(1 / 7)
        assert day.metrics["sources"] == [
            {
                "ai_source": AI_SOURCE_CHATGPT,
                "sessions": 4,
                "share": pytest.approx(4 / 13),
            },
            {
                "ai_source": AI_SOURCE_PERPLEXITY,
                "sessions": 2,
                "share": pytest.approx(2 / 13),
            },
            {
                "ai_source": AI_SOURCE_GEMINI,
                "sessions": 1,
                "share": pytest.approx(1 / 13),
            },
        ]
        assert set(day.source_classification_ids or []) == {
            str(identifier) for identifier in evidence["classification_ids"]
        }
        for granularity in ("week", "month"):
            assert snapshots[granularity].metrics["referral_volume"] == [
                {"date": "2026-07-20", "value": 7}
            ]


@pytest.mark.asyncio
async def test_missing_canonical_classification_is_unmeasured(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        workspace_id, project_id = await seed_workspace_project(session)
        seed = await seed_ga4_import(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            dataset=DATASET_GA4_SOURCE_MEDIUM_DAILY,
        )
        await seed_metric_row(
            session,
            seed=seed,
            row_date=WINDOW[0],
            dimension_values=["chatgpt.com", "referral", "20260720"],
            metrics={"sessions": 4},
        )
        await session.commit()
    task = await _enqueue(
        session_factory, workspace_id=workspace_id, project_id=project_id
    )
    await refresh_ai_referrals_snapshot(session_factory, task)
    async with session_factory() as session:
        day = (await _snapshots(session))["day"]
        assert day.metrics["referral_volume"][0]["value"] is None
        assert day.metrics["referral_share"][0]["value"] is None
        assert day.metrics["sources"] == []


@pytest.mark.asyncio
async def test_refresh_upsert_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        workspace_id, project_id = await seed_workspace_project(session)
        await _seed_canonical_chain(
            session, workspace_id=workspace_id, project_id=project_id
        )
    task = await _enqueue(
        session_factory, workspace_id=workspace_id, project_id=project_id
    )
    await refresh_ai_referrals_snapshot(session_factory, task)
    async with session_factory() as session:
        first = await _snapshots(session)
        first_ids = {key: row.id for key, row in first.items()}
    await refresh_ai_referrals_snapshot(session_factory, task)
    async with session_factory() as session:
        second = await _snapshots(session)
        assert {key: row.id for key, row in second.items()} == first_ids
        assert await session.scalar(select(func.count(AiReferralsSnapshot.id))) == 3


@pytest.mark.asyncio
async def test_refresh_reads_only_latest_resync_revision(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        workspace_id, project_id = await seed_workspace_project(session)
        seed = await seed_ga4_import(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            dataset=DATASET_GA4_SOURCE_MEDIUM_DAILY,
        )
        stale, stale_classification = await _classified_row(
            session,
            seed=seed,
            key="stale",
            row_date=WINDOW[0],
            source="chatgpt.com",
            medium="referral",
            sessions=5,
            is_ai=True,
            ai_source=AI_SOURCE_CHATGPT,
        )
        fresh, fresh_classification = await _classified_row(
            session,
            seed=seed,
            key="fresh",
            row_date=WINDOW[0],
            source="chatgpt.com",
            medium="referral",
            sessions=9,
            is_ai=True,
            ai_source=AI_SOURCE_CHATGPT,
            resync_seq=1,
        )
        assert stale.dimension_key == fresh.dimension_key
        await session.commit()
    task = await _enqueue(
        session_factory, workspace_id=workspace_id, project_id=project_id
    )
    await refresh_ai_referrals_snapshot(session_factory, task)
    async with session_factory() as session:
        day = (await _snapshots(session))["day"]
        assert day.metrics["referral_volume"][0]["value"] == 9
        assert day.source_classification_ids == [str(fresh_classification.id)]
        assert str(stale_classification.id) not in day.source_classification_ids


@pytest.mark.asyncio
async def test_refresh_honors_cancel_at_metric_batch_boundary(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with session_factory() as session:
        workspace_id, project_id = await seed_workspace_project(session)
        await _seed_canonical_chain(
            session, workspace_id=workspace_id, project_id=project_id
        )
    task = await _enqueue(
        session_factory, workspace_id=workspace_id, project_id=project_id
    )
    monkeypatch.setattr(snapshot_module, "_CLASSIFICATION_BATCH_SIZE", 1)
    real_check = snapshot_module._raise_if_task_terminal
    checks = 0

    async def cancel_on_second(factory, row_id):
        nonlocal checks
        checks += 1
        if checks == 2:
            async with factory() as session:
                row = await session.get(AnalyticsTask, row_id)
                assert row is not None
                row.status = TASK_STATUS_CANCELLED
                await session.commit()
        await real_check(factory, row_id)

    monkeypatch.setattr(snapshot_module, "_raise_if_task_terminal", cancel_on_second)
    with pytest.raises(TaskCancelledError):
        await refresh_ai_referrals_snapshot(session_factory, task)
    async with session_factory() as session:
        assert await session.scalar(select(func.count(AiReferralsSnapshot.id))) == 0


@pytest.mark.asyncio
async def test_worker_routes_snapshot_refresh(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        workspace_id, project_id = await seed_workspace_project(session)
        await _seed_canonical_chain(
            session, workspace_id=workspace_id, project_id=project_id
        )
        task_id = await enqueue_ai_referrals_snapshot_refresh(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            window_start=WINDOW[0],
            window_end=WINDOW[1],
            resync_seq=0,
        )
        await session.commit()
    worker = AnalyticsWorker(session_factory=session_factory, owner="snapshot-test")
    assert await worker.run_until_idle() == 1
    async with session_factory() as session:
        row = await session.get(AnalyticsTask, task_id)
        assert row is not None
        assert row.status == TASK_STATUS_SUCCEEDED
        assert await session.scalar(select(func.count(AiReferralsSnapshot.id))) == 3


@pytest.mark.asyncio
async def test_refresh_rejects_invalid_payload_and_project(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    workspace_id, project_id = uuid.uuid4(), uuid.uuid4()

    def task(payload: dict, *, with_project: bool = True) -> AnalyticsTask:
        return AnalyticsTask(
            workspace_id=workspace_id,
            project_id=project_id if with_project else None,
            task_kind="ai_referrals_snapshot_refresh",
            payload=payload,
            idempotency_key=uuid.uuid4().hex,
        )

    missing_project = task({}, with_project=False)
    missing_window = task({})
    reversed_window = task({"window_start": "2026-07-22", "window_end": "2026-07-20"})

    with pytest.raises(ValueError, match="project_id"):
        await refresh_ai_referrals_snapshot(session_factory, missing_project)
    with pytest.raises(ValueError, match="window_start"):
        await refresh_ai_referrals_snapshot(session_factory, missing_window)
    with pytest.raises(ValueError, match="window_end before window_start"):
        await refresh_ai_referrals_snapshot(session_factory, reversed_window)
