"""Unit tests for T11 execution credential resolution (real Postgres).

Pins the resolver contract: BYOK precedence (a healthy, probed, unpaused
tenant route wins outright — even when funded proofs are present — and is
frozen with ``reservation_id=None``); paused/inactive/unprobed routes are
skipped; the platform credential requires the full funded proof chain (a
RESOLVED entitlement, a COMPLETE expected cost, a matching reservation, and
a healthy platform row in THE ONE system workspace) and every missing piece
fails closed with the coded ``execution_credentials_unavailable`` error —
never with a claimable task, never with key material in the message.
"""

from __future__ import annotations

import uuid
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.config.costs import ExpectedExecutionCost
from app.core.config.provider_catalog import (
    CODE_EXECUTION_CREDENTIALS_UNAVAILABLE,
    CREDENTIAL_SOURCE_BYOK,
    CREDENTIAL_SOURCE_PLATFORM,
    ENGINE_CLAUDE,
    ERROR_AUTH,
    TELEMETRY_BYOK_PAUSED,
    TELEMETRY_PLATFORM_AUTH_FAILED,
)
from app.domain.entitlements.ledger import Reservation
from app.domain.entitlements.types import (
    STATUS_RESOLVED,
    ResolvedEntitlement,
    no_capability_entitlement,
)
from app.domain.providers.credentials import (
    ExecutionCredentialsUnavailableError,
    ResolvedCredential,
    connection_paused,
    pause_connection_after_key_failure,
    resolve_execution_credentials,
)
from app.domain.workspaces.service import list_workspaces_for_user
from app.models.provider import ProviderConnection
from app.models.user import User
from app.models.workspace import WorkspaceMember
from tests.component.audit_helpers import (
    seed_audit_fixtures,
    seed_platform_connection,
)
from tests.component.log_capture import capture_log_messages

_AT = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)
_ACCOUNT_ID = uuid.uuid4()


def _complete_cost() -> ExpectedExecutionCost:
    return ExpectedExecutionCost(
        token_cost_microusd=2_890,
        search_fee_microusd=None,
        expected_searches=None,
        complete=True,
    )


def _resolved_entitlement(account_id: uuid.UUID = _ACCOUNT_ID) -> ResolvedEntitlement:
    return ResolvedEntitlement(
        account_id=account_id,
        registry_revision="test-rev",
        entitlement_lifecycle_version=1,
        resolved_at=_AT,
        valid_until=None,
        status=STATUS_RESOLVED,
        capabilities=(),
        errors=(),
    )


def _unresolved_entitlement() -> ResolvedEntitlement:
    return no_capability_entitlement(
        account_id=_ACCOUNT_ID,
        registry_revision="test-rev",
        entitlement_lifecycle_version=1,
        at=_AT,
    )


def _reservation(account_id: uuid.UUID = _ACCOUNT_ID) -> Reservation:
    return Reservation(
        reservation_id=uuid.uuid4(),
        billing_account_id=account_id,
        capability_key="audit_credits",
        audit_id=uuid.uuid4(),
        task_id=uuid.uuid4(),
        units=3,
        allocations=(),
    )


async def _tenant_connection(
    session: AsyncSession, workspace_id: uuid.UUID
) -> ProviderConnection:
    connection = await session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.workspace_id == workspace_id
        )
    )
    assert connection is not None
    return connection


async def test_byok_wins_even_with_funded_proofs_present(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=True)
        await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
        reservation = _reservation()
        credential = await resolve_execution_credentials(
            session,
            workspace_id=seed.workspace_id,
            account_id=_ACCOUNT_ID,
            logical_engine=ENGINE_CLAUDE,
            entitlement=_resolved_entitlement(),
            reservation=reservation,
            expected_cost=_complete_cost(),
            at=_AT,
        )
        connection = await _tenant_connection(session, seed.workspace_id)
        assert credential.credential_source == CREDENTIAL_SOURCE_BYOK
        assert credential.connection_id == connection.id
        assert credential.transport_provider == connection.transport_provider
        assert credential.model
        # BYOK never touches the ledger — even when a reservation exists.
        assert credential.reservation_id is None


