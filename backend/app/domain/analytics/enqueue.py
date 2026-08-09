# Analytics enqueue service (invariant 8): the C5 post-sync hook plus the
# per-kind enqueue helpers with deterministic idempotency keys.
#
# ``enqueue_post_sync_projections`` is the hook the integrations worker calls
# after derivation (contract C5). It is DATASET-AWARE: each fresh artifact
# routes by its dataset id to the projection chains that consume it —
# referral-dimension artifacts enqueue ``ingest_referrals`` (the referral
# chain's first task; the executors chain ``classify_referrals`` and
# ``analytics_snapshot_refresh`` on completion), traffic-consumed artifacts
# trigger one ``traffic_snapshot_refresh`` per distinct affected sync
# window, and the GA4 ecommerce artifacts trigger one
# ``attribution_snapshot`` refresh per distinct affected window (WS-B A1).
# The mapping is additive and many-to-many (``ga4_source_medium_daily``
# feeds BOTH referral ingest and the traffic refresh); a dataset consumed
# by no projection chain enqueues nothing.
#
# Every helper builds a DETERMINISTIC idempotency key from the kind plus the
# project/artifact/window identity, and inserts ``ON CONFLICT DO NOTHING`` on
# the unique ``idempotency_key`` — a re-enqueue of the same logical task is a
# no-op (returns ``None``), never a duplicate queue row (invariant 8).
from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date

from sqlalchemy import Integer, cast, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.analytics import (
    AI_REFERRAL_RULE_VERSION,
    ANALYTICS_TASK_KIND_ANALYTICS_SNAPSHOT_REFRESH,
    ANALYTICS_TASK_KIND_ATTRIBUTION_LINK,
    ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT,
    ANALYTICS_TASK_KIND_CLASSIFY_REFERRALS,
    ANALYTICS_TASK_KIND_DEMAND_SNAPSHOT_REFRESH,
    ANALYTICS_TASK_KIND_INGEST_REFERRALS,
    ANALYTICS_TASK_KIND_ORDER_RETENTION_SWEEP,
    ANALYTICS_TASK_KIND_REFERRAL_RETENTION_SWEEP,
    ANALYTICS_TASK_KIND_TRAFFIC_SNAPSHOT_REFRESH,
    analytics_settings,
)
from app.core.config.attribution import (
    ATTRIBUTION_ANALYZER_VERSION,
    ATTRIBUTION_CONSUMED_DATASETS,
)
from app.core.config.integrations import DATASET_SHOPIFY_ORDERS
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.core.config.traffic import (
    TRAFFIC_GA4_REFERRAL_DATASETS,
    TRAFFIC_REFRESH_TRIGGER_DATASETS,
)
from app.models.analytics import AnalyticsTask
from app.models.integrations import IntegrationImportArtifact, IntegrationSyncRun
from app.models.project import Project


def _idempotency_key(task_kind: str, *parts: object) -> str:
    """Deterministic queue-row identity: kind + project/artifact/window.

    Fits the 160-char column un-hashed (kind <= 26 chars + UUIDs / ISO
    dates), keeping the key debuggable (site_health ``_task_idempotency_key``
    precedent).
    """
    return ":".join(("analytics", task_kind, *(str(part) for part in parts)))


async def _enqueue_task(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID | None,
    task_kind: str,
    payload: dict,
    idempotency_key: str,
    priority: int = 0,
) -> uuid.UUID | None:
    """Enqueue one queue row conflict-safely (returns id, or None if it existed).

    The unique ``idempotency_key`` plus ``ON CONFLICT DO NOTHING`` mean a
    re-enqueue of the same logical task never double-enqueues.
    """
    stmt = (
        pg_insert(AnalyticsTask)
        .values(
            workspace_id=workspace_id,
            project_id=project_id,
            task_kind=task_kind,
            payload=payload,
            idempotency_key=idempotency_key,
            status=TASK_STATUS_QUEUED,
            priority=priority,
            max_attempts=analytics_settings.task_max_attempts,
        )
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(AnalyticsTask.id)
    )
    return await session.scalar(stmt)


