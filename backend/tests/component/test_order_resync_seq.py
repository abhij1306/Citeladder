"""Component tests for order-fact resync revisions + the retention sweep.

Exercises ``derive_order_facts`` against a live Postgres schema:

  - per-order monotonic ``resync_seq`` across re-syncs (refund /
    cancellation revisions and overlapping windows), with prior rows
    immutable and consumers reading the LATEST via
    ``order_fact_not_superseded``;
  - intra-run duplicate allocation + conflict-safe finalize replay;
  - the sanitized-boundary re-validation (unexpected keys rejected);
  - SKU -> product resolution (unresolved stays null);
  - the ``order_retention_sweep`` executor: expired facts hard-deleted in
    bounded committed batches, young rows kept, idempotent re-run.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config.analytics import ANALYTICS_TASK_KIND_ORDER_RETENTION_SWEEP
from app.core.config.commerce import ORDER_RETENTION_DAYS, ORDER_SANITIZED_KEYS
from app.core.config.integrations_contracts import (
    GRANT_STATUS_CONNECTED,
)
from app.core.config.integrations_datasets import (
    DATASET_SHOPIFY_ORDERS,
)
from app.core.config.integrations_transport import (
    INTEGRATION_PROVIDER_SHOPIFY,
    INTEGRATION_TRANSPORT_SHOPIFY,
)
from app.core.security import encrypt_secret
from app.domain.analytics.sanitize import sanitize_referral_url
from app.domain.commerce import orders as order_module
from app.domain.commerce.orders import (
    derive_order_facts,
    order_fact_not_superseded,
    run_order_retention_sweep,
)
from app.domain.commerce.sanitize import sanitize_order_payload
from app.models.analytics import AnalyticsTask
from app.models.commerce import OrderFact
from app.models.integrations import (
    IntegrationConnection,
    IntegrationImportArtifact,
    IntegrationOAuthGrant,
    IntegrationPropertyMapping,
    IntegrationSyncRun,
)
from app.models.product import Product
from app.models.project import Project
from app.models.workspace import Workspace

_SHOP = "volt-city.myshopify.com"
_WINDOW_A = (date(2026, 7, 1), date(2026, 7, 7))
# Overlaps _WINDOW_A: the same order legitimately revises across both.
_WINDOW_B = (date(2026, 7, 5), date(2026, 7, 12))


def _raw_order(order_suffix: str, *, total: str = "64.99", **overrides: object) -> dict:
    node: dict = {
        "id": f"gid://shopify/Order/{order_suffix}",
        "createdAt": "2026-07-03T10:15:00Z",
        "updatedAt": "2026-07-03T11:00:00Z",
        "cancelledAt": None,
        "currencyCode": "USD",
        "currentTotalPriceSet": {"shopMoney": {"amount": total, "currencyCode": "USD"}},
        "displayFinancialStatus": "PAID",
        "displayFulfillmentStatus": "UNFULFILLED",
        "email": "buyer@example.com",
        "customerJourneySummary": {"ready": False},
        "lineItems": [
            {
                "sku": "VC-500",
                "quantity": 1,
                "currentQuantity": 1,
                "originalUnitPriceSet": {
                    "shopMoney": {"amount": "64.99", "currencyCode": "USD"}
                },
            }
        ],
    }
    node.update(overrides)
    return node


def _sanitized(order_suffix: str, *, total: str = "64.99", **overrides: object) -> dict:
    return sanitize_order_payload(
        _raw_order(order_suffix, total=total, **overrides),
        url_sanitizer=sanitize_referral_url,
    ).to_payload()


class _Graph:
    def __init__(
        self,
        *,
        workspace_id: uuid.UUID,
        project_id: uuid.UUID,
        connection: IntegrationConnection,
        mapping: IntegrationPropertyMapping,
    ) -> None:
        self.workspace_id = workspace_id
        self.project_id = project_id
        self.connection = connection
        self.mapping = mapping
        self.run_counter = 0


async def _seed_graph(db_session: AsyncSession) -> _Graph:
    workspace = Workspace(name="Acme")
    db_session.add(workspace)
    await db_session.flush()
    project = Project(workspace_id=workspace.id, name="Acme Site")
    db_session.add(project)
    await db_session.flush()
    grant = IntegrationOAuthGrant(
        workspace_id=workspace.id,
        transport=INTEGRATION_TRANSPORT_SHOPIFY,
        access_token_encrypted=encrypt_secret("shpat_x"),  # pragma: allowlist secret
        refresh_token_encrypted="",
        token_expires_at=None,
        granted_scopes=["read_orders"],
        status=GRANT_STATUS_CONNECTED,
    )
    db_session.add(grant)
    await db_session.flush()
    connection = IntegrationConnection(
        workspace_id=workspace.id,
        grant_id=grant.id,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        label="shop",
        account_ref=_SHOP,
    )
    db_session.add(connection)
    await db_session.flush()
    mapping = IntegrationPropertyMapping(
        workspace_id=workspace.id,
        connection_id=connection.id,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        property_ref=_SHOP,
        project_id=project.id,
        status="active",
    )
    db_session.add(mapping)
    await db_session.commit()
    return _Graph(
        workspace_id=workspace.id,
        project_id=project.id,
        connection=connection,
        mapping=mapping,
    )


async def _new_run_artifact(
    db_session: AsyncSession, graph: _Graph, window: tuple[date, date]
) -> tuple[IntegrationSyncRun, IntegrationImportArtifact]:
    graph.run_counter += 1
    run = IntegrationSyncRun(
        connection_id=graph.connection.id,
        workspace_id=graph.workspace_id,
        sync_kind="on_demand",
        window_start=window[0],
        window_end=window[1],
        resync_seq=graph.run_counter,
        idempotency_key=f"order-seq-test-{graph.workspace_id}-{graph.run_counter}",
        # Terminal: derivation reads the artifacts of FINISHED page writes;
        # this also keeps the one-ACTIVE-run-per-window index satisfied when
        # a test seeds several runs over the same window.
        status="succeeded",
    )
    db_session.add(run)
    await db_session.flush()
    artifact = IntegrationImportArtifact(
        sync_run_id=run.id,
        connection_id=graph.connection.id,
        workspace_id=graph.workspace_id,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        dataset=DATASET_SHOPIFY_ORDERS,
        query_snapshot={},
        payload_hash="0" * 64,
        row_count=0,
        payload={"orders": [], "pageInfo": {"hasNextPage": False, "endCursor": None}},
    )
    db_session.add(artifact)
    await db_session.flush()
    return run, artifact


async def _derive(
    db_session: AsyncSession,
    graph: _Graph,
    window: tuple[date, date],
    orders: list[dict],
) -> int:
    run, artifact = await _new_run_artifact(db_session, graph, window)
    count = await derive_order_facts(
        db_session,
        mapping=graph.mapping,
        connection=graph.connection,
        run=run,
        artifact=artifact,
        orders=orders,
    )
    await db_session.commit()
    return count


async def _facts(
    db_session: AsyncSession, graph: _Graph, order_hash: str | None = None
) -> list[OrderFact]:
    stmt = (
        select(OrderFact)
        .where(OrderFact.connection_id == graph.connection.id)
        .order_by(OrderFact.order_ref_hash.asc(), OrderFact.resync_seq.asc())
    )
    if order_hash is not None:
        stmt = stmt.where(OrderFact.order_ref_hash == order_hash)
    return list((await db_session.scalars(stmt)).all())


@pytest.mark.asyncio
async def test_revision_allocates_monotonic_seq_with_immutable_priors(
    db_session,
) -> None:
    """A refund revision across OVERLAPPING windows -> new fact at seq 1."""
    graph = await _seed_graph(db_session)

    staged = await _derive(db_session, graph, _WINDOW_A, [_sanitized("o1")])
    assert staged == 1
    (first,) = await _facts(db_session, graph)
    assert first.resync_seq == 0
    assert first.total_amount == Decimal("64.99")
    first_id = first.id
    first_updated_payload = first.line_items

    # The same order comes back revised (partial refund) in an overlapping
    # window's run: a NEW fact at the next seq; the prior row is immutable.
    revised = _sanitized("o1", total="44.99", updatedAt="2026-07-06T08:00:00Z")
    staged = await _derive(db_session, graph, _WINDOW_B, [revised])
    assert staged == 1

    facts = await _facts(db_session, graph)
    assert [fact.resync_seq for fact in facts] == [0, 1]
    assert facts[0].id == first_id
    assert facts[0].total_amount == Decimal("64.99")  # untouched
    assert facts[0].line_items == first_updated_payload
    assert facts[1].total_amount == Decimal("44.99")

    # Consumers read the LATEST per order via the not-superseded predicate.
    latest = list(
        (
            await db_session.scalars(
                select(OrderFact)
                .where(OrderFact.connection_id == graph.connection.id)
                .where(order_fact_not_superseded())
            )
        ).all()
    )
    assert [fact.resync_seq for fact in latest] == [1]


@pytest.mark.asyncio
async def test_sequences_are_per_order(db_session) -> None:
    graph = await _seed_graph(db_session)

    await _derive(db_session, graph, _WINDOW_A, [_sanitized("o1"), _sanitized("o2")])
    await _derive(db_session, graph, _WINDOW_B, [_sanitized("o1", total="1.00")])

    facts = await _facts(db_session, graph)
    by_hash: dict[str, list[int]] = {}
    for fact in facts:
        by_hash.setdefault(fact.order_ref_hash, []).append(fact.resync_seq)
    assert sorted(len(seqs) for seqs in by_hash.values()) == [1, 2]
    # The revised order has [0, 1]; the unrevised one stays at [0].
    assert sorted(seqs for seqs in by_hash.values()) == [[0], [0, 1]]


@pytest.mark.asyncio
async def test_intra_run_duplicates_allocate_successive_seqs(db_session) -> None:
    graph = await _seed_graph(db_session)

    staged = await _derive(
        db_session,
        graph,
        _WINDOW_A,
        [_sanitized("o1"), _sanitized("o1", total="60.00")],
    )

    assert staged == 2
    facts = await _facts(db_session, graph)
    assert [fact.resync_seq for fact in facts] == [0, 1]


@pytest.mark.asyncio
async def test_retried_run_finalize_replays_to_the_same_seq(db_session) -> None:
    """The worker's real replay path: a crashed finalize rolls its inserts
    back in the SAME terminal transaction, so the retried run's finalize
    re-derives the SAME seq — one fact total, no duplicate revision."""
    graph = await _seed_graph(db_session)
    run, artifact = await _new_run_artifact(db_session, graph, _WINDOW_A)
    # The artifact pages are durable BEFORE any finalize (the worker
    # commits each artifact separately from its terminal transaction).
    await db_session.commit()
    orders = [_sanitized("o1")]

    # Attempt 1: the finalize transaction crashes before its commit — the
    # staged derivation rolls back with it (the durable artifact stays).
    first = await derive_order_facts(
        db_session,
        mapping=graph.mapping,
        connection=graph.connection,
        run=run,
        artifact=artifact,
        orders=orders,
    )
    await db_session.rollback()
    # A rollback expires every ORM object; reload the durable rows.
    await db_session.refresh(graph.mapping)
    await db_session.refresh(graph.connection)
    await db_session.refresh(run)
    await db_session.refresh(artifact)
    # Attempt 2 (run re-claimed after the lease expired): the datasets read
    # complete from the durable artifacts and the finalize re-derives.
    second = await derive_order_facts(
        db_session,
        mapping=graph.mapping,
        connection=graph.connection,
        run=run,
        artifact=artifact,
        orders=orders,
    )
    await db_session.commit()

    assert first == second == 1
    facts = await _facts(db_session, graph)
    assert [fact.resync_seq for fact in facts] == [0]


@pytest.mark.asyncio
async def test_unexpected_key_or_missing_required_fields_rejected(db_session) -> None:
    graph = await _seed_graph(db_session)

    hostile = dict(_sanitized("o1"))
    hostile["email"] = "buyer@example.com"  # outside ORDER_SANITIZED_KEYS
    missing_time = dict(_sanitized("o2"))
    missing_time["occurred_at"] = ""
    missing_total = dict(_sanitized("o3"))
    missing_total["total_amount"] = "not-a-decimal"

    staged = await _derive(
        db_session, graph, _WINDOW_A, [hostile, missing_time, missing_total]
    )

    assert staged == 0
    assert await _facts(db_session, graph) == []


@pytest.mark.asyncio
async def test_sanitized_keys_revalidated_against_config(db_session) -> None:
    graph = await _seed_graph(db_session)
    payload = _sanitized("o1")
    assert set(payload) <= ORDER_SANITIZED_KEYS

    staged = await _derive(db_session, graph, _WINDOW_A, [payload])

    assert staged == 1
    (fact,) = await _facts(db_session, graph)
    assert fact.currency == "USD"
    assert fact.importer_version == "commerce-importer-1"
    assert fact.order_sanitize_version == "order-sanitize-1"


@pytest.mark.asyncio
async def test_line_item_product_resolution(db_session) -> None:
    graph = await _seed_graph(db_session)
    product = Product(
        project_id=graph.project_id,
        sku="VC-500",
        name="VoltCity 500",
        origin="synced",
        connection_id=graph.connection.id,
    )
    db_session.add(product)
    await db_session.commit()
    payload = _sanitized("o1")
    payload["line_items"] = [
        {"sku": "VC-500", "quantity": 1, "unit_price": "64.99"},
        {"sku": "VC-UNKNOWN", "quantity": 2, "unit_price": "1.00"},
    ]

    staged = await _derive(db_session, graph, _WINDOW_A, [payload])

    assert staged == 1
    (fact,) = await _facts(db_session, graph)
    assert fact.line_items[0]["product_id"] == str(product.id)
    assert fact.line_items[1]["product_id"] is None


# --- order_retention_sweep ----------------------------------------------------

_NOW = datetime.now(UTC)
_EXPIRED = _NOW - timedelta(days=ORDER_RETENTION_DAYS + 30)
_YOUNG = _NOW - timedelta(days=10)


def _sweep_task(workspace_id: uuid.UUID) -> AnalyticsTask:
    """Fabricate the claimed queue row the executor receives (not persisted)."""
    return AnalyticsTask(
        workspace_id=workspace_id,
        project_id=None,  # the sweep is workspace-scoped
        task_kind=ANALYTICS_TASK_KIND_ORDER_RETENTION_SWEEP,
        payload={"sweep_key": "2026-07-26"},
        idempotency_key=uuid.uuid4().hex,
    )


async def _seed_fact(
    db_session: AsyncSession, graph: _Graph, *, occurred_at: datetime
) -> OrderFact:
    run, artifact = await _new_run_artifact(db_session, graph, _WINDOW_A)
    fact = OrderFact(
        workspace_id=graph.workspace_id,
        project_id=graph.project_id,
        connection_id=graph.connection.id,
        provider=INTEGRATION_PROVIDER_SHOPIFY,
        order_ref_hash=uuid.uuid4().hex,
        resync_seq=0,
        occurred_at=occurred_at,
        currency="USD",
        total_amount=Decimal("10.00"),
        line_items=[],
        attribution_keys={},
        source_artifact_id=artifact.id,
        importer_version="commerce-importer-1",
        order_sanitize_version="order-sanitize-1",
    )
    db_session.add(fact)
    await db_session.commit()
    return fact


@pytest.mark.asyncio
async def test_sweep_deletes_expired_facts_keeps_young_and_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = await _seed_graph(db_session)
    for _ in range(3):
        await _seed_fact(db_session, graph, occurred_at=_EXPIRED)
    young = await _seed_fact(db_session, graph, occurred_at=_YOUNG)
    # Force multiple batches (3 expired rows, 2 per batch).
    monkeypatch.setattr(order_module, "ORDER_RETENTION_DELETE_BATCH_SIZE", 2)

    await run_order_retention_sweep(session_factory, _sweep_task(graph.workspace_id))

    remaining = set((await db_session.scalars(select(OrderFact.id))).all())
    assert remaining == {young.id}

    # Idempotent re-run: nothing left past the horizon.
    await run_order_retention_sweep(session_factory, _sweep_task(graph.workspace_id))
    count = await db_session.scalar(select(func.count(OrderFact.id)))
    assert count == 1


@pytest.mark.asyncio
async def test_sweep_requires_a_sweep_key(
    session_factory: async_sessionmaker[AsyncSession], db_session: AsyncSession
) -> None:
    graph = await _seed_graph(db_session)
    task = _sweep_task(graph.workspace_id)
    task.payload = {}

    with pytest.raises(ValueError, match="sweep_key"):
        await run_order_retention_sweep(session_factory, task)