async def test_unprobed_byok_falls_through_to_funded_platform(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=False)
        system = await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
        reservation = _reservation()
        credential = await resolve_execution_credentials(
            session,
            workspace_id=seed.workspace_id,
            account_id=_ACCOUNT_ID,
            logical_engine=ENGINE_CLAUDE,
            entitlement=_resolved_entitlement(),
            reservation=reservation,
            expected_cost=_complete_cost(),
            at=_AT,
        )
        platform_connection = await _tenant_connection(session, system.id)
        assert credential.credential_source == CREDENTIAL_SOURCE_PLATFORM
        assert credential.connection_id == platform_connection.id
        assert credential.transport_provider == platform_connection.transport_provider
        assert credential.model
        assert credential.reservation_id == reservation.reservation_id


async def test_inactive_byok_is_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=True)
        connection = await _tenant_connection(session, seed.workspace_id)
        connection.active = False
        await session.flush()
        await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
        credential = await resolve_execution_credentials(
            session,
            workspace_id=seed.workspace_id,
            account_id=_ACCOUNT_ID,
            logical_engine=ENGINE_CLAUDE,
            entitlement=_resolved_entitlement(),
            reservation=_reservation(),
            expected_cost=_complete_cost(),
            at=_AT,
        )
        assert credential.credential_source == CREDENTIAL_SOURCE_PLATFORM
        assert credential.connection_id != connection.id


async def test_paused_byok_is_skipped(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=True)
        connection = await _tenant_connection(session, seed.workspace_id)
        connection.paused_at = _AT
        connection.pause_reason = ERROR_AUTH
        await session.flush()
        await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
        credential = await resolve_execution_credentials(
            session,
            workspace_id=seed.workspace_id,
            account_id=_ACCOUNT_ID,
            logical_engine=ENGINE_CLAUDE,
            entitlement=_resolved_entitlement(),
            reservation=_reservation(),
            expected_cost=_complete_cost(),
            at=_AT,
        )
        assert credential.credential_source == CREDENTIAL_SOURCE_PLATFORM
        assert credential.connection_id != connection.id


async def test_expired_pause_lets_byok_win_again(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=True)
        connection = await _tenant_connection(session, seed.workspace_id)
        connection.paused_at = _AT - timedelta(days=1)
        connection.pause_reason = ERROR_AUTH
        connection.pause_until = _AT - timedelta(hours=1)
        await session.flush()
        credential = await resolve_execution_credentials(
            session,
            workspace_id=seed.workspace_id,
            account_id=None,
            logical_engine=ENGINE_CLAUDE,
            entitlement=_unresolved_entitlement(),
            reservation=None,
            expected_cost=ExpectedExecutionCost(
                token_cost_microusd=None,
                search_fee_microusd=None,
                expected_searches=None,
                complete=False,
            ),
            at=_AT,
        )
        assert credential.credential_source == CREDENTIAL_SOURCE_BYOK
        assert credential.connection_id == connection.id
        assert credential.reservation_id is None


def test_connection_paused_deadline_semantics() -> None:
    connection = ProviderConnection(
        workspace_id=uuid.uuid4(), transport_provider="anthropic"
    )
    assert connection_paused(connection, at=_AT) is False
    connection.paused_at = _AT
    # No deadline: the pause does not expire on its own.
    assert connection_paused(connection, at=_AT) is True
    connection.pause_until = _AT + timedelta(hours=1)
    assert connection_paused(connection, at=_AT) is True
    connection.pause_until = _AT - timedelta(hours=1)
    assert connection_paused(connection, at=_AT) is False
    # Exact boundary: the deadline has passed, resolution may retry.
    connection.pause_until = _AT
    assert connection_paused(connection, at=_AT) is False


