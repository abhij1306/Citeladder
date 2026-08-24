"""Planner: deterministic slot shuffle + cooperative cancel (invariants 9 + 3).

Exercises ``create_audit`` against a real Postgres schema:
  - a fixed seed reproduces the exact slot ordering (determinism);
  - one AuditTask is enqueued per (prompt x engine x repetition) slot with a
    stable idempotency key and frozen prompt/engine snapshots;
  - ``cancel_audit`` flips the audit to ``cancelled`` and terminalizes every
    non-terminal task so a live worker stops at its boundary.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.domain.audits.creation as creation_module
import app.domain.audits.funded_admission as funded_admission_module
from app.core.config.audits import (
    AUDIT_STATUS_CANCELLED,
    AUDIT_STATUS_QUEUED,
    AUDIT_TRIGGER_MANUAL,
    audit_settings,
)
from app.core.config.entitlements import (
    CREDENTIAL_MODE_FUNDED,
    KEY_AUDIT_CREDITS,
    LEDGER_ENTRY_RELEASE,
    LEDGER_ENTRY_RESERVATION,
)
from app.core.config.provider_catalog import ENGINE_CLAUDE
from app.core.config.task_queue import TASK_STATUS_QUEUED
from app.domain.audits.cancellation import cancel_audit
from app.domain.audits.creation import create_audit
from app.domain.audits.errors import AuditValidationError
from app.domain.audits.reads import list_tasks
from app.domain.entitlements.cache import clear_cache
from app.domain.entitlements.types import GrantSpec
from app.models.audit import AuditEngineSnapshot, AuditPromptSnapshot, AuditTask
from app.models.billing import ConsumableLedger
from app.models.prompt import Prompt
from app.models.provider import ProviderConnection
from tests.component.audit_helpers import (
    seed_audit_fixtures,
    seed_platform_connection,
)
from tests.component.occupancy_helpers import seed_occupancy_grants


async def _create(
    session: AsyncSession, seed, *, seed_value: str | None = None, reps: int = 2
):
    return await create_audit(
        session,
        trigger=AUDIT_TRIGGER_MANUAL,
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        engines=seed.engines,
        prompt_set_id=seed.prompt_set_id,
        repetitions=reps,
        random_seed=seed_value,
    )


@pytest.mark.asyncio
async def test_create_audit_enqueues_one_task_per_slot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=3)
    async with session_factory() as session:
        audit = await _create(session, seed, seed_value="12345", reps=2)

        assert audit.status == AUDIT_STATUS_QUEUED
        # 3 prompts x 1 engine x 2 reps = 6 tasks.
        assert audit.requested_count == 6

        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert len(tasks) == 6
        assert {t.status for t in tasks} == {TASK_STATUS_QUEUED}
        # Idempotency keys are unique and stable-shaped.
        keys = {t.idempotency_key for t in tasks}
        assert len(keys) == 6
        for task in tasks:
            assert task.idempotency_key == (
                f"{audit.id}:{task.prompt_index}:{task.repetition}:"
                f"{task.logical_engine}"
            )

        # Snapshots frozen.
        prompts = (
            await session.scalars(
                select(AuditPromptSnapshot).where(
                    AuditPromptSnapshot.audit_id == audit.id
                )
            )
        ).all()
        assert len(prompts) == 3
        engines = (
            await session.scalars(
                select(AuditEngineSnapshot).where(
                    AuditEngineSnapshot.audit_id == audit.id
                )
            )
        ).all()
        assert len(engines) == 1


@pytest.mark.asyncio
async def test_fixed_seed_reproduces_slot_order(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed_a = await seed_audit_fixtures(
            session, prompt_count=4, email="a@example.com"
        )
    async with session_factory() as session:
        seed_b = await seed_audit_fixtures(
            session, prompt_count=4, email="b@example.com"
        )

    async with session_factory() as session:
        audit_a = await _create(session, seed_a, seed_value="99", reps=3)
        order_a = [
            (t.prompt_index, t.repetition, t.logical_engine)
            for t in sorted(
                await list_tasks(
                    session,
                    workspace_id=seed_a.workspace_id,
                    audit_id=audit_a.id,
                ),
                key=lambda t: t.randomized_position,
            )
        ]
    async with session_factory() as session:
        audit_b = await _create(session, seed_b, seed_value="99", reps=3)
        order_b = [
            (t.prompt_index, t.repetition, t.logical_engine)
            for t in sorted(
                await list_tasks(
                    session,
                    workspace_id=seed_b.workspace_id,
                    audit_id=audit_b.id,
                ),
                key=lambda t: t.randomized_position,
            )
        ]

    # Same seed -> identical shuffle order (determinism, invariant 9).
    assert order_a == order_b
    # Stored seed is preserved for replay.
    assert audit_a.random_seed == "99"


@pytest.mark.asyncio
async def test_cancel_audit_terminalizes_open_tasks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=2)
    async with session_factory() as session:
        audit = await _create(session, seed, seed_value="7", reps=2)

        cancelled = await cancel_audit(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert cancelled.status == AUDIT_STATUS_CANCELLED

        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        assert {t.status for t in tasks} == {"cancelled"}
        assert all(t.lease_owner is None for t in tasks)

        # Cancelling a terminal audit is rejected.
        with pytest.raises(AuditValidationError):
            await cancel_audit(
                session, workspace_id=seed.workspace_id, audit_id=audit.id
            )


@pytest.mark.asyncio
async def test_create_audit_rejects_engine_without_route(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1, engines=["gemini"])
    async with session_factory() as session:
        with pytest.raises(AuditValidationError):
            await create_audit(
                session,
                trigger=AUDIT_TRIGGER_MANUAL,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=["claude"],  # no route configured
                prompt_set_id=seed.prompt_set_id,
                repetitions=1,
            )


@pytest.mark.asyncio
async def test_create_audit_ignores_inactive_legacy_route(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A retired (inactive) legacy route must not resolve for a new audit.

    Even though the connection is active, an ``active=false`` retired route
    is excluded by the planner, so the engine has no usable route.
    """
    from app.models.provider import ProviderConnection, ProviderRoute

    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1, engines=["gemini"])

    async with session_factory() as session:
        connection = ProviderConnection(
            workspace_id=seed.workspace_id,
            label="Retired transport",
            transport_provider="retired",
            api_key_encrypted="x",
            active=True,
        )
        session.add(connection)
        await session.flush()
        session.add(
            ProviderRoute(
                workspace_id=seed.workspace_id,
                connection_id=connection.id,
                logical_engine="chatgpt",
                transport_provider="retired",
                transport_model="openai/gpt-5.4",
                is_default=True,
                active=False,
                deactivation_reason="transport_retired",
            )
        )
        await session.commit()

    async with session_factory() as session:
        with pytest.raises(AuditValidationError):
            await create_audit(
                session,
                trigger=AUDIT_TRIGGER_MANUAL,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=["chatgpt"],  # only a retired route exists
                prompt_set_id=seed.prompt_set_id,
                repetitions=1,
            )


