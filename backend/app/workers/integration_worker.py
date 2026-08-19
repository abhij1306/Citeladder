# Integration sync worker: claims IntegrationSyncRun queue rows and pages the
# provider data APIs (GSC / GA4 / Bing) behind the config-owned dispatch
# registry (``INTEGRATION_CLIENT_BUILDERS`` — the ``_build_client`` seam).
#
# A separate process (the ``integration-worker`` compose service). It mirrors
# ``ContentWorker`` exactly on the queue mechanics — claim via the generic
# ``PostgresTaskQueue`` (``FOR UPDATE SKIP LOCKED``, claim committed BEFORE
# any network I/O — invariant 8), sweep expired leases FIRST in every loop
# iteration, ``mark_running`` before provider I/O, and heartbeat the lease
# while a long backfill pages. Cooperative cancel at the page boundary
# (invariant 9): the worker stops BEFORE the next provider call.
#
# Per claimed run (spec docs/roadmap/integrations.md §4):
#   1. begin the attempt (bump ``attempt_count``, append sync_started event);
#   2. resolve + decrypt the grant token, refreshing it when near expiry via
#      the SERIALIZED-PER-GRANT rotation (spec §2 — ``integration.tokens``);
#   3. page every configured provider dataset over the run's window, writing
#      ONE immutable ``IntegrationImportArtifact`` per fetched page
#      (invariant 3: sha256 ``payload_hash``, credential-free
#      ``query_snapshot``, never an overwrite — a retry RESUMES from the
#      durable artifacts instead of refetching);
#   4. derive ``IntegrationMetricRow`` rows from the artifacts (projection,
#      never a second fetch — invariant 7) and call the C5
#      ``enqueue_post_sync_projections`` hook as the final step;
#   5. on success stamp ``connection.last_synced_at`` + the sync_finished
#      event and succeed the run.
#
# Every write transaction re-locks the run row FOR UPDATE and re-checks
# ``lease_owner``/status: a lost lease or a cancelled run writes NOTHING
# (single-writer, invariant 3).
from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import cast

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.integrations import oauth as integration_oauth
from app.connectors.integrations._http import IntegrationApiError
from app.connectors.integrations.ga4 import (
    Ga4DimensionCompatibilityError,
)
from app.core.config.integrations_clients import (
    INTEGRATION_CLIENT_BUILDERS,
    INTEGRATION_QUEUE_SPEC,
)
from app.core.config.integrations_contracts import (
    ERROR_GA4_DIMENSION_INCOMPATIBLE,
    ERROR_GRANT_AUTH_FAILED,
    ERROR_PAYLOAD_TOO_LARGE,
    ERROR_PROVIDER_API,
    ERROR_TOKEN_REFRESH_FAILED,
    ERROR_UNMAPPED_PROPERTY,
    EVENT_INTEGRATION_REAUTH_REQUIRED,
    EVENT_INTEGRATION_SYNC_STARTED,
    GRANT_STATUS_CONNECTED,
    GRANT_STATUS_NEEDS_REAUTH,
)
from app.core.config.integrations_datasets import (
    DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
    DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY,
    DATASET_SHOPIFY_ORDERS,
    GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY,
    GA4_ITEM_ATTRIBUTION_CAPABILITY_VERSION,
    GA4_ITEM_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP,
    INTEGRATION_DATASET_TEMPLATES,
    PAGING_MODE_CURSOR,
    IntegrationDatasetTemplate,
)
from app.core.config.integrations_settings import (
    integration_settings,
)
from app.core.config.provider_catalog import ERROR_UNKNOWN
from app.core.config.task_queue import (
    TASK_STATUS_RUNNING,
    TASK_TERMINAL_STATUSES,
)
from app.core.database import SessionLocal
from app.core.telemetry import configure_logging
from app.domain.analytics.sanitize import sanitize_referral_url
from app.domain.commerce.sanitize import sanitize_order_payload
from app.models.integrations import (
    IntegrationConnection,
    IntegrationEvent,
    IntegrationImportArtifact,
    IntegrationOAuthGrant,
    IntegrationSyncRun,
)
from app.orchestration.postgres_task_queue import PostgresTaskQueue
from app.workers.drain import DrainableWorkerMixin
from app.workers.integration.artifacts import ArtifactWriter
from app.workers.integration.finalization import RunFinalizer
from app.workers.integration.paging import (
    PROVIDER_API_ERRORS,
    DataClient,
    DataClientPage,
    DatasetResume,
    MalformedProviderPageError,
    PayloadTooLargeError,
    RunContext,
    RunPreflightError,
    UnsupportedProviderError,
    WorkerPage,
    dataset_resume_from_artifacts,
    next_dataset_page,
    provider_datasets,
)
from app.workers.integration.tokens import fresh_access_token

