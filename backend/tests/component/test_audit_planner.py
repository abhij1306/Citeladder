"""Planner: deterministic slot shuffle + cooperative cancel (invariants 9 + 3).

Exercises ``create_audit`` against a real Postgres schema:
  - a fixed seed reproduces the exact slot ordering (determinism);
  - one AuditTask is enqueued per (prompt x engine x repetition) slot with a
    stable idempotency key and frozen prompt/engine snapshots;
  - ``cancel_audit`` flips the audit to ``cancelled`` and terminalizes every
    non-terminal task so a live worker stops at its boundary.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.domain.audits.creation as creation_module
import app.domain.audits.funded_admission as funded_admission_module
from app.core.config.abuse import abuse_settings
from app.core.config.audits import (
    AUDIT_STATUS_CANCELLED,
    AUDIT_STATUS_QUEUED,
    AUDIT_TRIGGER_MANUAL,
    MEASUREMENT_MODE_BENCHMARK,
    MEASUREMENT_MODE_PULSE,
    MEASUREMENT_MODES,
    MEASUREMENT_POLICY_KEY,
    PULSE_ANSWER_INSTRUCTION,
    PULSE_ANSWER_INSTRUCTION_SHA256,
    TASK_STATUS_QUEUED,
    audit_settings,
    measurement_policy_from_configuration,
    system_instruction_for_mode,
)
from app.core.config.entitlements import (
    CREDENTIAL_MODE_FUNDED,
    KEY_PULSE_CREDITS,
    LEDGER_ENTRY_RELEASE,
    LEDGER_ENTRY_RESERVATION,
)
from app.core.config.projects import BENCHMARK_MODES
from app.core.config.provider_catalog import ENGINE_CLAUDE, route_policy
from app.domain.audits.cancellation import cancel_audit
from app.domain.audits.creation import create_audit
from app.domain.audits.errors import AuditValidationError
from app.domain.audits.reads import get_audit, list_tasks
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
        # Every planned task is a measurement-surface slot (§7.1).
        assert {t.shopping_surface for t in tasks} == {""}
        # Idempotency keys are unique + stable-shaped; the trailing empty
        # segment reserves the shopping-surface identity.
        keys = {t.idempotency_key for t in tasks}
        assert len(keys) == 6
        for task in tasks:
            assert task.idempotency_key == (
                f"{audit.id}:{task.prompt_index}:{task.repetition}:"
                f"{task.logical_engine}:{task.shopping_surface}"
            )
            assert task.idempotency_key.endswith(":")

        # The disabled surface gate freezes as an empty list; no surface
        # snapshot rows exist.
        assert audit.configuration["shopping_surfaces"] == []
        assert audit.shopping_surface_snapshots == []

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
            (t.prompt_index, t.repetition, t.logical_engine, t.shopping_surface)
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
            (t.prompt_index, t.repetition, t.logical_engine, t.shopping_surface)
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
    """The catalog is frozen into ``configuration`` at creation (invariant 9).

    The audit carries the frozen ``products``/``competitor_products`` identity
    next to ``scoring_identity``; a later catalog edit does not alter the
    already-created audit.
    """
    from decimal import Decimal

    from app.models.brand import Competitor
    from app.models.product import CompetitorProduct, Product

    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
    async with session_factory() as session:
        competitor = await session.scalar(
            select(Competitor).where(Competitor.project_id == seed.project_id)
        )
        assert competitor is not None
        session.add(
            Product(
                project_id=seed.project_id,
                sku="VC-EB500-GR",
                name="VoltCity Commuter 500",
                aliases=["VoltCity 500"],
                variants=[{"name": "Graphite", "sku": "VC-EB500-GR", "price": 2499.0}],
                price=Decimal("2499.00"),
                currency="USD",
                url="https://acme.com/p/vc500",
                attributes={"category": "footwear", "brand": "Voltaic"},
            )
        )
        session.add(
            CompetitorProduct(
                project_id=seed.project_id,
                competitor_id=competitor.id,
                name="Globex CityCommuter 450",
                price=Decimal("2399.00"),
                currency="USD",
            )
        )
        await session.commit()

    async with session_factory() as session:
        audit = await _create(session, seed, seed_value="7", reps=1)
        configuration = audit.configuration
        assert [p["sku"] for p in configuration["products"]] == ["VC-EB500-GR"]
        frozen = configuration["products"][0]
        assert frozen["name"] == "VoltCity Commuter 500"
        assert frozen["aliases"] == ["VoltCity 500"]
        assert frozen["price"] == 2499.0
        assert frozen["currency"] == "USD"
        assert frozen["id"]
        # The complete attribute bag freezes with the product identity.
        assert frozen["attributes"] == {"category": "footwear", "brand": "Voltaic"}
        competitor_products = configuration["competitor_products"]
        assert len(competitor_products) == 1
        assert competitor_products[0]["name"] == "Globex CityCommuter 450"
        assert competitor_products[0]["competitor_name"] == "Globex"
        # The brand scoring identity is untouched by the catalog freeze.
        assert configuration["brand_name"] == "Acme Corp"
        # The disabled shopping-surface gate freezes as an empty list and
        # creates no surface snapshot rows.
        assert configuration["shopping_surfaces"] == []
        assert audit.shopping_surface_snapshots == []

    # Later catalog edits never alter the frozen audit (deterministic
    # re-scoring, invariant 9).
    async with session_factory() as session:
        product = await session.scalar(
            select(Product).where(Product.project_id == seed.project_id)
        )
        assert product is not None
        product.price = Decimal("1999.00")
        product.name = "Renamed After Freeze"
        await session.commit()
    async with session_factory() as session:
        from app.domain.audits.reads import get_audit

        audit = await get_audit(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        frozen = audit.configuration["products"][0]
        assert frozen["price"] == 2499.0
        assert frozen["name"] == "VoltCity Commuter 500"


@pytest.mark.asyncio
async def test_create_audit_empty_catalog_freezes_empty_lists(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
    async with session_factory() as session:
        audit = await _create(session, seed, seed_value="7", reps=1)
        assert audit.configuration["products"] == []
        assert audit.configuration["competitor_products"] == []
        assert audit.configuration["shopping_surfaces"] == []


# ---------------------------------------------------------------------------
# Measurement-mode policy freezing (T3).
#
# ``measurement_mode`` (pulse | benchmark) selects the frozen route/output
# policy; ``benchmark_mode`` (consumer_like | controlled_localized |
# forced_grounded) selects the prompt framing. They are INDEPENDENT axes.
#
# The pulse answer instruction is an UNMEASURED CANDIDATE: no cost or latency
# figure anywhere is attributable to that wording until a live-key measurement
# run measures it. These tests pin the wording and the freezing, never a result.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_prompt_framing_and_measurement_modes_are_independent(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every (framing x measurement) combination composes; neither constrains
    the other."""
    # One workspace creates every combination in a row; the concurrency guard is
    # not what is under test here.
    monkeypatch.setattr(abuse_settings, "active_audits_per_workspace", 100)
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)

    combinations = [
        (framing, measurement)
        for framing in sorted(BENCHMARK_MODES)
        for measurement in sorted(MEASUREMENT_MODES)
    ]
    for framing, measurement in combinations:
        async with session_factory() as session:
            audit = await create_audit(
                session,
                trigger=AUDIT_TRIGGER_MANUAL,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=seed.engines,
                prompt_set_id=seed.prompt_set_id,
                repetitions=1,
                benchmark_mode=framing,
                measurement_mode=measurement,
                random_seed="5",
            )
            assert audit.benchmark_mode == framing
            assert audit.measurement_mode == measurement
            expected_framing = system_instruction_for_mode(
                mode=framing, country_code="AU", language_code="en-AU"
            )
            if expected_framing:
                assert audit.system_instruction.startswith(expected_framing)
            # The measurement axis contributes the answer-shaping addendum (and
            # only pulse has one); the framing axis is untouched by it.
            if measurement == MEASUREMENT_MODE_PULSE:
                assert audit.system_instruction.endswith(PULSE_ANSWER_INSTRUCTION)
            else:
                assert PULSE_ANSWER_INSTRUCTION not in audit.system_instruction


