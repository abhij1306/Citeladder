"""Operator CLI: provision the platform-funded provider connections (T11).

Creates/loads THE ONE reserved system workspace and upserts one platform
connection per transport (``openai``/``anthropic``/``google`` from the
approved-route catalog) plus its catalog-default routes. These rows are what
funded execution resolves after the planner's funded proofs — tenant sessions
never see them (system workspace, ``credential_source="platform"``).

Secret handling (invariant 6):

- keys are accepted ONLY as ``SecretStr`` (from the process environment or a
  dotenv-style ``--env-file`` — never on argv);
- each key is Fernet-encrypted BEFORE flush; the database stores ciphertext
  only;
- no key, plaintext or ciphertext, is ever printed or logged — the report
  carries transport, opaque row ids, and status tokens only;
- the run FAILS CLOSED when ``ENCRYPTION_KEY`` is missing (the shipped
  placeholder default counts as missing).

The script is idempotent (a re-run converges to the same rows), supports
rotation (a new key replaces the ciphertext and clears any auth-failure
pause), and ``--dry-run`` reports the converged state while writing nothing.
It is a CLI only: nothing here is wired into a worker or scheduler, and no
adapter reads key material from this path.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import encryption_key_configured, settings
from app.core.config.provider_catalog import (
    ACTIVE_TRANSPORTS,
    CREDENTIAL_SOURCE_PLATFORM,
    PLATFORM_CREDENTIAL_ENV_VARS,
    SYSTEM_WORKSPACE_NAME,
    TELEMETRY_PLATFORM_PROVISIONED,
    engines_for_transport,
    measurement_route,
)
from app.core.database import SessionLocal
from app.core.security import decrypt_secret, encrypt_secret
from app.models.provider import ProviderConnection, ProviderRoute
from app.models.workspace import Workspace

# Operator telemetry for provisioning (safe fields only — invariant 6).
logger = logging.getLogger("app.providers")

_STATUS_CREATED: Final = "created"
_STATUS_ROTATED: Final = "rotated"
_STATUS_UNCHANGED: Final = "unchanged"


class PlatformProvisioningError(RuntimeError):
    """Fail-closed provisioning refusal (missing Fernet key / bad input).

    The message names the safe reason only — never any secret material.
    """


@dataclass(frozen=True, slots=True)
class PlatformConnectionReport:
    """One transport's provisioning outcome (transport/row id/status ONLY)."""

    transport_provider: str
    connection_id: uuid.UUID | None
    status: str


async def _load_system_workspace(session: AsyncSession) -> Workspace:
    """Load or create THE ONE system workspace (partial unique index)."""
    system = await session.scalar(
        select(Workspace).where(Workspace.is_system.is_(True))
    )
    if system is None:
        system = Workspace(name=SYSTEM_WORKSPACE_NAME, is_system=True)
        session.add(system)
        await session.flush()
    return system


async def _upsert_connection(
    session: AsyncSession,
    *,
    system_workspace_id: uuid.UUID,
    transport: str,
    secret: SecretStr,
) -> tuple[ProviderConnection, str]:
    """Create or rotate one transport's platform connection; report status.

    Rotation replaces the ciphertext (Fernet is non-deterministic, so
    same-key detection decrypts the stored row — the plaintext never leaves
    this function) and clears any auth-failure pause: the operator rotated
    the key BECAUSE the old one failed, so the grace pause no longer applies.
    """
    connection = await session.scalar(
        select(ProviderConnection).where(
            ProviderConnection.workspace_id == system_workspace_id,
            ProviderConnection.credential_source == CREDENTIAL_SOURCE_PLATFORM,
            ProviderConnection.transport_provider == transport,
        )
    )
    ciphertext = encrypt_secret(secret.get_secret_value())
    if connection is None:
        connection = ProviderConnection(
            workspace_id=system_workspace_id,
            label=f"platform {transport} key",
            transport_provider=transport,
            credential_source=CREDENTIAL_SOURCE_PLATFORM,
            api_key_encrypted=ciphertext,
            active=True,
        )
        session.add(connection)
        await session.flush()
        return connection, _STATUS_CREATED
    same_key = bool(connection.api_key_encrypted) and (
        decrypt_secret(connection.api_key_encrypted) == secret.get_secret_value()
    )
    if not same_key:
        connection.api_key_encrypted = ciphertext
        connection.paused_at = None
        connection.pause_reason = ""
        connection.pause_until = None
    connection.active = True
    await session.flush()
    return connection, _STATUS_UNCHANGED if same_key else _STATUS_ROTATED