async def test_funded_without_reservation_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=False)
        await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
        with pytest.raises(ExecutionCredentialsUnavailableError) as exc_info:
            await resolve_execution_credentials(
                session,
                workspace_id=seed.workspace_id,
                account_id=_ACCOUNT_ID,
                logical_engine=ENGINE_CLAUDE,
                entitlement=_resolved_entitlement(),
                reservation=None,
                expected_cost=_complete_cost(),
                at=_AT,
            )
        assert exc_info.value.code == CODE_EXECUTION_CREDENTIALS_UNAVAILABLE


async def test_funded_with_unresolved_entitlement_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=False)
        await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
        with pytest.raises(ExecutionCredentialsUnavailableError) as exc_info:
            await resolve_execution_credentials(
                session,
                workspace_id=seed.workspace_id,
                account_id=_ACCOUNT_ID,
                logical_engine=ENGINE_CLAUDE,
                entitlement=_unresolved_entitlement(),
                reservation=_reservation(),
                expected_cost=_complete_cost(),
                at=_AT,
            )
        assert exc_info.value.code == CODE_EXECUTION_CREDENTIALS_UNAVAILABLE


async def test_funded_with_incomplete_expected_cost_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=False)
        await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
        with pytest.raises(ExecutionCredentialsUnavailableError) as exc_info:
            await resolve_execution_credentials(
                session,
                workspace_id=seed.workspace_id,
                account_id=_ACCOUNT_ID,
                logical_engine=ENGINE_CLAUDE,
                entitlement=_resolved_entitlement(),
                reservation=_reservation(),
                expected_cost=ExpectedExecutionCost(
                    token_cost_microusd=2_890,
                    search_fee_microusd=None,
                    expected_searches=None,
                    complete=False,
                ),
                at=_AT,
            )
        assert exc_info.value.code == CODE_EXECUTION_CREDENTIALS_UNAVAILABLE


async def test_funded_with_account_mismatch_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=False)
        await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
        with pytest.raises(ExecutionCredentialsUnavailableError) as exc_info:
            await resolve_execution_credentials(
                session,
                workspace_id=seed.workspace_id,
                account_id=_ACCOUNT_ID,
                logical_engine=ENGINE_CLAUDE,
                entitlement=_resolved_entitlement(),
                reservation=_reservation(account_id=uuid.uuid4()),
                expected_cost=_complete_cost(),
                at=_AT,
            )
        assert exc_info.value.code == CODE_EXECUTION_CREDENTIALS_UNAVAILABLE


async def test_funded_without_platform_row_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=False)
        # Full funded proof chain but no system workspace at all.
        with pytest.raises(ExecutionCredentialsUnavailableError) as exc_info:
            await resolve_execution_credentials(
                session,
                workspace_id=seed.workspace_id,
                account_id=_ACCOUNT_ID,
                logical_engine=ENGINE_CLAUDE,
                entitlement=_resolved_entitlement(),
                reservation=_reservation(),
                expected_cost=_complete_cost(),
                at=_AT,
            )
        assert exc_info.value.code == CODE_EXECUTION_CREDENTIALS_UNAVAILABLE


async def test_no_credential_at_all_raises(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=False)
        with pytest.raises(ExecutionCredentialsUnavailableError) as exc_info:
            await resolve_execution_credentials(
                session,
                workspace_id=seed.workspace_id,
                account_id=None,
                logical_engine=ENGINE_CLAUDE,
                entitlement=_unresolved_entitlement(),
                reservation=None,
                expected_cost=_complete_cost(),
                at=_AT,
            )
        assert exc_info.value.code == CODE_EXECUTION_CREDENTIALS_UNAVAILABLE


async def test_error_message_and_details_carry_no_key_material(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=False)
        with pytest.raises(ExecutionCredentialsUnavailableError) as exc_info:
            await resolve_execution_credentials(
                session,
                workspace_id=seed.workspace_id,
                account_id=None,
                logical_engine=ENGINE_CLAUDE,
                entitlement=_unresolved_entitlement(),
                reservation=None,
                expected_cost=_complete_cost(),
                at=_AT,
            )
        error = exc_info.value
        assert error.code == "execution_credentials_unavailable"
        assert error.message == "No executable credential available for this task"
        assert error.details == {"logical_engine": ENGINE_CLAUDE}
        rendered = f"{error.message}{error.details}"
        assert "secret-test-key" not in rendered
        assert "platform" not in rendered