# --- Per-kind helpers (the worker executors chain through these) -------------


async def enqueue_ingest_referrals(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    import_artifact_id: uuid.UUID,
    priority: int = 0,
) -> uuid.UUID | None:
    """Enqueue the referral chain's first task for one import artifact (A5)."""
    return await _enqueue_task(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        task_kind=ANALYTICS_TASK_KIND_INGEST_REFERRALS,
        payload={"import_artifact_id": str(import_artifact_id)},
        idempotency_key=_idempotency_key(
            ANALYTICS_TASK_KIND_INGEST_REFERRALS, project_id, import_artifact_id
        ),
        priority=priority,
    )


async def enqueue_classify_referrals(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    import_artifact_id: uuid.UUID,
    priority: int = 0,
) -> uuid.UUID | None:
    """Enqueue classification of the events one artifact ingested (A6)."""
    return await _enqueue_task(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        task_kind=ANALYTICS_TASK_KIND_CLASSIFY_REFERRALS,
        payload={"import_artifact_id": str(import_artifact_id)},
        idempotency_key=_idempotency_key(
            ANALYTICS_TASK_KIND_CLASSIFY_REFERRALS, project_id, import_artifact_id
        ),
        priority=priority,
    )


async def _enqueue_window_snapshot_refresh(
    session: AsyncSession,
    *,
    task_kind: str,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
    resync_seq: int,
    source_revision: str | None = None,
    priority: int = 0,
) -> uuid.UUID | None:
    """The shared body of the two window snapshot-refresh enqueues (A7/A8).

    The payload is window-level; the executor expands the configured
    snapshot granularities. The idempotency key carries the triggering
    data revision (``resync_seq``) so a re-sync of an already-projected
    window re-fires the refresh while a same-revision duplicate still
    dedupes.
    """
    payload = _window_refresh_payload(
        task_kind=task_kind,
        window_start=window_start,
        window_end=window_end,
        resync_seq=resync_seq,
        source_revision=source_revision,
    )
    revision_parts = [source_revision] if source_revision is not None else []
    return await _enqueue_task(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        task_kind=task_kind,
        payload=payload,
        idempotency_key=_idempotency_key(
            task_kind,
            project_id,
            window_start,
            window_end,
            resync_seq,
            *revision_parts,
        ),
        priority=priority,
    )


def _window_refresh_payload(
    *,
    task_kind: str,
    window_start: date,
    window_end: date,
    resync_seq: int,
    source_revision: str | None,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
    }
    if source_revision is not None:
        payload["source_revision"] = source_revision
    if task_kind == ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT:
        payload["resync_seq"] = resync_seq
    return payload


async def enqueue_traffic_snapshot_refresh(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
    resync_seq: int,
    source_revision: str | None = None,
    priority: int = 0,
) -> uuid.UUID | None:
    """Enqueue a rebuild of the Traffic snapshot rows for one window (A7).

    The executor expands ``TRAFFIC_SNAPSHOT_GRANULARITIES``; the
    revision-keyed dedupe rule is documented on
    ``_enqueue_window_snapshot_refresh``.
    """
    return await _enqueue_window_snapshot_refresh(
        session,
        task_kind=ANALYTICS_TASK_KIND_TRAFFIC_SNAPSHOT_REFRESH,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
        resync_seq=resync_seq,
        source_revision=source_revision,
        priority=priority,
    )


async def enqueue_analytics_snapshot_refresh(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
    resync_seq: int,
    source_revision: str | None = None,
    priority: int = 0,
) -> uuid.UUID | None:
    """Enqueue a rebuild of the LLM-Analytics snapshot for one window (A8).

    The executor expands ``ANALYTICS_SNAPSHOT_GRANULARITIES``; the
    revision-keyed dedupe rule is documented on
    ``_enqueue_window_snapshot_refresh``.
    """
    return await _enqueue_window_snapshot_refresh(
        session,
        task_kind=ANALYTICS_TASK_KIND_ANALYTICS_SNAPSHOT_REFRESH,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
        resync_seq=resync_seq,
        source_revision=source_revision,
        priority=priority,
    )


