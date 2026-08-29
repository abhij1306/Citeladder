# Integration dispatcher: the periodic scheduler for sync runs (I10).
#
# A separate process (the ``integration-dispatcher`` compose service) — one
# lightweight asyncio loop, one owner (the roadmap's first recurring
# scheduler; spec docs/roadmap/integrations.md §4 "Scheduling"). Every
# ``sync_cadence_seconds`` tick it:
#
#   1. enqueues a ``scheduled`` IntegrationSyncRun per ACTIVE connection
#      (its grant is ``connected``) for the default trailing window, via the
#      I5 ``enqueue_sync_run`` service — an ``ActiveWindowConflictError``
#      (the active-window partial unique index) means a run is already in
#      flight and the tick SKIPS it, so a missed/duplicated tick never
#      double-imports a window;
#   2. re-syncs the trailing ``sync_late_data_revision_days`` window so
#      late provider revisions land: once that window's previous run is
#      terminal the enqueue allocates a bumped ``resync_seq`` (new run
#      identity + new immutable artifacts, never an overwrite);
#   3. retries the remote revoke of ``pending_revocation`` grants whose
#      disconnect-time revoke failed (spec §5). Remote revoke exists only
#      where the config pins a revoke URL (Google); a transport without one
#      (Microsoft) resolves locally — tokens dropped, grant ``revoked``.
#
# The dispatcher never touches provider data APIs and never logs a token
# (invariant 6); the decrypted retained token lives only for the revoke call.
from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.integrations import oauth as integration_oauth
from app.core.config.integrations_contracts import (
    ERROR_PROVIDER_API,
    EVENT_INTEGRATION_REVOKE_FAILED,
    EVENT_INTEGRATION_REVOKED,
    GRANT_STATUS_CONNECTED,
    GRANT_STATUS_PENDING_REVOCATION,
    GRANT_STATUS_REVOKED,
    SYNC_KIND_SCHEDULED,
)
from app.core.config.integrations_settings import (
    integration_settings,
)
from app.core.config.integrations_transport import (
    INTEGRATION_OAUTH_REVOKE_URLS,
)
from app.core.database import SessionLocal
from app.core.security import decrypt_secret
from app.core.telemetry import configure_logging, instrument_worker
from app.domain.integrations.errors import IntegrationConnectionNotFoundError
from app.domain.integrations.sync import (
    ActiveWindowConflictError,
    SyncWindowInvalidError,
    enqueue_sync_run,
)
from app.models.integrations import (
    IntegrationConnection,
    IntegrationEvent,
    IntegrationOAuthGrant,
)

logger = logging.getLogger("app.workers.integration_dispatcher")


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True)
class RevokeMaterial:
    workspace_id: uuid.UUID
    transport: str
    revoke_url: str
    token: str


@dataclass(frozen=True)
class RevokeOutcome:
    succeeded: bool
    error_code: str = ""