logger = logging.getLogger("app.workers.integration_worker")


def _utcnow() -> datetime:
    return datetime.now(UTC)


class IntegrationWorker(DrainableWorkerMixin):
    """Claim/lease loop for ``IntegrationSyncRun`` rows.

    ``transport`` is the test seam: an ``httpx.MockTransport`` (or any
    ``httpx.AsyncBaseTransport``) makes the real OAuth + GSC clients run
    without a network. Production passes none.
    """

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        owner: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._session_factory = session_factory or SessionLocal
        self._queue = PostgresTaskQueue(self._session_factory, INTEGRATION_QUEUE_SPEC)
        self._transport = transport
        self.owner = owner or f"integration-worker-{uuid.uuid4().hex[:12]}"
        self._artifacts = ArtifactWriter(
            session_factory=self._session_factory,
            claim_owned_run=self._claim_run_if_owned,
        )
        self._finalizer = RunFinalizer(
            session_factory=self._session_factory,
            claim_owned_run=self._claim_run_if_owned,
        )

    # --- Loop -------------------------------------------------------------

    async def run_once(self) -> int:
        """Sweep expired leases, claim one row, run it. Returns count run."""
        await self._queue.release_expired()
        rows = await self._queue.claim(owner=self.owner, limit=1)
        for row in rows:
            await self._execute(row)
        return len(rows)

    async def run_forever(self) -> None:  # pragma: no cover - process loop
        logger.info("integration worker started", extra={"owner": self.owner})
        while True:
            try:
                ran = await self.run_once()
            except Exception:  # defensive: a bad row must not kill the loop
                logger.exception("integration worker loop iteration failed")
                ran = 0
            if ran == 0:
                await asyncio.sleep(
                    max(0.05, integration_settings.poll_interval_seconds)
                )

    # --- One claimed row --------------------------------------------------

    async def _execute(self, claimed: IntegrationSyncRun) -> None:
        run_id = claimed.id
        try:
            # Cooperative cancel at the boundary: if the run was cancelled
            # between enqueue and claim, never touch the provider.
            async with self._session_factory() as session:
                row = await session.get(IntegrationSyncRun, run_id)
                if row is None or row.status in TASK_TERMINAL_STATUSES:
                    return

            if not await self._queue.mark_running(task_id=run_id, owner=self.owner):
                # Lease lost before the work started; another worker retries.
                return

            ctx = await self._begin_attempt(run_id)
            if ctx is None:
                return
            await self._run(ctx)
        except Exception as exc:  # defensive: never kill the loop
            logger.exception(
                "integration sync crashed", extra={"sync_run_id": str(run_id)}
            )
            with contextlib.suppress(Exception):
                await self._queue.fail(
                    task_id=run_id,
                    owner=self.owner,
                    error_code=ERROR_UNKNOWN,
                    error_detail=f"worker crash: {type(exc).__name__}",
                )

    async def _begin_attempt(self, run_id: uuid.UUID) -> RunContext | None:
        """Bump the attempt count + append sync_started (owner-gated)."""
        async with self._session_factory() as session:
            run = await self._claim_run_if_owned(session, run_id)
            if run is None:
                return None
            connection = await session.get(IntegrationConnection, run.connection_id)
            grant = (
                await session.get(IntegrationOAuthGrant, connection.grant_id)
                if connection is not None
                else None
            )
            if connection is None or grant is None:
                await session.commit()
                return None
            run.attempt_count += 1
            ctx = RunContext(
                run_id=run.id,
                workspace_id=run.workspace_id,
                connection_id=connection.id,
                grant_id=grant.id,
                provider=connection.provider,
                transport=grant.transport,
                grant_status=grant.status,
                sync_kind=run.sync_kind,
                window_start=run.window_start,
                window_end=run.window_end,
                resync_seq=run.resync_seq,
                property_ref=connection.account_ref,
                attempt_count=run.attempt_count,
                max_attempts=run.max_attempts,
                dataset_capabilities=dict(connection.dataset_capabilities or {}),
            )
            self._append_event(
                session,
                ctx,
                event_type=EVENT_INTEGRATION_SYNC_STARTED,
                message=f"Sync started for {ctx.provider}",
                payload={
                    "provider": ctx.provider,
                    "sync_run_id": str(ctx.run_id),
                    "sync_kind": ctx.sync_kind,
                    "window_start": ctx.window_start.isoformat(),
                    "window_end": ctx.window_end.isoformat(),
                    "resync_seq": ctx.resync_seq,
                    "attempt_count": ctx.attempt_count,
                },
            )
            await session.commit()
            return ctx

    async def _run(self, ctx: RunContext) -> None:
        if ctx.grant_status != GRANT_STATUS_CONNECTED:
            await self._queue.fail(
                task_id=ctx.run_id,
                owner=self.owner,
                error_code=ERROR_GRANT_AUTH_FAILED,
                error_detail=f"grant status is {ctx.grant_status!r}",
            )
            return
        try:
            client = self._preflight(ctx)
        except RunPreflightError as exc:
            await self._queue.fail(
                task_id=ctx.run_id,
                owner=self.owner,
                error_code=exc.error_code,
                error_detail=str(exc),
            )
            return

        try:
            access_token = await fresh_access_token(
                ctx,
                session_factory=self._session_factory,
                transport=self._transport,
                now=_utcnow,
            )
        except integration_oauth.IntegrationOAuthError as exc:
            await self._handle_classified_error(
                ctx, exc, run_error_code=ERROR_TOKEN_REFRESH_FAILED
            )
            return

        heartbeat = asyncio.create_task(self._heartbeat_loop(ctx.run_id))
        try:
            for template in provider_datasets(ctx.provider, ctx.dataset_capabilities):
                synced = await self._sync_template(
                    ctx,
                    client=client,
                    template=template,
                    access_token=access_token,
                )
                if not synced:
                    # Lost lease or cancelled at a page boundary: not ours to
                    # finalize — nothing more is written.
                    return
        except PROVIDER_API_ERRORS as exc:
            # Every provider client raises the same classified taxonomy.
            await self._handle_classified_error(
                ctx, exc, retry_after_seconds=exc.retry_after_seconds
            )
            return
        except MalformedProviderPageError as exc:
            # Malformed cursor pageInfo: deterministic, terminal, and the
            # malformed page was NEVER persisted (validation precedes the
            # artifact write).
            await self._queue.fail(
                task_id=ctx.run_id,
                owner=self.owner,
                error_code=ERROR_PROVIDER_API,
                error_detail=str(exc),
            )
            return
        except PayloadTooLargeError as exc:
            await self._queue.fail(
                task_id=ctx.run_id,
                owner=self.owner,
                error_code=ERROR_PAYLOAD_TOO_LARGE,
                error_detail=str(exc),
            )
            return
        finally:
            heartbeat.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat

        await self._finalizer.finalize(ctx)

    def _build_client(self, provider: str) -> DataClient:
        """Provider -> data-API client dispatch via the config-owned registry.

        ``INTEGRATION_CLIENT_BUILDERS`` (config, invariant 1) maps each
        provider to its lazy client builder; an unmapped provider fails the
        run terminally (no retry burn).
        """
        builder = INTEGRATION_CLIENT_BUILDERS.get(provider)
        if builder is None:
            raise UnsupportedProviderError(
                f"no data-API client for provider {provider!r}"
            )
        return builder(transport=self._transport)

    def _preflight(self, ctx: RunContext) -> DataClient:
        """Resolve the data client, asserting the run CAN be attempted.

        Both failures here are deterministic, so they raise
        ``RunPreflightError`` and the caller fails the run terminally
        rather than retrying. The property check in particular must happen
        BEFORE any provider I/O: an empty ``property_ref`` interpolates into
        ``/webmasters/v3/sites//searchAnalytics/query`` (or
        ``/properties/:runReport``) and the provider's confusing 400/404
        would surface as a generic ``provider_api_error``, hiding the fact
        that the connection was simply never pointed at a property. The
        derivation-time ``unmapped_property`` guard cannot cover it — that
        runs only after a SUCCESSFUL fetch.
        """
        client = self._build_client(ctx.provider)
        if not ctx.property_ref:
            raise RunPreflightError(
                ERROR_UNMAPPED_PROPERTY,
                f"connection has no {ctx.provider} property selected; "
                "choose one in Settings → Integrations",
            )
        return client

    # --- Token refresh (serialized per grant, spec section 2) --------------

    async def _handle_classified_error(
        self,
        ctx: RunContext,
        exc: IntegrationApiError,
        *,
        run_error_code: str | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        """Terminal accounting for one classified connector error.

        Token-refresh failures and provider data-API failures share the
        taxonomy: an auth failure moves the grant to needs_reauth and
        fails the run; a retryable failure burns one attempt with backoff
        (or fails terminal at the cap); anything else fails the run. The
        run's error token is ``run_error_code`` when given (the refresh
        path wraps the transport cause in ERROR_TOKEN_REFRESH_FAILED),
        else the exception's own config-owned token.
        """
        error_code = run_error_code or exc.error_code
        if exc.error_code == ERROR_GRANT_AUTH_FAILED:
            await self._mark_grant_needs_reauth(ctx)
            await self._queue.fail(
                task_id=ctx.run_id,
                owner=self.owner,
                error_code=exc.error_code,
                error_detail=str(exc),
            )
            return
        if exc.retryable:
            if ctx.attempt_count < ctx.max_attempts:
                await self._queue.retry(
                    task_id=ctx.run_id,
                    owner=self.owner,
                    delay_seconds=integration_settings.retry_delay(
                        ctx.attempt_count, retry_after_seconds
                    ),
                    error_code=error_code,
                    error_detail=str(exc),
                )
            else:
                await self._queue.fail(
                    task_id=ctx.run_id,
                    owner=self.owner,
                    error_code=INTEGRATION_QUEUE_SPEC.max_attempts_error,
                    error_detail=str(exc),
                )
            return
        await self._queue.fail(
            task_id=ctx.run_id,
            owner=self.owner,
            error_code=error_code,
            error_detail=str(exc),
        )

    async def _mark_grant_needs_reauth(self, ctx: RunContext) -> None:
        """Transition a live grant to needs_reauth + append the event."""
        async with self._session_factory() as session:
            grant = await session.get(
                IntegrationOAuthGrant, ctx.grant_id, with_for_update=True
            )
            if grant is None or grant.status != GRANT_STATUS_CONNECTED:
                await session.commit()
                return
            grant.status = GRANT_STATUS_NEEDS_REAUTH
            self._append_event(
                session,
                ctx,
                event_type=EVENT_INTEGRATION_REAUTH_REQUIRED,
                message=(
                    "Grant token rejected by provider; re-authentication required"
                ),
                payload={
                    "provider": ctx.provider,
                    "transport": ctx.transport,
                    "sync_run_id": str(ctx.run_id),
                    "error_code": ERROR_GRANT_AUTH_FAILED,
                },
            )
            await session.commit()

    # --- Paging + immutable artifacts ---------------------------------------

    async def _sync_template(
        self,
        ctx: RunContext,
        *,
        client: DataClient,
        template: IntegrationDatasetTemplate,
        access_token: str,
    ) -> bool:
        """Page one template, with the NARROW GA4 item fallback path.

        ``Ga4DimensionCompatibilityError`` is caught HERE — around the
        primary item dataset's ``_sync_dataset`` call only — so it never
        reaches the broad ``_PROVIDER_API_ERRORS`` handler: the run
        switches to the channel-group item template, persists the
        capability selection under the connection row lock, and pages the
        fallback in the SAME run. Every other error propagates unchanged.
        """
        try:
            return await self._sync_dataset(
                ctx,
                client=client,
                template=template,
                access_token=access_token,
            )
        except Ga4DimensionCompatibilityError:
            return await self._sync_item_fallback(
                ctx, client=client, template=template, access_token=access_token
            )

    async def _sync_item_fallback(
        self,
        ctx: RunContext,
        *,
        client: DataClient,
        template: IntegrationDatasetTemplate,
        access_token: str,
    ) -> bool:
        if template.dataset != DATASET_GA4_ITEM_SOURCE_MEDIUM_DAILY:
            raise
        if await self._has_dataset_artifact(ctx.run_id, template.dataset):
            raise
        if not await self._persist_item_fallback_capability(ctx):
            return False
        fallback = INTEGRATION_DATASET_TEMPLATES[DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY]
        logger.info(
            "ga4 item dimensions incompatible; falling back to %s",
            fallback.dataset,
            extra={"sync_run_id": str(ctx.run_id)},
        )
        return await self._sync_dataset(
            ctx, client=client, template=fallback, access_token=access_token
        )

    async def _has_dataset_artifact(self, run_id: uuid.UUID, dataset: str) -> bool:
        """True when the run already holds a durable artifact for ``dataset``."""
        async with self._session_factory() as session:
            artifact_id = await session.scalar(
                select(IntegrationImportArtifact.id)
                .where(
                    IntegrationImportArtifact.sync_run_id == run_id,
                    IntegrationImportArtifact.dataset == dataset,
                )
                .limit(1)
            )
            return artifact_id is not None

    async def _persist_item_fallback_capability(self, ctx: RunContext) -> bool:
        """Persist the channel-group item selection under the connection lock.

        Owner-gated exactly like every other write (a lost lease writes
        NOTHING): the run row is re-locked and re-checked first, then the
        connection row is locked FOR UPDATE and its
        ``dataset_capabilities`` entry is stamped with the selected
        dataset, the reduced source granularity, the reason token, and the
        CURRENT capability version (a future version bump re-probes the
        primary instead of trusting this selection).
        """
        async with self._session_factory() as session:
            run = await self._claim_run_if_owned(session, ctx.run_id)
            if run is None:
                return False
            connection = await session.get(
                IntegrationConnection, ctx.connection_id, with_for_update=True
            )
            if connection is None:
                await session.commit()
                return False
            capabilities = dict(connection.dataset_capabilities or {})
            capabilities[GA4_ITEM_ATTRIBUTION_CAPABILITY_KEY] = {
                "selected_dataset": DATASET_GA4_ITEM_CHANNEL_GROUP_DAILY,
                "source_granularity": GA4_ITEM_SOURCE_GRANULARITY_DEFAULT_CHANNEL_GROUP,
                "reason": ERROR_GA4_DIMENSION_INCOMPATIBLE,
                "version": GA4_ITEM_ATTRIBUTION_CAPABILITY_VERSION,
            }
            connection.dataset_capabilities = capabilities
            await session.commit()
            return True

    async def _sync_dataset(
        self,
        ctx: RunContext,
        *,
        client: DataClient,
        template: IntegrationDatasetTemplate,
        access_token: str,
    ) -> bool:
        """Page one dataset to completion. False = lost lease / cancelled.

        Cursor-mode templates (Shopify) run the durable-cursor protocol:
        the resume cursor comes ONLY from the latest immutable artifact's
        ``query_snapshot`` and is injected into the client before each
        unchanged-protocol call; each returned page's outer ``pageInfo``
        is validated BEFORE the artifact write (malformed = terminal);
        the dataset finishes when ``hasNextPage`` is false. Offset
        templates keep the short-page termination rule.
        """
        cursor_mode = template.paging_mode == PAGING_MODE_CURSOR
        page_size = integration_settings.sync_page_size
        resume = await self._dataset_resume(ctx.run_id, template)
        if resume.complete:
            return True
        start_row = resume.start_row
        page_cursor = resume.page_cursor
        while True:
            # Cooperative cancel / lost-lease at the PAGE BOUNDARY: stop
            # BEFORE the next provider call (invariant 9).
            if not await self._still_owned(ctx.run_id):
                return False
            if cursor_mode:
                # The narrow optional cursor capability: the value is sent
                # as the GraphQL ``after`` variable; ``start_row`` stays a
                # logical offset and is never translated.
                set_page_cursor = getattr(client, "set_page_cursor", None)
                if set_page_cursor is not None:
                    set_page_cursor(page_cursor)
            page = await client.query_search_analytics(
                access_token=access_token,
                property_ref=ctx.property_ref,
                dataset=template.dataset,
                dimensions=template.dimensions,
                start_date=ctx.window_start,
                end_date=ctx.window_end,
                start_row=start_row,
            )
            page_info = self._validated_cursor_page_info(page) if cursor_mode else None
            if template.dataset == DATASET_SHOPIFY_ORDERS:
                # Sanitize BEFORE the immutable artifact write: raw order
                # nodes (customer PII) never persist — the artifact stores
                # only allowlisted SanitizedOrder payloads (AC7).
                page = self._sanitize_orders_page(page)
            wrote = await self._artifacts.write(
                ctx,
                template=template,
                page=page,
                start_row=start_row,
                page_cursor=page_cursor if cursor_mode else None,
                page_info=page_info,
            )
            if not wrote:
                return False
            next_page = next_dataset_page(
                cursor_mode=cursor_mode,
                page_info=page_info,
                start_row=start_row,
                raw_row_count=page.raw_row_count,
                page_size=page_size,
            )
            if next_page.complete:
                return True
            start_row = next_page.start_row
            page_cursor = next_page.page_cursor

    @staticmethod
    def _validated_cursor_page_info(page: DataClientPage) -> dict:
        """Validate one cursor-mode page's outer ``pageInfo`` (pre-write).

        Returns the normalized ``{"hasNextPage": bool, "endCursor": str |
        None}``. Missing/non-dict pageInfo, a non-bool ``hasNextPage``, or
        ``hasNextPage=true`` without a non-empty ``endCursor`` raise
        ``MalformedProviderPageError`` — malformed provider data is never
        persisted and never guessed.
        """
        payload = page.payload if isinstance(page.payload, dict) else {}
        page_info = payload.get("pageInfo")
        if not isinstance(page_info, dict):
            raise MalformedProviderPageError(
                "cursor page payload has no pageInfo object"
            )
        has_next = page_info.get("hasNextPage")
        if not isinstance(has_next, bool):
            raise MalformedProviderPageError(
                "cursor pageInfo.hasNextPage is not a bool"
            )
        end_cursor = page_info.get("endCursor")
        if end_cursor is not None and not isinstance(end_cursor, str):
            raise MalformedProviderPageError(
                "cursor pageInfo.endCursor is not a string"
            )
        if has_next and not end_cursor:
            raise MalformedProviderPageError(
                "cursor pageInfo hasNextPage without an endCursor"
            )
        return {"hasNextPage": has_next, "endCursor": end_cursor or None}

    @staticmethod
    def _sanitize_orders_page(page: DataClientPage) -> WorkerPage:
        """Transform a raw orders page into its sanitized persistable form.

        The connector returns structurally-normalized-but-RAW order nodes;
        HERE — in the worker, before the immutable artifact write — each
        is allowlist-sanitized (the connector never sanitizes). The
        sanitized payload keeps the outer ``pageInfo`` for the cursor
        protocol; ``raw_row_count`` (the outer node count) is preserved.
        """
        payload = page.payload if isinstance(page.payload, dict) else {}
        orders = payload.get("orders")
        sanitized = (
            [
                sanitize_order_payload(
                    order, url_sanitizer=sanitize_referral_url
                ).to_payload()
                for order in orders
                if isinstance(order, dict)
            ]
            if isinstance(orders, list)
            else []
        )
        return WorkerPage(
            payload={"orders": sanitized, "pageInfo": payload.get("pageInfo") or {}},
            rows=tuple(sanitized),
            raw_row_count=page.raw_row_count,
        )

    async def _dataset_resume(
        self, run_id: uuid.UUID, template: IntegrationDatasetTemplate
    ) -> DatasetResume:
        """Resume state for one dataset from its DURABLE artifacts.

        A retry never refetches a persisted page (immutability + idempotent
        retries): the artifact pages already written for this run tell us
        either that the dataset is complete or where to resume. Offset
        datasets: complete when the last page's RAW provider row count was
        partial, else resume at the next ``startRow``. Cursor datasets:
        complete when the last page's ``pageInfo.hasNextPage`` is false,
        else resume from the snapshot's ``nextPageCursor`` — no cursor is
        ever held only in memory across a process restart.
        """
        page_size = integration_settings.sync_page_size
        cursor_mode = template.paging_mode == PAGING_MODE_CURSOR
        async with self._session_factory() as session:
            rows = (
                await session.execute(
                    select(
                        IntegrationImportArtifact.query_snapshot,
                        IntegrationImportArtifact.row_count,
                        IntegrationImportArtifact.payload,
                    ).where(
                        IntegrationImportArtifact.sync_run_id == run_id,
                        IntegrationImportArtifact.dataset == template.dataset,
                    )
                )
            ).all()
        return dataset_resume_from_artifacts(
            cast(Sequence[tuple[dict | None, int, dict | None]], rows),
            cursor_mode=cursor_mode,
            page_size=page_size,
        )

    async def _still_owned(self, run_id: uuid.UUID) -> bool:
        async with self._session_factory() as session:
            run = await session.get(IntegrationSyncRun, run_id)
            return (
                run is not None
                and run.lease_owner == self.owner
                and run.status == TASK_STATUS_RUNNING
            )

    async def _claim_run_if_owned(
        self, session: AsyncSession, run_id: uuid.UUID
    ) -> IntegrationSyncRun | None:
        """Lock + return the run only while THIS owner still runs it.

        A missing row, a lost lease, or a cancelled run yields ``None``
        after the lock is released with nothing staged — a lost lease
        writes NOTHING (single-writer, invariant 3).
        """
        run = await session.get(IntegrationSyncRun, run_id, with_for_update=True)
        if (
            run is None
            or run.lease_owner != self.owner
            or run.status != TASK_STATUS_RUNNING
        ):
            await session.commit()  # nothing staged; releases the lock
            return None
        return run

    def _append_event(
        self,
        session: AsyncSession,
        ctx: RunContext,
        *,
        event_type: str,
        message: str,
        payload: dict,
    ) -> None:
        """Stage one integration event on the run's connection + grant."""
        session.add(
            IntegrationEvent(
                workspace_id=ctx.workspace_id,
                connection_id=ctx.connection_id,
                grant_id=ctx.grant_id,
                event_type=event_type,
                message=message,
                payload=payload,
            )
        )

    async def _heartbeat_loop(
        self, run_id: uuid.UUID
    ) -> None:  # pragma: no cover - timing loop
        while True:
            await asyncio.sleep(
                max(1.0, integration_settings.heartbeat_interval_seconds)
            )
            try:
                await self._queue.heartbeat(task_id=run_id, owner=self.owner)
            except asyncio.CancelledError:
                raise
            except Exception:
                # A dead heartbeat loop silently expires the lease and lets
                # the sweeper hand the run to another worker mid-call; keep
                # beating through transient failures instead.
                logger.exception(
                    "heartbeat failed; retrying", extra={"sync_run_id": str(run_id)}
                )


if __name__ == "__main__":  # pragma: no cover
    configure_logging()
    asyncio.run(IntegrationWorker().run_forever())