async def _upsert_routes(
    session: AsyncSession, *, connection: ProviderConnection, transport: str
) -> None:
    """Converge the catalog-default route per engine for this transport."""
    for engine in engines_for_transport(transport):
        model = measurement_route(engine).transport_model
        route = await session.scalar(
            select(ProviderRoute).where(
                ProviderRoute.connection_id == connection.id,
                ProviderRoute.logical_engine == engine,
            )
        )
        if route is None:
            session.add(
                ProviderRoute(
                    workspace_id=connection.workspace_id,
                    connection_id=connection.id,
                    logical_engine=engine,
                    transport_provider=transport,
                    transport_model=model,
                    is_default=True,
                )
            )
            continue
        route.transport_model = model
        route.is_default = True
        route.active = True
    await session.flush()


async def provision_platform_connections(
    session: AsyncSession,
    *,
    credentials: Mapping[str, SecretStr],
    dry_run: bool = False,
    at: datetime | None = None,
) -> tuple[PlatformConnectionReport, ...]:
    """Upsert the system workspace's platform connections/routes by transport.

    Idempotent (a re-run with the same keys reports ``unchanged`` and keeps
    the same row ids), rotation-safe, and fail closed when the Fernet key is
    missing. ``dry_run`` computes the identical converged state and rolls the
    transaction back — nothing persists. Emits
    ``provider.platform.provisioned`` per transport with transport/row
    id/status only (never secret material). ``at`` is the caller's clock
    (provisioned timestamp provenance); defaults to now.
    """
    if not encryption_key_configured(settings):
        raise PlatformProvisioningError(
            "ENCRYPTION_KEY is not configured; refusing to provision platform "
            "credentials with a missing/default Fernet key"
        )
    unknown = sorted(set(credentials) - ACTIVE_TRANSPORTS)
    if unknown:
        raise PlatformProvisioningError(
            "unknown transport(s) for platform provisioning: " + ", ".join(unknown)
        )
    provisioned_at = at or datetime.now(UTC)
    system = await _load_system_workspace(session)
    reports: list[PlatformConnectionReport] = []
    for transport in sorted(credentials):
        secret = credentials[transport]
        if not secret.get_secret_value().strip():
            raise PlatformProvisioningError(
                f"empty platform credential for transport {transport}"
            )
        connection, status = await _upsert_connection(
            session,
            system_workspace_id=system.id,
            transport=transport,
            secret=secret,
        )
        await _upsert_routes(session, connection=connection, transport=transport)
        logger.info(
            TELEMETRY_PLATFORM_PROVISIONED
            + " transport=%s connection_id=%s status=%s provisioned_at=%s",
            transport,
            connection.id,
            status,
            provisioned_at.isoformat(),
        )
        reports.append(
            PlatformConnectionReport(
                transport_provider=transport,
                connection_id=connection.id,
                status=status,
            )
        )
    if dry_run:
        await session.rollback()
    else:
        await session.commit()
    return tuple(reports)


def _parse_env_file(path: Path) -> dict[str, str]:
    """Parse a dotenv-style KEY=VALUE file (no shell expansion, no export)."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _collect_credentials(
    env_file: Path | None, environ: Mapping[str, str]
) -> dict[str, SecretStr]:
    """Resolve each transport's key (env-file wins, then process env)."""
    file_values = _parse_env_file(env_file) if env_file is not None else {}
    credentials: dict[str, SecretStr] = {}
    for transport, variable in PLATFORM_CREDENTIAL_ENV_VARS.items():
        raw = file_values.get(variable) or environ.get(variable) or ""
        if raw.strip():
            credentials[transport] = SecretStr(raw.strip())
    return credentials


async def _run(
    credentials: Mapping[str, SecretStr], *, dry_run: bool
) -> tuple[PlatformConnectionReport, ...]:
    async with SessionLocal() as session:
        return await provision_platform_connections(
            session, credentials=credentials, dry_run=dry_run
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="dotenv-style file with the platform keys (process env is the fallback)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report the converged state without writing anything",
    )
    args = parser.parse_args()
    try:
        credentials = _collect_credentials(args.env_file, os.environ)
        if not credentials:
            expected = ", ".join(sorted(PLATFORM_CREDENTIAL_ENV_VARS.values()))
            print(
                f"no platform credentials found; set one of: {expected}",
                file=sys.stderr,
            )
            return 1
        reports = asyncio.run(_run(credentials, dry_run=args.dry_run))
    except PlatformProvisioningError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for report in reports:
        print(f"{report.transport_provider}\t{report.connection_id}\t{report.status}")
    if args.dry_run:
        print("dry-run: no changes written")
    return 0


if __name__ == "__main__":  # pragma: no cover - operator CLI entrypoint
    sys.exit(main())