async def test_resolved_credential_is_frozen(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=True)
        credential = await resolve_execution_credentials(
            session,
            workspace_id=seed.workspace_id,
            account_id=None,
            logical_engine=ENGINE_CLAUDE,
            entitlement=_unresolved_entitlement(),
            reservation=None,
            expected_cost=_complete_cost(),
            at=_AT,
        )
        assert isinstance(credential, ResolvedCredential)
        with pytest.raises(FrozenInstanceError):
            credential.credential_source = CREDENTIAL_SOURCE_PLATFORM  # type: ignore[misc]
        with pytest.raises(FrozenInstanceError):
            credential.reservation_id = uuid.uuid4()  # type: ignore[misc]


# ---------------------------------------------------------------------------
# T11 stage D: pause writer, pause/resolution integration, dev-test-login gate
# ---------------------------------------------------------------------------


async def test_pause_writer_pauses_byok_and_emits_safe_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=True)
        connection = await _tenant_connection(session, seed.workspace_id)
        with capture_log_messages("app.providers") as events:
            await pause_connection_after_key_failure(session, connection.id, _AT)
        await session.commit()

    async with session_factory() as session:
        paused = await session.get(ProviderConnection, connection.id)
        assert paused is not None
        assert paused.paused_at == _AT
        # The safe classification token IS the recorded status (never raw
        # provider detail), and the grace deadline is the configured 7 days.
        assert paused.pause_reason == ERROR_AUTH
        assert paused.pause_until == _AT + timedelta(days=7)
        # Paused is a separate recoverable state from operator enablement.
        assert paused.active is True

    rendered = "\n".join(events)
    assert any(TELEMETRY_BYOK_PAUSED in message for message in events)
    assert not any(TELEMETRY_PLATFORM_AUTH_FAILED in message for message in events)
    # Safe payload: opaque connection id + pause timing; never key material.
    assert str(connection.id) in rendered
    assert "secret-test-key" not in rendered