@pytest.mark.asyncio
async def test_create_audit_rejects_unknown_or_disabled_prompt_ids(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    import uuid

    from sqlalchemy import select

    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=3)

    # Disable one of the seeded prompts.
    async with session_factory() as session:
        disabled_id = seed.prompt_ids[0]
        prompt = await session.get(Prompt, disabled_id)
        assert prompt is not None
        prompt.enabled = False
        await session.commit()

    # A request that includes the disabled prompt is rejected, not silently
    # narrowed to the enabled subset.
    async with session_factory() as session:
        with pytest.raises(AuditValidationError):
            await create_audit(
                session,
                trigger=AUDIT_TRIGGER_MANUAL,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=seed.engines,
                prompt_ids=seed.prompt_ids,  # includes the disabled one
                repetitions=1,
            )

    # A request that references a completely unknown id is also rejected.
    async with session_factory() as session:
        with pytest.raises(AuditValidationError):
            await create_audit(
                session,
                trigger=AUDIT_TRIGGER_MANUAL,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=seed.engines,
                prompt_ids=[seed.prompt_ids[1], uuid.uuid4()],
                repetitions=1,
            )

    # Sanity: an explicit list of only enabled, in-project ids still works.
    async with session_factory() as session:
        enabled = (
            await session.scalars(
                select(Prompt.id)
                .join(Prompt.prompt_set)
                .where(Prompt.enabled.is_(True))
            )
        ).all()
        audit = await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            prompt_ids=[seed.prompt_ids[1], seed.prompt_ids[2]],
            repetitions=1,
        )
        assert audit.requested_count == 2
        assert len(enabled) == 2