async def enqueue_demand_snapshot_refresh(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
    source_revision: str,
    priority: int = 0,
) -> uuid.UUID | None:
    """Queue one immutable Demand interpretation for an evidence revision."""
    revision = source_revision[:24]
    return await _enqueue_window_snapshot_refresh(
        session,
        task_kind=ANALYTICS_TASK_KIND_DEMAND_SNAPSHOT_REFRESH,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
        resync_seq=0,
        source_revision=revision,
        priority=priority,
    )


async def enqueue_attribution_snapshot_refresh(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
    resync_seq: int,
    source_revision: str | None = None,
    priority: int = 0,
) -> uuid.UUID | None:
    """Enqueue a rebuild of the attribution snapshot rows for one window.

    The A1 projection refresh (WS-B Task 1): the executor expands
    ``ANALYTICS_SNAPSHOT_GRANULARITIES``; the revision-keyed dedupe rule is
    documented on ``_enqueue_window_snapshot_refresh``.
    """
    payload: dict[str, object] = {
        "window_start": window_start.isoformat(),
        "window_end": window_end.isoformat(),
        "resync_seq": resync_seq,
    }
    return await _enqueue_task(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        task_kind=ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT,
        payload=payload,
        idempotency_key=_idempotency_key(
            ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT,
            project_id,
            window_start,
            window_end,
            resync_seq,
            *([source_revision] if source_revision is not None else []),
        ),
        priority=priority,
    )


async def enqueue_attribution_recompute(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    window_start: date,
    window_end: date,
    priority: int = 0,
) -> uuid.UUID:
    """Allocate and enqueue a fresh manual attribution projection revision.

    The project row lock serializes revision allocation across automatic and
    manual snapshot tasks. The revision lives on the durable task payload,
    not an integration run or mutable snapshot row.
    """
    project = await session.scalar(
        select(Project)
        .where(Project.id == project_id, Project.workspace_id == workspace_id)
        .with_for_update()
    )
    if project is None:
        raise ValueError(f"unknown project: {project_id}")

    window_start_text = window_start.isoformat()
    window_end_text = window_end.isoformat()
    max_revision = await session.scalar(
        select(func.max(cast(AnalyticsTask.payload["resync_seq"].astext, Integer)))
        .where(AnalyticsTask.workspace_id == workspace_id)
        .where(AnalyticsTask.project_id == project_id)
        .where(AnalyticsTask.task_kind == ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT)
        .where(AnalyticsTask.payload["window_start"].astext == window_start_text)
        .where(AnalyticsTask.payload["window_end"].astext == window_end_text)
    )
    resync_seq = (max_revision if max_revision is not None else -1) + 1
    task_id = await enqueue_attribution_snapshot_refresh(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        window_start=window_start,
        window_end=window_end,
        resync_seq=resync_seq,
        priority=priority,
    )
    if task_id is not None:
        return task_id

    # Defensive idempotency-race fallback: always return the pollable row.
    existing_id = await session.scalar(
        select(AnalyticsTask.id)
        .where(AnalyticsTask.workspace_id == workspace_id)
        .where(AnalyticsTask.project_id == project_id)
        .where(AnalyticsTask.task_kind == ANALYTICS_TASK_KIND_ATTRIBUTION_SNAPSHOT)
        .where(AnalyticsTask.payload["window_start"].astext == window_start_text)
        .where(AnalyticsTask.payload["window_end"].astext == window_end_text)
        .where(AnalyticsTask.payload["resync_seq"].astext == str(resync_seq))
        .order_by(AnalyticsTask.created_at.desc(), AnalyticsTask.id.desc())
    )
    if existing_id is None:
        raise RuntimeError("attribution recompute enqueue lost without a durable task")
    return existing_id