class IntegrationDispatcher:
    """One-owner periodic loop: scheduled enqueues + revoke retries.

    ``transport`` is the test seam (an ``httpx.MockTransport`` fake OAuth
    server for the revoke retry); production passes none. ``run_once`` is the
    deterministic tick (tests drive it directly); ``run_forever`` sleeps
    ``sync_cadence_seconds`` between ticks.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        owner: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._session_factory = session_factory or SessionLocal
        self._transport = transport
        self.owner = owner or f"integration-dispatcher-{uuid.uuid4().hex[:12]}"

    async def run_once(self, *, today: date | None = None) -> int:
        """One tick. Returns the number of runs enqueued + revokes resolved."""
        enqueued = await self._enqueue_scheduled_runs(today=today)
        resolved = await self._retry_pending_revocations()
        return enqueued + resolved

    async def run_forever(self) -> None:  # pragma: no cover - process loop
        logger.info("integration dispatcher started", extra={"owner": self.owner})
        while True:
            try:
                await self.run_once()
            except Exception:  # defensive: a bad tick must not kill the loop
                logger.exception("integration dispatcher tick failed")
            await asyncio.sleep(max(0.05, integration_settings.sync_cadence_seconds))

    # --- Scheduled sync enqueues -------------------------------------------

    async def _enqueue_scheduled_runs(self, *, today: date | None) -> int:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        IntegrationConnection.id,
                        IntegrationConnection.workspace_id,
                    )
                    .join(
                        IntegrationOAuthGrant,
                        IntegrationConnection.grant_id == IntegrationOAuthGrant.id,
                    )
                    .where(IntegrationOAuthGrant.status == GRANT_STATUS_CONNECTED)
                    .order_by(
                        IntegrationConnection.created_at.asc(),
                        IntegrationConnection.id.asc(),
                    )
                )
            ).all()
        enqueued = 0
        for connection_id, workspace_id in rows:
            enqueued += await self._enqueue_for_connection(
                workspace_id=workspace_id, connection_id=connection_id, today=today
            )
        return enqueued

    async def _try_enqueue(
        self,
        *,
        workspace_id: uuid.UUID,
        connection_id: uuid.UUID,
        label: str,
        window_start: date | None = None,
        window_end: date | None = None,
    ) -> int:
        """One scheduled ``enqueue_sync_run`` attempt: 1 enqueued, 0 skipped.

        An ``ActiveWindowConflictError`` is the dedup contract — an active
        run already covers the window, so the tick skips it; a validation
        failure is logged and skipped.
        """
        async with self._session_factory() as session:
            try:
                await enqueue_sync_run(
                    session,
                    workspace_id=workspace_id,
                    connection_id=connection_id,
                    sync_kind=SYNC_KIND_SCHEDULED,
                    window_start=window_start,
                    window_end=window_end,
                )
                return 1
            except ActiveWindowConflictError:
                return 0
            except (
                IntegrationConnectionNotFoundError,
                SyncWindowInvalidError,
            ) as exc:
                logger.warning("%s skipped: %s", label, exc)
                return 0

    async def _enqueue_for_connection(
        self,
        *,
        workspace_id: uuid.UUID,
        connection_id: uuid.UUID,
        today: date | None,
    ) -> int:
        """Trailing-window run + late-data revision re-sync for one connection.

        Both go through ``enqueue_sync_run`` (the one enqueue entry point).
        """
        enqueued = await self._try_enqueue(
            workspace_id=workspace_id,
            connection_id=connection_id,
            label="scheduled sync enqueue",
        )
        # Late-data revision (spec §4): re-enqueue the trailing
        # ``sync_late_data_revision_days`` window (ends yesterday, the latest
        # complete UTC day — the same rule as the default trailing window).
        # A terminal window re-syncs with a bumped resync_seq; an active one
        # dedups to a skip.
        late_end = (today or _utcnow().date()) - timedelta(days=1)
        late_start = late_end - timedelta(
            days=integration_settings.sync_late_data_revision_days - 1
        )
        enqueued += await self._try_enqueue(
            workspace_id=workspace_id,
            connection_id=connection_id,
            label="late-data revision enqueue",
            window_start=late_start,
            window_end=late_end,
        )
        return enqueued

    # --- pending_revocation retries -----------------------------------------

    async def _retry_pending_revocations(self) -> int:
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(IntegrationOAuthGrant.id)
                    .where(
                        IntegrationOAuthGrant.status == GRANT_STATUS_PENDING_REVOCATION
                    )
                    .order_by(
                        IntegrationOAuthGrant.created_at.asc(),
                        IntegrationOAuthGrant.id.asc(),
                    )
                )
            ).all()
        resolved = 0
        for (grant_id,) in rows:
            if await self._retry_revoke(grant_id):
                resolved += 1
        return resolved

    async def _retry_revoke(self, grant_id: uuid.UUID) -> bool:
        """One grant's revoke retry. True = the grant left pending_revocation.

        Reads + decrypts the retained token in a short transaction (committed
        BEFORE the remote call, invariant 8), then applies the outcome under
        a fresh row lock with a status re-check so a concurrent resolution
        (another tick, a later manual path) is never clobbered.
        """
        material = await self._load_revoke_material(grant_id)
        if material is None:
            return False
        outcome = await self._revoke_remote(material)
        return await self._persist_revoke_outcome(grant_id, material, outcome)

    async def _load_revoke_material(self, grant_id: uuid.UUID) -> RevokeMaterial | None:
        async with self._session_factory() as session:
            grant = await session.get(IntegrationOAuthGrant, grant_id)
            if grant is None or grant.status != GRANT_STATUS_PENDING_REVOCATION:
                return None
            revoke_url = INTEGRATION_OAUTH_REVOKE_URLS[grant.transport]
            token = ""
            if revoke_url:
                try:
                    token = decrypt_secret(
                        grant.refresh_token_encrypted or grant.access_token_encrypted
                    )
                except Exception:  # noqa: BLE001 - undecryptable: resolve locally
                    logger.warning(
                        "revoke token undecryptable; resolving grant locally",
                        extra={"grant_id": str(grant_id)},
                    )
            return RevokeMaterial(
                workspace_id=grant.workspace_id,
                transport=grant.transport,
                revoke_url=revoke_url,
                token=token,
            )

    async def _revoke_remote(self, material: RevokeMaterial) -> RevokeOutcome:
        if not material.revoke_url or not material.token:
            return RevokeOutcome(succeeded=True)
        client = integration_oauth.build_oauth_client(
            material.transport, transport=self._transport
        )
        try:
            await client.revoke(token=material.token)
        except integration_oauth.IntegrationOAuthError as exc:
            return RevokeOutcome(succeeded=False, error_code=exc.error_code)
        except Exception:  # noqa: BLE001 - any transport fault = failed revoke
            return RevokeOutcome(succeeded=False, error_code=ERROR_PROVIDER_API)
        return RevokeOutcome(succeeded=True)

    async def _persist_revoke_outcome(
        self,
        grant_id: uuid.UUID,
        material: RevokeMaterial,
        outcome: RevokeOutcome,
    ) -> bool:
        async with self._session_factory() as session:
            grant = await session.get(
                IntegrationOAuthGrant, grant_id, with_for_update=True
            )
            if grant is None or grant.status != GRANT_STATUS_PENDING_REVOCATION:
                await session.commit()  # resolved concurrently; nothing staged
                return False
            if outcome.succeeded:
                grant.status = GRANT_STATUS_REVOKED
                grant.access_token_encrypted = ""
                grant.refresh_token_encrypted = ""
                grant.token_expires_at = None
                session.add(
                    IntegrationEvent(
                        workspace_id=material.workspace_id,
                        grant_id=grant_id,
                        event_type=EVENT_INTEGRATION_REVOKED,
                        message=(
                            "Grant revoked at provider (dispatcher retry)"
                            if material.revoke_url and material.token
                            else "Grant revoked locally (no remote revoke possible)"
                        ),
                        payload={
                            "transport": material.transport,
                            "remote_revoke": bool(
                                material.revoke_url and material.token
                            ),
                            "dispatcher": self.owner,
                        },
                    )
                )
            else:
                # Tokens stay retained for the next tick (spec §5).
                session.add(
                    IntegrationEvent(
                        workspace_id=material.workspace_id,
                        grant_id=grant_id,
                        event_type=EVENT_INTEGRATION_REVOKE_FAILED,
                        message="Remote revoke retry failed; tokens retained",
                        payload={
                            "transport": material.transport,
                            "error_code": outcome.error_code,
                            "dispatcher": self.owner,
                        },
                    )
                )
            await session.commit()
            return outcome.succeeded


def main() -> None:  # pragma: no cover - process entrypoint
    configure_logging()
    instrument_worker("integration-dispatcher")
    dispatcher = IntegrationDispatcher()
    asyncio.run(dispatcher.run_forever())


if __name__ == "__main__":  # pragma: no cover
    main()
