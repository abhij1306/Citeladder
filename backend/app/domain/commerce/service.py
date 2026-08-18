"""Persisted-only Commerce catalog-health projection (invariant 7)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.commerce import (
    FEED_SEVERITY_ERROR,
    FEED_SEVERITY_INFO,
    FEED_SEVERITY_WARNING,
)
from app.core.config.integrations_contracts import (
    MAPPING_STATUS_ACTIVE,
)
from app.core.config.integrations_transport import (
    INTEGRATION_PROVIDER_SHOPIFY,
)
from app.core.config.products import PRODUCT_ORIGIN_SYNCED
from app.domain.commerce.schemas import (
    CommerceCatalogHealth,
    CommerceConnectionSummary,
    CommerceSyncSummary,
    ProductFeedHealth,
)
from app.models.commerce import FeedIssue
from app.models.integrations import (
    IntegrationConnection,
    IntegrationImportArtifact,
    IntegrationOAuthGrant,
    IntegrationPropertyMapping,
    IntegrationSyncRun,
)
from app.models.product import Product

_SEVERITY_RANK = {
    FEED_SEVERITY_INFO: 0,
    FEED_SEVERITY_WARNING: 1,
    FEED_SEVERITY_ERROR: 2,
}


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


async def get_catalog_health(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    project_id: uuid.UUID,
) -> CommerceCatalogHealth:
    """Project Shopify connection/feed state from persisted rows only."""
    connection_rows = (
        await session.execute(
            select(IntegrationConnection, IntegrationOAuthGrant.status)
            .join(
                IntegrationPropertyMapping,
                IntegrationPropertyMapping.connection_id == IntegrationConnection.id,
            )
            .join(
                IntegrationOAuthGrant,
                IntegrationOAuthGrant.id == IntegrationConnection.grant_id,
            )
            .where(IntegrationPropertyMapping.workspace_id == workspace_id)
            .where(IntegrationPropertyMapping.project_id == project_id)
            .where(IntegrationPropertyMapping.status == MAPPING_STATUS_ACTIVE)
            .where(IntegrationConnection.provider == INTEGRATION_PROVIDER_SHOPIFY)
            .order_by(IntegrationConnection.created_at, IntegrationConnection.id)
        )
    ).all()
    connections_by_id = {connection.id: connection for connection, _ in connection_rows}
    connection_ids = list(connections_by_id)
    if not connection_ids:
        return CommerceCatalogHealth(
            project_id=project_id, connections=[], products=[], generated_at=None
        )

    row_counts = (
        select(
            IntegrationImportArtifact.sync_run_id,
            func.coalesce(func.sum(IntegrationImportArtifact.row_count), 0).label(
                "row_count"
            ),
        )
        .group_by(IntegrationImportArtifact.sync_run_id)
        .subquery()
    )
    run_rows = (
        await session.execute(
            select(IntegrationSyncRun, func.coalesce(row_counts.c.row_count, 0))
            .outerjoin(row_counts, row_counts.c.sync_run_id == IntegrationSyncRun.id)
            .where(IntegrationSyncRun.workspace_id == workspace_id)
            .where(IntegrationSyncRun.connection_id.in_(connection_ids))
            .order_by(
                IntegrationSyncRun.connection_id,
                IntegrationSyncRun.created_at.desc(),
                IntegrationSyncRun.id.desc(),
            )
        )
    ).all()
    latest_runs: dict[uuid.UUID, tuple[IntegrationSyncRun, int]] = {}
    for run, row_count in run_rows:
        latest_runs.setdefault(run.connection_id, (run, int(row_count)))

    connection_summaries: list[CommerceConnectionSummary] = []
    for connection, grant_status in connection_rows:
        latest = latest_runs.get(connection.id)
        sync_summary = None
        if latest is not None:
            run, row_count = latest
            sync_summary = CommerceSyncSummary(
                sync_run_id=run.id,
                connection_id=connection.id,
                status=run.status,
                window_start=run.window_start.isoformat(),
                window_end=run.window_end.isoformat(),
                row_count=row_count,
                error_code=run.error_code,
                completed_at=_iso(run.completed_at),
            )
        connection_summaries.append(
            CommerceConnectionSummary(
                connection_id=connection.id,
                provider=INTEGRATION_PROVIDER_SHOPIFY,
                label=connection.label,
                account_ref=connection.account_ref,
                grant_status=grant_status,
                last_synced_at=_iso(connection.last_synced_at),
                latest_sync=sync_summary,
            )
        )

    products = list(
        (
            await session.scalars(
                select(Product)
                .where(Product.project_id == project_id)
                .where(Product.connection_id.in_(connection_ids))
                .where(Product.origin == PRODUCT_ORIGIN_SYNCED)
                .order_by(Product.sku, Product.id)
            )
        ).all()
    )
    # Feed health is a projection of each connection's latest run. Historical
    # findings must not leak onto products absent from that run or reappear as
    # orphan rows in the current catalog-health response.
    run_ids = {run.id for run, _row_count in latest_runs.values()}
    issues_by_product: dict[tuple[uuid.UUID, uuid.UUID], list[FeedIssue]] = defaultdict(
        list
    )
    orphan_issues: dict[tuple[uuid.UUID, uuid.UUID, str], list[FeedIssue]] = (
        defaultdict(list)
    )
    if run_ids:
        issues = (
            await session.scalars(
                select(FeedIssue)
                .where(FeedIssue.workspace_id == workspace_id)
                .where(FeedIssue.project_id == project_id)
                .where(FeedIssue.sync_run_id.in_(run_ids))
                .order_by(FeedIssue.rule_id, FeedIssue.id)
            )
        ).all()
        for issue in issues:
            if issue.product_id is not None:
                issues_by_product[(issue.product_id, issue.sync_run_id)].append(issue)
            else:
                orphan_issues[
                    (issue.connection_id, issue.sync_run_id, issue.external_item_ref)
                ].append(issue)

    product_health: list[ProductFeedHealth] = []
    for product in products:
        if product.connection_id is None or product.last_seen_sync_run_id is None:
            continue
        latest = latest_runs.get(product.connection_id)
        last_seen = latest is not None and product.last_seen_sync_run_id == latest[0].id
        issues = issues_by_product.get((product.id, product.last_seen_sync_run_id), [])
        highest = max(
            (issue.severity for issue in issues),
            key=lambda value: _SEVERITY_RANK.get(value, -1),
            default=None,
        )
        if highest == FEED_SEVERITY_ERROR:
            health_status = "error"
        elif highest in {FEED_SEVERITY_WARNING, FEED_SEVERITY_INFO}:
            health_status = "warning"
        elif last_seen:
            health_status = "healthy"
        else:
            health_status = "unavailable"
        product_health.append(
            ProductFeedHealth(
                product_id=product.id,
                connection_id=product.connection_id,
                external_item_ref=product.external_item_ref,
                sync_run_id=product.last_seen_sync_run_id,
                status=health_status,
                highest_severity=highest,
                issue_count=len(issues),
                rule_ids=sorted({issue.rule_id for issue in issues}),
                last_seen_in_feed=last_seen,
            )
        )

    for (connection_id, sync_run_id, external_ref), issues in sorted(
        orphan_issues.items(), key=lambda item: tuple(str(value) for value in item[0])
    ):
        highest = max(
            (issue.severity for issue in issues),
            key=lambda value: _SEVERITY_RANK.get(value, -1),
            default=None,
        )
        latest = latest_runs.get(connection_id)
        last_seen = latest is not None and sync_run_id == latest[0].id
        health_status = "error" if highest == FEED_SEVERITY_ERROR else "warning"
        product_health.append(
            ProductFeedHealth(
                product_id=None,
                connection_id=connection_id,
                external_item_ref=external_ref,
                sync_run_id=sync_run_id,
                status=health_status,
                highest_severity=highest,
                issue_count=len(issues),
                rule_ids=sorted({issue.rule_id for issue in issues}),
                last_seen_in_feed=last_seen,
            )
        )

    generated_at = max(
        (run.updated_at for run, _row_count in latest_runs.values()),
        default=None,
    )
    return CommerceCatalogHealth(
        project_id=project_id,
        connections=connection_summaries,
        products=product_health,
        generated_at=_iso(generated_at),
    )