async def enqueue_attribution_link(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
    sync_run_id: uuid.UUID,
    rule_version: str = AI_REFERRAL_RULE_VERSION,
    priority: int = 0,
) -> uuid.UUID | None:
    """Enqueue deterministic links for the latest order facts of one sync run."""
    return await _enqueue_task(
        session,
        workspace_id=workspace_id,
        project_id=project_id,
        task_kind=ANALYTICS_TASK_KIND_ATTRIBUTION_LINK,
        payload={"sync_run_id": str(sync_run_id), "rule_version": rule_version},
        idempotency_key=_idempotency_key(
            ANALYTICS_TASK_KIND_ATTRIBUTION_LINK,
            project_id,
            sync_run_id,
            rule_version,
            ATTRIBUTION_ANALYZER_VERSION,
        ),
        priority=priority,
    )


async def enqueue_referral_retention_sweep(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    sweep_key: str,
    priority: int = 0,
) -> uuid.UUID | None:
    """Enqueue one workspace-scoped retention sweep (A6).

    ``sweep_key`` is the caller-chosen period token (e.g. an ISO date) that
    makes the sweep deterministic per period — at most one sweep row per
    ``(workspace_id, sweep_key)`` is ever queued.
    """
    return await _enqueue_task(
        session,
        workspace_id=workspace_id,
        project_id=None,
        task_kind=ANALYTICS_TASK_KIND_REFERRAL_RETENTION_SWEEP,
        payload={"sweep_key": sweep_key},
        idempotency_key=_idempotency_key(
            ANALYTICS_TASK_KIND_REFERRAL_RETENTION_SWEEP, workspace_id, sweep_key
        ),
        priority=priority,
    )


async def enqueue_order_retention_sweep(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    sweep_key: str,
    priority: int = 0,
) -> uuid.UUID | None:
    """Enqueue one workspace-scoped order retention sweep (commerce suite).

    Mirrors the referral sweep contract: ``sweep_key`` is the caller-chosen
    period token making the sweep deterministic per period — at most one
    sweep row per ``(workspace_id, sweep_key)`` is ever queued.
    """
    return await _enqueue_task(
        session,
        workspace_id=workspace_id,
        project_id=None,
        task_kind=ANALYTICS_TASK_KIND_ORDER_RETENTION_SWEEP,
        payload={"sweep_key": sweep_key},
        idempotency_key=_idempotency_key(
            ANALYTICS_TASK_KIND_ORDER_RETENTION_SWEEP, workspace_id, sweep_key
        ),
        priority=priority,
    )


# --- C5 post-sync hook (called by the integrations worker after derivation) --


