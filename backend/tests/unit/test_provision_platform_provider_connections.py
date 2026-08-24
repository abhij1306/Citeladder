"""Provisioning CLI internals (T11 stage D): platform connections (real Postgres).

Pins the operator provisioning contract: the ONE system workspace is
created/loaded and platform connections/routes converge per transport;
re-runs are idempotent and rotations replace the ciphertext (and clear an
auth-failure pause); a missing/default Fernet key fails CLOSED before any
write; ``dry_run`` writes nothing; the database stores ciphertext only; and
the report + ``provider.platform.provisioned`` telemetry carry transport/row
ids/status — never secret material.
"""

from __future__ import annotations

import uuid

import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import settings
from app.core.config.provider_catalog import (
    CREDENTIAL_SOURCE_PLATFORM,
    ENGINE_CLAUDE,
    ENGINE_GEMINI,
    MEASUREMENT_ROUTES,
    TELEMETRY_PLATFORM_PROVISIONED,
    TRANSPORT_ANTHROPIC,
    TRANSPORT_GOOGLE,
    TRANSPORT_OPENAI,
)
from app.core.security import decrypt_secret
from app.models.provider import ProviderConnection, ProviderRoute
from app.models.workspace import Workspace
from scripts.provision_platform_provider_connections import (
    PlatformConnectionReport,
    PlatformProvisioningError,
    provision_platform_connections,
)
from tests.component.log_capture import capture_log_messages

_VALID_ENCRYPTION_KEY = "provision-test-encryption-key-0123456789abcdef"
_OPENAI_KEY = "test-openai-platform-key-9f8e7d6c"
_ANTHROPIC_KEY = "test-anthropic-platform-key-1a2b3c4d"
_GOOGLE_KEY = "test-google-platform-key-5e6f7a8b"
_ROTATED_OPENAI_KEY = "test-openai-platform-key-ROTATED-0z9y8x"

_ALL_KEYS = (_OPENAI_KEY, _ANTHROPIC_KEY, _GOOGLE_KEY, _ROTATED_OPENAI_KEY)


@pytest.fixture(autouse=True)
def _configured_encryption_key(monkeypatch: pytest.MonkeyPatch):
    """A really-configured Fernet key (the placeholder default fails closed)."""
    monkeypatch.setattr(settings, "encryption_key", _VALID_ENCRYPTION_KEY)


def _credentials(openai: str = _OPENAI_KEY) -> dict[str, SecretStr]:
    return {
        TRANSPORT_OPENAI: SecretStr(openai),
        TRANSPORT_ANTHROPIC: SecretStr(_ANTHROPIC_KEY),
        TRANSPORT_GOOGLE: SecretStr(_GOOGLE_KEY),
    }


async def _platform_connections(
    session: AsyncSession,
) -> list[ProviderConnection]:
    result = await session.execute(
        select(ProviderConnection).where(
            ProviderConnection.credential_source == CREDENTIAL_SOURCE_PLATFORM
        )
    )
    return list(result.scalars())