@pytest.mark.asyncio
async def test_pulse_answer_instruction_sha256_is_pinned() -> None:
    """The UNMEASURED CANDIDATE wording cannot drift silently.

    A drifted wording is a DIFFERENT, equally unmeasured candidate: the pinned
    digest forces the change to be deliberate. Nothing here asserts any cost or
    latency outcome for this string — it has never been executed against a live
    provider key.
    """
    digest = hashlib.sha256(PULSE_ANSWER_INSTRUCTION.encode("utf-8")).hexdigest()
    assert digest == PULSE_ANSWER_INSTRUCTION_SHA256


@pytest.mark.asyncio
async def test_full_frozen_configuration_for_pulse_mode(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The WHOLE measurement policy + trigger + route policy is frozen."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
    async with session_factory() as session:
        audit = await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            prompt_set_id=seed.prompt_set_id,
            measurement_mode=MEASUREMENT_MODE_PULSE,
            random_seed="9",
        )
        configuration = audit.configuration
        assert audit.trigger == AUDIT_TRIGGER_MANUAL
        assert configuration["trigger"] == AUDIT_TRIGGER_MANUAL
        assert configuration["measurement_mode"] == MEASUREMENT_MODE_PULSE
        assert configuration[MEASUREMENT_POLICY_KEY] == {
            "retrieval_enabled": False,
            "max_output_tokens": audit_settings.pulse_max_output_tokens,
            "timeout_seconds": audit_settings.pulse_timeout_seconds,
            "repetitions": audit_settings.pulse_repetitions,
            "answer_instruction": PULSE_ANSWER_INSTRUCTION,
        }
        # The frozen per-call timeout is the MODE's, not the generic live knob.
        assert (
            configuration["request_timeout_seconds"]
            == audit_settings.pulse_timeout_seconds
        )
        assert configuration["system_instruction"] == audit.system_instruction
        # The route policy is frozen alongside the route identity.
        engine = seed.engines[0]
        route = configuration["engine_routes"][engine]
        policy = route_policy(engine, MEASUREMENT_MODE_PULSE)
        assert route["reasoning_effort"] == policy.reasoning_effort
        assert route["reasoning_pinnable"] == policy.reasoning_pinnable
        assert route["representative_status"] == policy.representative_status
        assert route["batch_enabled"] == policy.batch_enabled

        # Every task carries the same frozen policy + route policy (no key).
        tasks = await list_tasks(
            session, workspace_id=seed.workspace_id, audit_id=audit.id
        )
        for task in tasks:
            snapshot = task.provider_route_snapshot
            assert snapshot["measurement_mode"] == MEASUREMENT_MODE_PULSE
            assert snapshot["retrieval_enabled"] is False
            assert snapshot["max_output_tokens"] == (
                audit_settings.pulse_max_output_tokens
            )
            assert snapshot["reasoning_effort"] == policy.reasoning_effort
            assert "api_key" not in snapshot
            assert "secret-test-key" not in str(snapshot)