async def enqueue_post_sync_projections(
    session: AsyncSession,
    *,
    project_id: uuid.UUID,
    import_artifact_ids: Iterable[uuid.UUID],
) -> list[uuid.UUID]:
    """Enqueue the analytics projection chains for freshly derived artifacts.

    DATASET-AWARE routing (each artifact routes to exactly the chains that
    consume its dataset; the mapping is additive and many-to-many):

    - ``TRAFFIC_GA4_REFERRAL_DATASETS`` (``ga4_referrer_daily``,
      ``ga4_source_medium_daily``) → one ``ingest_referrals`` task per
      artifact (the referral chain's first link; the executors chain
      ``classify_referrals`` and ``analytics_snapshot_refresh`` on
      completion).
    - ``TRAFFIC_REFRESH_TRIGGER_DATASETS`` (the traffic-consumed read set
      plus the Bing dailies) → one ``traffic_snapshot_refresh`` per
      distinct affected (sync window, ``resync_seq``) revision (C5).
      ``ga4_source_medium_daily`` keeps BOTH this trigger and referral
      ingest.
    - ``ATTRIBUTION_CONSUMED_DATASETS`` (the three GA4 ecommerce datasets)
      → one ``attribution_snapshot`` refresh per distinct affected
      (window, revision) — and NOTHING else (they are not referral, not
      traffic).
    - A dataset consumed by no projection chain (e.g. the future Shopify
      datasets, which enqueue through their own derive path) triggers
      nothing here.

    The refresh idempotency keys carry the triggering run's data revision
    so a re-sync of an already-projected window re-fires the refresh
    instead of deduping away.

    Artifact ids are resolved scoped to the project's workspace — an id that
    does not resolve there (unknown or cross-workspace) is skipped, never
    enqueued (invariant 5). Returns the ids of the newly inserted queue rows
    (deduplicated re-calls return fewer or no ids).
    """
    artifact_ids = list(dict.fromkeys(import_artifact_ids))
    if not artifact_ids:
        return []

    project = await session.get(Project, project_id)
    if project is None:
        raise ValueError(f"unknown project: {project_id}")
    workspace_id = project.workspace_id

    rows = (
        await session.execute(
            select(
                IntegrationImportArtifact.id,
                IntegrationImportArtifact.dataset,
                IntegrationImportArtifact.sync_run_id,
                IntegrationSyncRun.window_start,
                IntegrationSyncRun.window_end,
                IntegrationSyncRun.resync_seq,
            )
            .join(
                IntegrationSyncRun,
                IntegrationImportArtifact.sync_run_id == IntegrationSyncRun.id,
            )
            .where(IntegrationImportArtifact.workspace_id == workspace_id)
            .where(IntegrationImportArtifact.id.in_(artifact_ids))
        )
    ).all()
    resolved = {row.id: row for row in rows}
    # One refresh per DISTINCT affected (window, data revision) PER chain,
    # deduped in first-seen order of the returned rows (the SELECT has no
    # ORDER BY; a hook call normally carries one run's artifacts — one
    # window at one resync_seq — so ordering is moot in practice).
    traffic_revisions: dict[tuple[date, date, int, uuid.UUID], None] = {}
    attribution_revisions: dict[tuple[date, date, int, uuid.UUID], None] = {}
    order_sync_runs: dict[uuid.UUID, None] = {}
    for row in rows:
        revision = (row.window_start, row.window_end, row.resync_seq)
        if row.dataset in TRAFFIC_REFRESH_TRIGGER_DATASETS:
            traffic_revisions.setdefault((*revision, row.sync_run_id))
        if row.dataset in ATTRIBUTION_CONSUMED_DATASETS:
            attribution_revisions.setdefault((*revision, row.sync_run_id))
        if row.dataset == DATASET_SHOPIFY_ORDERS:
            order_sync_runs.setdefault(row.sync_run_id)

    enqueued: list[uuid.UUID] = []
    for artifact_id in artifact_ids:
        resolved_row = resolved.get(artifact_id)
        if (
            resolved_row is None
            or resolved_row.dataset not in TRAFFIC_GA4_REFERRAL_DATASETS
        ):
            continue
        task_id = await enqueue_ingest_referrals(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            import_artifact_id=artifact_id,
        )
        if task_id is not None:
            enqueued.append(task_id)
    for window_start, window_end, resync_seq, sync_run_id in traffic_revisions:
        task_id = await enqueue_traffic_snapshot_refresh(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            window_start=window_start,
            window_end=window_end,
            resync_seq=resync_seq,
            source_revision=str(sync_run_id),
        )
        if task_id is not None:
            enqueued.append(task_id)
    for window_start, window_end, resync_seq, sync_run_id in attribution_revisions:
        task_id = await enqueue_attribution_snapshot_refresh(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            window_start=window_start,
            window_end=window_end,
            resync_seq=resync_seq,
            source_revision=str(sync_run_id),
        )
        if task_id is not None:
            enqueued.append(task_id)
    for sync_run_id in order_sync_runs:
        task_id = await enqueue_attribution_link(
            session,
            workspace_id=workspace_id,
            project_id=project_id,
            sync_run_id=sync_run_id,
        )
        if task_id is not None:
            enqueued.append(task_id)
    return enqueued