async def test_provision_creates_system_workspace_connections_and_routes(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with capture_log_messages("app.providers") as events:
            reports = await provision_platform_connections(
                session, credentials=_credentials()
            )

        assert {r.transport_provider for r in reports} == {
            TRANSPORT_OPENAI,
            TRANSPORT_ANTHROPIC,
            TRANSPORT_GOOGLE,
        }
        assert all(r.status == "created" for r in reports)
        assert all(r.connection_id is not None for r in reports)

        system = await session.scalar(
            select(Workspace).where(Workspace.is_system.is_(True))
        )
        assert system is not None
        connections = await _platform_connections(session)
        assert len(connections) == 3
        assert all(c.workspace_id == system.id for c in connections)
        assert all(c.active for c in connections)
        assert {r.connection_id for r in reports} == {c.id for c in connections}

        # One catalog-default route per engine on the matching transport.
        routes = (await session.execute(select(ProviderRoute))).scalars().all()
        for engine, approved in MEASUREMENT_ROUTES.items():
            route = next(r for r in routes if r.logical_engine == engine)
            assert route.transport_provider == approved.transport_provider
            assert route.transport_model == approved.transport_model
            assert route.is_default is True
            assert route.workspace_id == system.id

    # Telemetry carries transport/row ids/status only — never secret material.
    provisioned = [m for m in events if TELEMETRY_PLATFORM_PROVISIONED in m]
    assert len(provisioned) == 3
    rendered = "\n".join(events)
    for secret in _ALL_KEYS:
        assert secret not in rendered


async def test_provision_is_idempotent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        first = await provision_platform_connections(
            session, credentials=_credentials()
        )
    async with session_factory() as session:
        second = await provision_platform_connections(
            session, credentials=_credentials()
        )
        assert [r.connection_id for r in second] == [r.connection_id for r in first]
        assert all(r.status == "unchanged" for r in second)

        # Converged: exactly one system workspace + one row per transport.
        systems = await session.scalar(
            select(func.count()).select_from(Workspace).where(Workspace.is_system)
        )
        assert systems == 1
        assert len(await _platform_connections(session)) == 3


async def test_rotation_replaces_ciphertext_and_clears_pause(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from datetime import UTC, datetime

    async with session_factory() as session:
        first = await provision_platform_connections(
            session, credentials=_credentials()
        )
        connection_id = next(
            r for r in first if r.transport_provider == TRANSPORT_OPENAI
        ).connection_id

    async with session_factory() as session:
        connection = await session.get(ProviderConnection, connection_id)
        assert connection is not None
        assert connection.transport_provider == TRANSPORT_OPENAI
        old_ciphertext = connection.api_key_encrypted
        # Simulate the worker's auth-failure pause (T11 stage D).
        connection.paused_at = datetime.now(UTC)
        connection.pause_reason = "auth_failure"
        connection.pause_until = datetime.now(UTC)
        await session.commit()

    async with session_factory() as session:
        rotated = await provision_platform_connections(
            session, credentials=_credentials(openai=_ROTATED_OPENAI_KEY)
        )
        report = next(r for r in rotated if r.transport_provider == TRANSPORT_OPENAI)
        assert report.status == "rotated"
        assert report.connection_id == connection_id

        connection = await session.get(ProviderConnection, connection_id)
        assert connection is not None
        assert connection.api_key_encrypted != old_ciphertext
        assert decrypt_secret(connection.api_key_encrypted) == _ROTATED_OPENAI_KEY
        # The rotation fixes the auth failure, so the grace pause is cleared.
        assert connection.paused_at is None
        assert connection.pause_reason == ""
        assert connection.pause_until is None


async def test_missing_fernet_key_is_rejected_before_any_write(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        settings, "encryption_key", "replace-with-32-byte-minimum-secret"
    )
    async with session_factory() as session:
        with pytest.raises(PlatformProvisioningError):
            await provision_platform_connections(session, credentials=_credentials())
        await session.rollback()

    async with session_factory() as session:
        assert (
            await session.scalar(select(Workspace).where(Workspace.is_system.is_(True)))
            is None
        )
        assert await _platform_connections(session) == []


async def test_empty_encryption_key_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "encryption_key", "")
    async with session_factory() as session:
        with pytest.raises(PlatformProvisioningError):
            await provision_platform_connections(session, credentials=_credentials())
        await session.rollback()


async def test_dry_run_writes_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        reports = await provision_platform_connections(
            session, credentials=_credentials(), dry_run=True
        )
        assert all(r.status == "created" for r in reports)
        assert all(r.connection_id is not None for r in reports)

    async with session_factory() as session:
        assert (
            await session.scalar(select(Workspace).where(Workspace.is_system.is_(True)))
            is None
        )
        assert await _platform_connections(session) == []
        assert (await session.execute(select(ProviderRoute))).scalars().all() == []


async def test_database_stores_ciphertext_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        await provision_platform_connections(session, credentials=_credentials())
        connections = await _platform_connections(session)
        assert connections
        for connection in connections:
            stored = connection.api_key_encrypted
            for secret in _ALL_KEYS:
                assert secret not in stored
            assert decrypt_secret(stored) in _ALL_KEYS


async def test_report_carries_ids_and_status_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        reports = await provision_platform_connections(
            session, credentials=_credentials()
        )
    for report in reports:
        assert isinstance(report, PlatformConnectionReport)
        assert isinstance(report.connection_id, uuid.UUID)
        assert report.status in {"created", "rotated", "unchanged"}
        rendered = str(report)
        for secret in _ALL_KEYS:
            assert secret not in rendered


async def test_unknown_transport_is_rejected(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        with pytest.raises(PlatformProvisioningError):
            await provision_platform_connections(
                session,
                credentials={**_credentials(), "mistral": SecretStr("nope")},
            )
        await session.rollback()


async def test_single_transport_provisions_independently(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory() as session:
        reports = await provision_platform_connections(
            session, credentials={TRANSPORT_ANTHROPIC: SecretStr(_ANTHROPIC_KEY)}
        )
        assert len(reports) == 1
        assert reports[0].transport_provider == TRANSPORT_ANTHROPIC
        connection = await session.get(ProviderConnection, reports[0].connection_id)
        assert connection is not None
        assert connection.transport_provider == TRANSPORT_ANTHROPIC
        routes = (await session.execute(select(ProviderRoute))).scalars().all()
        assert {r.logical_engine for r in routes} == {ENGINE_CLAUDE}
        assert ENGINE_GEMINI not in {r.logical_engine for r in routes}