@pytest.mark.asyncio
async def test_frozen_policy_is_never_reread_from_live_settings(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutating the live setting AFTER creation leaves the frozen value alone
    (invariant 9 — an env change must not alter an in-flight run)."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
    async with session_factory() as session:
        audit = await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            prompt_set_id=seed.prompt_set_id,
            measurement_mode=MEASUREMENT_MODE_PULSE,
            random_seed="9",
        )
        audit_id = audit.id
        frozen = dict(audit.configuration[MEASUREMENT_POLICY_KEY])

    monkeypatch.setattr(audit_settings, "pulse_max_output_tokens", 1)
    monkeypatch.setattr(audit_settings, "pulse_timeout_seconds", 999.0)

    async with session_factory() as session:
        reloaded = await get_audit(
            session, workspace_id=seed.workspace_id, audit_id=audit_id
        )
        assert reloaded.configuration[MEASUREMENT_POLICY_KEY] == frozen
        # And the worker reads the FROZEN copy back, not the mutated live knob.
        policy = measurement_policy_from_configuration(reloaded.configuration)
        assert policy.max_output_tokens == frozen["max_output_tokens"]
        assert policy.timeout_seconds == frozen["timeout_seconds"]


@pytest.mark.asyncio
async def test_default_repetitions_come_from_the_measurement_mode(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no explicit request, each mode contributes its own default reps."""
    monkeypatch.setattr(abuse_settings, "active_audits_per_workspace", 100)
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)

    expected = {
        MEASUREMENT_MODE_PULSE: audit_settings.pulse_repetitions,
        MEASUREMENT_MODE_BENCHMARK: audit_settings.benchmark_repetitions,
    }
    for mode, reps in expected.items():
        async with session_factory() as session:
            audit = await create_audit(
                session,
                trigger=AUDIT_TRIGGER_MANUAL,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=seed.engines,
                prompt_set_id=seed.prompt_set_id,
                measurement_mode=mode,
                random_seed="3",
            )
            assert audit.repetitions == reps
            assert audit.configuration["repetitions"] == reps

    # An explicit request still wins over the mode default.
    async with session_factory() as session:
        audit = await create_audit(
            session,
            trigger=AUDIT_TRIGGER_MANUAL,
            workspace_id=seed.workspace_id,
            project_id=seed.project_id,
            engines=seed.engines,
            prompt_set_id=seed.prompt_set_id,
            measurement_mode=MEASUREMENT_MODE_PULSE,
            repetitions=2,
            random_seed="3",
        )
        assert audit.repetitions == 2


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


@pytest.mark.asyncio
async def test_create_audit_rejects_an_unknown_measurement_mode(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Fails CLOSED: an unknown mode never silently gets a cheaper/costlier
    shape."""
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, prompt_count=1)
    async with session_factory() as session:
        with pytest.raises(AuditValidationError, match="measurement_mode"):
            await create_audit(
                session,
                trigger=AUDIT_TRIGGER_MANUAL,
                workspace_id=seed.workspace_id,
                project_id=seed.project_id,
                engines=seed.engines,
                prompt_set_id=seed.prompt_set_id,
                repetitions=1,
                measurement_mode="turbo",
            )


# ---------------------------------------------------------------------------
# T11: frozen execution-credential provenance
# ---------------------------------------------------------------------------


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
    """Tenant workspace (BYOK connection probed or not) + platform credential
    + a funded account with pulse credits."""
    seed = await seed_audit_fixtures(
        session, prompt_count=2, engines=[ENGINE_CLAUDE], probed=probed
    )
    system = await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
    account = await seed_occupancy_grants(
        session,
        workspace_id=seed.workspace_id,
        grants=(GrantSpec(key=KEY_PULSE_CREDITS, value=100),),
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
        measurement_mode=MEASUREMENT_MODE_PULSE,
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
