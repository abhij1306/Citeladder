"""Atomic projection derivation and terminal success for integration runs."""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.integrations_contracts import (
    ERROR_UNMAPPED_PROPERTY,
    EVENT_INTEGRATION_SYNC_FINISHED,
)
from app.core.config.integrations_transport import INTEGRATION_PROVIDER_SHOPIFY
from app.core.config.task_queue import TASK_STATUS_FAILED, TASK_STATUS_SUCCEEDED
from app.domain.analytics.enqueue import enqueue_post_sync_projections
from app.domain.commerce.derive import derive_shopify_run
from app.domain.integrations.derive import UnmappedPropertyError, derive_run
from app.models.integrations import (
    IntegrationConnection,
    IntegrationEvent,
    IntegrationImportArtifact,
    IntegrationSyncRun,
)
from app.workers.integration.paging import RunContext

ClaimOwnedRun = Callable[
    [AsyncSession, uuid.UUID], Awaitable[IntegrationSyncRun | None]
]


class RunFinalizer:
    """Derive persisted projections and terminalize one still-owned run."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        claim_owned_run: ClaimOwnedRun,
    ) -> None:
        self._session_factory = session_factory
        self._claim_owned_run = claim_owned_run

    async def finalize(self, ctx: RunContext) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            run = await self._claim_owned_run(session, ctx.run_id)
            if run is None:
                return
            artifacts = list(
                (
                    await session.scalars(
                        select(IntegrationImportArtifact)
                        .where(IntegrationImportArtifact.sync_run_id == run.id)
                        .order_by(
                            IntegrationImportArtifact.created_at.asc(),
                            IntegrationImportArtifact.id.asc(),
                        )
                    )
                ).all()
            )
            connection = await session.get(
                IntegrationConnection, ctx.connection_id, with_for_update=True
            )
            if connection is None:
                await session.commit()
                return
            try:
                project_id, artifact_ids, metric_count = await self._derive(
                    session,
                    ctx=ctx,
                    run=run,
                    connection=connection,
                    artifacts=artifacts,
                )
            except UnmappedPropertyError as exc:
                self._fail_unmapped(run, exc, now)
                await session.commit()
                return
            await enqueue_post_sync_projections(
                session,
                project_id=project_id,
                import_artifact_ids=artifact_ids,
            )
            connection.last_synced_at = now
            session.add(
                IntegrationEvent(
                    workspace_id=ctx.workspace_id,
                    connection_id=ctx.connection_id,
                    grant_id=ctx.grant_id,
                    event_type=EVENT_INTEGRATION_SYNC_FINISHED,
                    message=f"Sync finished for {ctx.provider}",
                    payload={
                        "provider": ctx.provider,
                        "sync_run_id": str(ctx.run_id),
                        "sync_kind": ctx.sync_kind,
                        "window_start": ctx.window_start.isoformat(),
                        "window_end": ctx.window_end.isoformat(),
                        "resync_seq": ctx.resync_seq,
                        "project_id": str(project_id),
                        "artifact_ids": [str(value) for value in artifact_ids],
                        "row_count": sum(item.row_count for item in artifacts),
                        "metric_row_count": metric_count,
                    },
                )
            )
            run.status = TASK_STATUS_SUCCEEDED
            run.completed_at = now
            run.error_code = ""
            run.error_detail = ""
            run.lease_owner = None
            run.lease_expires_at = None
            await session.commit()

    @staticmethod
    async def _derive(
        session: AsyncSession,
        *,
        ctx: RunContext,
        run: IntegrationSyncRun,
        connection: IntegrationConnection,
        artifacts: list[IntegrationImportArtifact],
    ) -> tuple[uuid.UUID, tuple[uuid.UUID, ...], int]:
        if ctx.provider == INTEGRATION_PROVIDER_SHOPIFY:
            commerce_derived = await derive_shopify_run(
                session, run=run, connection=connection, artifacts=artifacts
            )
            return commerce_derived.project_id, commerce_derived.artifact_ids, 0
        metric_derived = await derive_run(
            session, run=run, connection=connection, artifacts=artifacts
        )
        return (
            metric_derived.project_id,
            metric_derived.artifact_ids,
            metric_derived.metric_row_count,
        )

    @staticmethod
    def _fail_unmapped(
        run: IntegrationSyncRun, exc: UnmappedPropertyError, now: datetime
    ) -> None:
        run.status = TASK_STATUS_FAILED
        run.completed_at = now
        run.error_code = ERROR_UNMAPPED_PROPERTY
        run.error_detail = str(exc)[:2000]
        run.lease_owner = None
        run.lease_expires_at = None