async def test_pause_writer_pauses_platform_row_and_emits_platform_event(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        system = await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
        platform_connection = await session.scalar(
            select(ProviderConnection).where(
                ProviderConnection.workspace_id == system.id
            )
        )
        assert platform_connection is not None
        with capture_log_messages("app.providers") as events:
            await pause_connection_after_key_failure(
                session, platform_connection.id, _AT
            )
        await session.commit()
        assert platform_connection.paused_at == _AT
        assert platform_connection.pause_reason == ERROR_AUTH
        assert platform_connection.pause_until == _AT + timedelta(days=7)

    rendered = "\n".join(events)
    assert any(TELEMETRY_PLATFORM_AUTH_FAILED in message for message in events)
    assert not any(TELEMETRY_BYOK_PAUSED in message for message in events)
    assert "platform-secret-test-key" not in rendered


async def test_pause_writer_ignores_a_missing_connection(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with capture_log_messages("app.providers") as events:
            await pause_connection_after_key_failure(session, uuid.uuid4(), _AT)
        await session.commit()
    assert events == []


async def test_paused_connection_resolves_again_after_grace_deadline(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Pause/resolution integration: skipped while paused, eligible after.

    Follows the stage-C ``connection_paused`` semantics exactly: a pause with
    a future deadline is skipped; once ``pause_until`` has passed resolution
    treats the credential as eligible again (the row stays as provenance).
    """
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=True)
        connection = await _tenant_connection(session, seed.workspace_id)
        await pause_connection_after_key_failure(session, connection.id, _AT)
        await session.flush()
        await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))

        inside_grace = await resolve_execution_credentials(
            session,
            workspace_id=seed.workspace_id,
            account_id=_ACCOUNT_ID,
            logical_engine=ENGINE_CLAUDE,
            entitlement=_resolved_entitlement(),
            reservation=_reservation(),
            expected_cost=_complete_cost(),
            at=_AT + timedelta(days=1),
        )
        assert inside_grace.credential_source == CREDENTIAL_SOURCE_PLATFORM
        assert inside_grace.connection_id != connection.id

        after_grace = await resolve_execution_credentials(
            session,
            workspace_id=seed.workspace_id,
            account_id=None,
            logical_engine=ENGINE_CLAUDE,
            entitlement=_unresolved_entitlement(),
            reservation=None,
            expected_cost=ExpectedExecutionCost(
                token_cost_microusd=None,
                search_fee_microusd=None,
                expected_searches=None,
                complete=False,
            ),
            at=_AT + timedelta(days=8),
        )
        assert after_grace.credential_source == CREDENTIAL_SOURCE_BYOK
        assert after_grace.connection_id == connection.id
        assert after_grace.reservation_id is None


async def test_dev_test_login_cannot_resolve_platform_credentials_while_gate_closed(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate false (the default): the dev session fails CLOSED at the boundary.

    Full funded proofs do not help — the platform/system-workspace read is
    refused before it happens, and the reserved system workspace never shows
    up in the session's tenant workspace list either.
    """
    monkeypatch.setattr(settings, "dev_test_login_allow_platform_credentials", False)
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=False)
        system = await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
        with pytest.raises(ExecutionCredentialsUnavailableError) as exc_info:
            await resolve_execution_credentials(
                session,
                workspace_id=seed.workspace_id,
                account_id=_ACCOUNT_ID,
                logical_engine=ENGINE_CLAUDE,
                entitlement=_resolved_entitlement(),
                reservation=_reservation(),
                expected_cost=_complete_cost(),
                at=_AT,
                dev_test_login=True,
            )
        assert exc_info.value.code == CODE_EXECUTION_CREDENTIALS_UNAVAILABLE
        rendered = f"{exc_info.value.message}{exc_info.value.details}"
        assert "platform" not in rendered
        assert "system" not in rendered

        user = await session.scalar(
            select(User)
            .join(WorkspaceMember, WorkspaceMember.user_id == User.id)
            .where(WorkspaceMember.workspace_id == seed.workspace_id)
        )
        assert user is not None
        listed = await list_workspaces_for_user(session, user)
        assert all(workspace.id != system.id for workspace, _ in listed)


async def test_dev_test_login_resolves_platform_credentials_when_gate_open(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gate true (a development/test-only escape hatch): funded proofs apply."""
    monkeypatch.setattr(settings, "dev_test_login_allow_platform_credentials", True)
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=False)
        await seed_platform_connection(session, engines=(ENGINE_CLAUDE,))
        credential = await resolve_execution_credentials(
            session,
            workspace_id=seed.workspace_id,
            account_id=_ACCOUNT_ID,
            logical_engine=ENGINE_CLAUDE,
            entitlement=_resolved_entitlement(),
            reservation=_reservation(),
            expected_cost=_complete_cost(),
            at=_AT,
            dev_test_login=True,
        )
        assert credential.credential_source == CREDENTIAL_SOURCE_PLATFORM


async def test_dev_test_login_byok_resolution_is_not_gated(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The gate only guards the platform path: BYOK precedence is unaffected."""
    monkeypatch.setattr(settings, "dev_test_login_allow_platform_credentials", False)
    async with session_factory() as session:
        seed = await seed_audit_fixtures(session, engines=[ENGINE_CLAUDE], probed=True)
        connection = await _tenant_connection(session, seed.workspace_id)
        credential = await resolve_execution_credentials(
            session,
            workspace_id=seed.workspace_id,
            account_id=None,
            logical_engine=ENGINE_CLAUDE,
            entitlement=_unresolved_entitlement(),
            reservation=None,
            expected_cost=_complete_cost(),
            at=_AT,
            dev_test_login=True,
        )
        assert credential.credential_source == CREDENTIAL_SOURCE_BYOK
        assert credential.connection_id == connection.id
