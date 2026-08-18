"""Shopify run derivation: artifacts -> catalog + feed issues + order facts.

The commerce analogue of ``domain/integrations/derive.py::derive_run`` for
the Shopify entity feeds (no metric rows): resolves the ACTIVE property
mapping (never guessed — ``UnmappedPropertyError`` fails the run), splits
the run's artifacts by dataset, and runs the catalog merge, feed
validation, and sanitized-order fact derivation inside the caller's (the
integration worker's) owner-gated terminal transaction, which performs
the C5 ``enqueue_post_sync_projections`` call as the final step.

Idempotent under finalize replay: feed issues insert conflict-safely on
``(sync_run_id, external_item_ref, rule_id)`` and order facts on
``(connection_id, order_ref_hash, resync_seq)``; the catalog merge is a
deterministic re-application of the same platform values.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config.commerce import COMMERCE_IMPORTER_VERSION
from app.core.config.integrations_datasets import (
    DATASET_SHOPIFY_ORDERS,
    DATASET_SHOPIFY_PRODUCTS,
)
from app.domain.commerce.catalog import merge_catalog_row
from app.domain.commerce.feed import FeedFinding, validate_feed_row
from app.domain.commerce.orders import derive_order_facts
from app.domain.integrations.derive import resolve_active_mapping
from app.models.commerce import FeedIssue
from app.models.integrations import (
    IntegrationConnection,
    IntegrationImportArtifact,
    IntegrationPropertyMapping,
    IntegrationSyncRun,
)
from app.models.product import Product


@dataclass(frozen=True)
class DerivedCommerceRun:
    """The outcome of deriving one Shopify run's artifacts."""

    project_id: uuid.UUID
    artifact_ids: tuple[uuid.UUID, ...]
    product_count: int
    feed_issue_count: int
    order_fact_count: int


async def _existing_product(
    session: AsyncSession, *, project_id: uuid.UUID, row: Mapping
) -> Product | None:
    sku = str(row.get("sku") or "").strip()
    if not sku:
        return None
    return await session.scalar(
        select(Product).where(Product.project_id == project_id, Product.sku == sku)
    )


async def _insert_feed_issue(
    session: AsyncSession,
    *,
    run: IntegrationSyncRun,
    connection: IntegrationConnection,
    project_id: uuid.UUID,
    artifact: IntegrationImportArtifact,
    row: Mapping,
    product: Product | None,
    finding: FeedFinding,
) -> None:
    await session.execute(
        pg_insert(FeedIssue)
        .values(
            workspace_id=run.workspace_id,
            project_id=project_id,
            connection_id=connection.id,
            sync_run_id=run.id,
            external_item_ref=str(row.get("variant_ref") or ""),
            product_id=product.id if product is not None else None,
            rule_id=finding.rule_id,
            severity=finding.severity,
            evidence=finding.evidence,
            source_artifact_id=artifact.id,
            importer_version=COMMERCE_IMPORTER_VERSION,
        )
        .on_conflict_do_nothing(
            index_elements=["sync_run_id", "external_item_ref", "rule_id"]
        )
    )


async def _derive_product_artifact(
    session: AsyncSession,
    *,
    run: IntegrationSyncRun,
    connection: IntegrationConnection,
    project_id: uuid.UUID,
    mapping: IntegrationPropertyMapping,
    artifact: IntegrationImportArtifact,
    rows: list,
) -> tuple[int, int]:
    product_count = 0
    issue_count = 0
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        existing = await _existing_product(session, project_id=project_id, row=row)
        findings = list(validate_feed_row(row=row, product=existing))
        result = await merge_catalog_row(
            session,
            mapping=mapping,
            connection=connection,
            run=run,
            artifact=artifact,
            row=row,
        )
        if result.finding is not None:
            findings.append(result.finding)
        product_count += result.product is not None
        for finding in findings:
            await _insert_feed_issue(
                session,
                run=run,
                connection=connection,
                project_id=project_id,
                artifact=artifact,
                row=row,
                product=result.product,
                finding=finding,
            )
            issue_count += 1
    return product_count, issue_count


async def derive_shopify_run(
    session: AsyncSession,
    *,
    run: IntegrationSyncRun,
    connection: IntegrationConnection,
    artifacts: list[IntegrationImportArtifact],
) -> DerivedCommerceRun:
    """Derive one Shopify run's catalog/feed/order projections.

    Catalog artifacts merge every catalog row (validating the feed rules
    against the PRE-merge product state); order artifacts insert one new
    fact per sanitized order. Returns the project + artifact/count
    bookkeeping for the worker's terminal event.
    """
    mapping = await resolve_active_mapping(
        session,
        workspace_id=run.workspace_id,
        provider=connection.provider,
        property_ref=connection.account_ref,
    )
    product_count = 0
    feed_issue_count = 0
    order_fact_count = 0
    for artifact in artifacts:
        payload = artifact.payload or {}
        if artifact.dataset == DATASET_SHOPIFY_PRODUCTS:
            products, issues = await _derive_product_artifact(
                session,
                run=run,
                connection=connection,
                project_id=mapping.project_id,
                mapping=mapping,
                artifact=artifact,
                rows=payload.get("rows") or [],
            )
            product_count += products
            feed_issue_count += issues
        elif artifact.dataset == DATASET_SHOPIFY_ORDERS:
            orders = payload.get("orders") or []
            order_fact_count += await derive_order_facts(
                session,
                mapping=mapping,
                connection=connection,
                run=run,
                artifact=artifact,
                orders=orders,
            )
        # An unknown dataset id is skipped, never guessed (the config
        # templates are the only dataset vocabulary).
    return DerivedCommerceRun(
        project_id=mapping.project_id,
        artifact_ids=tuple(artifact.id for artifact in artifacts),
        product_count=product_count,
        feed_issue_count=feed_issue_count,
        order_fact_count=order_fact_count,
    )