@pytest.mark.asyncio
async def test_create_audit_freezes_product_catalog(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from app.models.product import Product

    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
        session.add(
            Product(
                project_id=seed.project_id,
                sku="AC-500",
                name="Acme VoltBike 500",
                aliases=["VoltBike"],
                price=2499,
                currency="USD",
                url="https://acme.test/products/500",
                attributes={"category": "E-Bikes"},
            )
        )
        await session.commit()
    async with session_factory() as session:
        audit = await _create(session, seed, seed_value="catalog", reps=1)
        products = audit.configuration["products"]
        assert len(products) == 1
        assert products[0]["sku"] == "AC-500"
        assert products[0]["attributes"]["category"] == "E-Bikes"


@pytest.mark.asyncio
async def test_create_audit_empty_catalog_freezes_empty_lists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
    async with session_factory() as session:
        audit = await _create(session, seed, seed_value="7", reps=1)
        assert audit.configuration["products"] == []


# ---------------------------------------------------------------------------
# Single audit-policy planner boundaries.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_audit_rejects_a_prompt_over_the_max_length(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The prompt-length ceiling is config-owned and enforced by the planner."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
    async with session_factory() as session:
        prompt = await session.get(Prompt, seed.prompt_ids[0])
        assert prompt is not None
        prompt.text = "x" * (audit_settings.max_prompt_chars + 1)
        await session.commit()
    async with session_factory() as session:
        with pytest.raises(AuditValidationError, match="maximum length"):
            await create_audit(
                session,
                trigger=AUDIT_TRIGGER_MANUAL,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=seed.engines,
                prompt_set_id=seed.prompt_set_id,
                repetitions=1,
            )


@pytest.fixture(autouse=True)
def _clear_entitlement_cache():
    clear_cache()
    yield
    clear_cache()


async def _tasks(session: AsyncSession, audit_id) -> list[AuditTask]:
    return list(
        (
            await session.scalars(
                select(AuditTask).where(AuditTask.audit_id == audit_id)
            )
        ).all()
    )


async def _seed_funded_workspace(session: AsyncSession, *, probed: bool):
    seed = await seed_audit_fixtures(
        session, prompt_count=2, engines=[ENGINE_CLAUDE], probed=probed
    )
    system = await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
    account = await seed_occupancy_grants(
        session,
        workspace_id=seed.workspace_id,
        grants=(GrantSpec(key=KEY_AUDIT_CREDITS, value=100),),
    )
    await session.commit()
    return seed, system, account


async def _create_funded_claude(session: AsyncSession, seed) -> object:
    return await create_audit(
        session,
        trigger=AUDIT_TRIGGER_MANUAL,
        workspace_id=seed.workspace_id,
        project_id=seed.project_id,
        engines=[ENGINE_CLAUDE],
        prompt_set_id=seed.prompt_set_id,
        repetitions=1,
        credential_mode=CREDENTIAL_MODE_FUNDED,
        random_seed="1",
    )


@pytest.mark.asyncio
async def test_byok_run_freezes_credential_identity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(
            session, prompt_count=2, engines=[ENGINE_CLAUDE]
        )
        connection = await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.workspace_id == seed.workspace_id
            )
        )
        assert connection is not None
        audit = await _create(session, seed, seed_value="7", reps=1)

        configuration = audit.configuration or {}
        engine_route = configuration["engine_routes"][ENGINE_CLAUDE]
        assert engine_route["credential_source"] == "byok"
        assert engine_route["connection_id"] == str(connection.id)
        # BYOK runs carry no funded provenance at all.
        assert "funding" not in configuration
        assert "task_reservations" not in configuration

        tasks = await _tasks(session, audit.id)
        assert len(tasks) == 2
        task_credentials = configuration["task_credentials"]
        assert set(task_credentials) == {str(task.id) for task in tasks}
        for task in tasks:
            snapshot = task.provider_route_snapshot or {}
            assert snapshot["credential_source"] == "byok"
            assert snapshot["connection_id"] == str(connection.id)
            assert snapshot["reservation_id"] is None
            assert "funding" not in snapshot
            assert task_credentials[str(task.id)] == {
                "credential_source": "byok",
                "connection_id": str(connection.id),
                "reservation_id": None,
            }
        # The engine snapshot row records the same concrete connection.
        engine_snapshot = await session.scalar(
            select(AuditEngineSnapshot).where(AuditEngineSnapshot.audit_id == audit.id)
        )
        assert engine_snapshot is not None
        assert engine_snapshot.connection_id == connection.id


