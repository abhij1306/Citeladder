"""Immutable import-artifact persistence for integration sync pages."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.integrations_datasets import IntegrationDatasetTemplate
from app.core.config.integrations_settings import integration_settings
from app.models.integrations import IntegrationImportArtifact, IntegrationSyncRun
from app.workers.integration.paging import (
    DataClientPage,
    PayloadTooLargeError,
    RunContext,
)

ClaimOwnedRun = Callable[
    [AsyncSession, uuid.UUID], Awaitable[IntegrationSyncRun | None]
]


class ArtifactWriter:
    """Append one validated provider page only while its lease remains owned."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        claim_owned_run: ClaimOwnedRun,
    ) -> None:
        self._session_factory = session_factory
        self._claim_owned_run = claim_owned_run

    async def write(
        self,
        ctx: RunContext,
        *,
        template: IntegrationDatasetTemplate,
        page: DataClientPage,
        start_row: int,
        page_cursor: str | None = None,
        page_info: dict | None = None,
    ) -> bool:
        """Hash and append one page, never truncating an oversized payload."""
        canonical = json.dumps(page.payload, sort_keys=True, separators=(",", ":"))
        encoded = canonical.encode("utf-8")
        if len(encoded) > integration_settings.max_inline_payload_bytes:
            raise PayloadTooLargeError(
                f"page payload is {len(encoded)} bytes, over the inline cap "
                f"of {integration_settings.max_inline_payload_bytes}"
            )
        return await self._persist(
            ctx,
            template=template,
            page=page,
            payload_hash=hashlib.sha256(encoded).hexdigest(),
            query_snapshot=self._query_snapshot(
                ctx,
                template=template,
                page=page,
                start_row=start_row,
                page_cursor=page_cursor,
                page_info=page_info,
            ),
        )

    @staticmethod
    def _query_snapshot(
        ctx: RunContext,
        *,
        template: IntegrationDatasetTemplate,
        page: DataClientPage,
        start_row: int,
        page_cursor: str | None,
        page_info: dict | None,
    ) -> dict:
        """Build the credential-free query and durable cursor checkpoint."""
        snapshot: dict = {
            "api_method": template.api_method,
            "dataset": template.dataset,
            "property_ref": ctx.property_ref,
            "startDate": ctx.window_start.isoformat(),
            "endDate": ctx.window_end.isoformat(),
            "dimensions": list(template.dimensions),
            "metrics": list(template.metrics),
            "rowLimit": integration_settings.sync_page_size,
            "startRow": start_row,
        }
        metadata = page.payload.get("metadata")
        if isinstance(metadata, dict):
            snapshot["providerMetadata"] = metadata
        snapshot["coverage"] = {
            "returnedRows": page.raw_row_count,
            "pageCapacity": integration_settings.sync_page_size,
            "mayHaveMoreRows": page.raw_row_count
            >= integration_settings.sync_page_size,
        }
        if page_info is not None:
            snapshot["pagingMode"] = template.paging_mode
            snapshot["pageCursor"] = page_cursor
            snapshot["nextPageCursor"] = (
                page_info["endCursor"] if page_info["hasNextPage"] else None
            )
        return snapshot

    async def _persist(
        self,
        ctx: RunContext,
        *,
        template: IntegrationDatasetTemplate,
        page: DataClientPage,
        payload_hash: str,
        query_snapshot: dict,
    ) -> bool:
        async with self._session_factory() as session:
            run = await self._claim_owned_run(session, ctx.run_id)
            if run is None:
                return False
            session.add(
                IntegrationImportArtifact(
                    sync_run_id=run.id,
                    connection_id=ctx.connection_id,
                    workspace_id=ctx.workspace_id,
                    provider=ctx.provider,
                    dataset=template.dataset,
                    query_snapshot=query_snapshot,
                    payload_hash=payload_hash,
                    fetched_at=datetime.now(UTC),
                    row_count=page.raw_row_count,
                    payload=page.payload,
                )
            )
            await session.commit()
            return True