@pytest.mark.asyncio
async def test_funded_run_freezes_platform_credential_identity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed, system, account = await _seed_funded_workspace(session, probed=False)
        platform_connection = await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.workspace_id == system.id
            )
        )
        assert platform_connection is not None
        audit = await _create_funded_claude(session, seed)

        configuration = audit.configuration or {}
        engine_route = configuration["engine_routes"][ENGINE_CLAUDE]
        assert engine_route["credential_source"] == "platform"
        assert engine_route["connection_id"] == str(platform_connection.id)

        tasks = await _tasks(session, audit.id)
        assert len(tasks) == 2
        task_reservations = configuration["task_reservations"]
        task_credentials = configuration["task_credentials"]
        assert set(task_reservations) == {str(task.id) for task in tasks}
        assert set(task_credentials) == {str(task.id) for task in tasks}
        for task in tasks:
            assert task.status == TASK_STATUS_QUEUED
            snapshot = task.provider_route_snapshot or {}
            assert snapshot["credential_source"] == "platform"
            assert snapshot["connection_id"] == str(platform_connection.id)
            reservation_id = task_reservations[str(task.id)]
            assert snapshot["reservation_id"] == reservation_id
            funding = snapshot.get("funding") or {}
            assert funding["reservation_id"] == reservation_id
            assert funding["funding_account_id"] == str(account.id)
            assert task_credentials[str(task.id)] == {
                "credential_source": "platform",
                "connection_id": str(platform_connection.id),
                "reservation_id": reservation_id,
            }
        engine_snapshot = await session.scalar(
            select(AuditEngineSnapshot).where(AuditEngineSnapshot.audit_id == audit.id)
        )
        assert engine_snapshot is not None
        assert engine_snapshot.connection_id == platform_connection.id


@pytest.mark.asyncio
async def test_funded_request_with_healthy_byok_executes_byok_and_releases(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """BYOK precedence is frozen at admission: a funded REQUEST with a healthy
    probed tenant BYOK route executes BYOK, and the just-made reservation is
    released in the same transaction (no stranded credits, no funded
    fallback)."""
    async with session_factory() as session:
        seed, _system, _account = await _seed_funded_workspace(session, probed=True)
        connection = await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.workspace_id == seed.workspace_id
            )
        )
        assert connection is not None
        audit = await _create_funded_claude(session, seed)

        configuration = audit.configuration or {}
        tasks = await _tasks(session, audit.id)
        assert len(tasks) == 2
        # Every task froze BYOK: no task-reservation map entries, no funding
        # block on any task snapshot.
        assert (configuration.get("task_reservations") or {}) == {}
        for task in tasks:
            assert task.status == TASK_STATUS_QUEUED
            snapshot = task.provider_route_snapshot or {}
            assert snapshot["credential_source"] == "byok"
            assert snapshot["connection_id"] == str(connection.id)
            assert snapshot["reservation_id"] is None
            assert "funding" not in snapshot
            assert configuration["task_credentials"][str(task.id)] == {
                "credential_source": "byok",
                "connection_id": str(connection.id),
                "reservation_id": None,
            }
        # The reservations were made then released in the same transaction:
        # per reservation id, reserved units == released units (no debits).
        ledger_rows = list(
            (
                await session.scalars(
                    select(ConsumableLedger).where(
                        ConsumableLedger.audit_id == audit.id
                    )
                )
            ).all()
        )
        reserved: dict[object, int] = {}
        released: dict[object, int] = {}
        for row in ledger_rows:
            if row.entry_kind == LEDGER_ENTRY_RESERVATION:
                bucket = reserved
            elif row.entry_kind == LEDGER_ENTRY_RELEASE:
                bucket = released
            else:
                raise AssertionError(f"unexpected ledger entry {row.entry_kind}")
            bucket[row.reservation_id] = bucket.get(row.reservation_id, 0) + row.units
        assert len(reserved) == len(tasks)
        assert reserved == released


@pytest.mark.asyncio
async def test_admission_at_is_one_shared_instant_everywhere(
    session_factory: async_sessionmaker[AsyncSession], monkeypatch
) -> None:
    """The planner reads the clock ONCE: the exact ``admission_at`` instant
    flows UNCHANGED into entitlement resolution and the frozen configuration
    (a boundary-exact clock never shifts between readers)."""
    fixed = datetime.now(UTC).replace(microsecond=0) + timedelta(hours=1)

    class _StubDatetime:
        @classmethod
        def now(cls, tz=None):
            assert tz is UTC
            return fixed

    monkeypatch.setattr(creation_module, "datetime", _StubDatetime)
    captured: dict[str, datetime] = {}
    real_resolve = funded_admission_module.resolve_workspace_entitlement

    async def _spy(session, *, workspace_id, at):
        captured["at"] = at
        return await real_resolve(session, workspace_id=workspace_id, at=at)

    monkeypatch.setattr(funded_admission_module, "resolve_workspace_entitlement", _spy)

    async with session_factory() as session:
        seed, _system, _account = await _seed_funded_workspace(session, probed=False)
        audit = await _create_funded_claude(session, seed)

        assert captured["at"] == fixed
        funding = (audit.configuration or {})["funding"]
        assert funding["admission_at"] == fixed.isoformat()
        assert audit.funded_budget_period_start == fixed.replace(
            day=1, hour=0, minute=0, second=0, microsecond=0
        )
