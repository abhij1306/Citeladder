"""BYOK provider-connection service (workspace-scoped, invariant 5 + 6).

Every read/write filters by ``workspace_id``. The BYOK secret is Fernet-
encrypted on write and decrypted only inside ``run_connection_test`` to build a
short-lived adapter — it is never returned in a DTO, never logged, and never
persisted anywhere but the encrypted column (invariant 6).
"""

from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.connectors.answer_engines.contracts import AnswerEngineRequest
from app.connectors.answer_engines.errors import ProviderError
from app.connectors.answer_engines.factory import build_adapter
from app.core.config.provider_catalog import (
    CREDENTIAL_SOURCE_BYOK,
    ERROR_PARSE,
    ERROR_UNKNOWN,
    PROBE_PROMPT,
    PUBLIC_PROVIDER_CATALOG,
    REASON_VERIFICATION_REQUIRED,
    TEST_STATUS_FAILED,
    TEST_STATUS_OK,
    MeasurementRoute,
    ProviderCatalogEntry,
    configured_endpoint,
    default_probe_engine,
    is_active_transport,
    is_endpoint_approved,
    is_route_approved,
    measurement_route,
    provider_catalog_settings,
    public_provider_routes,
)
from app.core.security import decrypt_secret, encrypt_secret
from app.domain.billing.schemas import (
    ProviderConnectionStateResponse,
    ProviderConnectionStatesResponse,
    ProviderProbeResponse,
)
from app.domain.providers.credentials import connection_paused
from app.domain.providers.schemas import (
    ProviderConnectionCreate,
    ProviderConnectionResponse,
    ProviderConnectionTestResponse,
    ProviderConnectionUpdate,
    ProviderRouteResponse,
)
from app.models.audit import ProviderCapacityBucket
from app.models.provider import (
    ProviderConnection,
    ProviderConnectionTest,
    ProviderRoute,
)
from app.models.workspace import Workspace


class ProviderConnectionNotFoundError(LookupError):
    """Raised when a connection is missing or not in the caller's workspace."""


class InvalidRouteError(ValueError):
    """Raised when a requested (engine, transport) route is not approved."""


class InvalidProviderEndpointError(ValueError):
    """Raised when a tenant endpoint is not the operator-approved destination."""


def _require_approved_endpoint(transport_provider: str, base_url: str) -> None:
    if not is_endpoint_approved(transport_provider, base_url):
        raise InvalidProviderEndpointError(
            "Provider endpoint is not approved for this transport"
        )


class RetiredConnectionReadOnlyError(RuntimeError):
    """Raised when a mutation/test targets a retired transport."""


def _connection_query():
    """Tenant CRUD scope: BYOK rows in a non-system workspace only (T11).

    Platform-funded rows live in the reserved system workspace and are absent
    from every tenant list/get/update/delete/test path — even when an id is
    guessed (the workspace match and this filter both fail closed to 404).
    """
    return (
        select(ProviderConnection)
        .options(selectinload(ProviderConnection.routes))
        .join(Workspace, Workspace.id == ProviderConnection.workspace_id)
        .where(
            ProviderConnection.credential_source == CREDENTIAL_SOURCE_BYOK,
            Workspace.is_system.is_(False),
        )
    )


def connection_to_response(
    connection: ProviderConnection,
) -> ProviderConnectionResponse:
    """Project a connection to its DTO. NEVER includes the key (invariant 6)."""
    return ProviderConnectionResponse(
        id=connection.id,
        workspace_id=connection.workspace_id,
        label=connection.label,
        transport_provider=connection.transport_provider,
        base_url=connection.base_url,
        active=connection.active,
        api_key_set=bool(connection.api_key_encrypted),
        last_tested_at=connection.last_tested_at,
        last_test_status=connection.last_test_status,
        routes=[
            ProviderRouteResponse.model_validate(route) for route in connection.routes
        ],
        created_at=connection.created_at,
        updated_at=connection.updated_at,
    )


def _build_routes(
    *,
    workspace_id: uuid.UUID,
    transport_provider: str,
    items: list[Any] | None,
) -> list[ProviderRoute]:
    routes: list[ProviderRoute] = []
    for item in items or []:
        logical_engine = item.logical_engine
        if not is_route_approved(logical_engine, transport_provider):
            raise InvalidRouteError(
                f"Route not approved: {logical_engine} via {transport_provider}"
            )
        model = measurement_route(logical_engine).transport_model
        routes.append(
            ProviderRoute(
                workspace_id=workspace_id,
                logical_engine=logical_engine,
                transport_provider=transport_provider,
                transport_model=model,
                is_default=item.is_default,
            )
        )
    return routes


async def list_connections(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> list[ProviderConnection]:
    result = await session.execute(
        _connection_query()
        .where(ProviderConnection.workspace_id == workspace_id)
        .order_by(ProviderConnection.created_at.desc())
    )
    return list(result.scalars().all())


async def get_connection(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> ProviderConnection:
    result = await session.execute(
        _connection_query().where(
            ProviderConnection.id == connection_id,
            ProviderConnection.workspace_id == workspace_id,
        )
    )
    connection = result.scalar_one_or_none()
    if connection is None:
        raise ProviderConnectionNotFoundError(str(connection_id))
    return connection


async def create_connection(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    payload: ProviderConnectionCreate,
) -> ProviderConnection:
    _require_approved_endpoint(payload.transport_provider, payload.base_url)
    routes = _build_routes(
        workspace_id=workspace_id,
        transport_provider=payload.transport_provider,
        items=payload.routes,
    )
    connection = ProviderConnection(
        workspace_id=workspace_id,
        label=payload.label,
        transport_provider=payload.transport_provider,
        base_url=payload.base_url,
        api_key_encrypted=encrypt_secret(payload.api_key.strip()),
        active=payload.active,
        routes=routes,
    )
    session.add(connection)
    await session.commit()
    return await get_connection(
        session, workspace_id=workspace_id, connection_id=connection.id
    )


def _apply_endpoint_update(
    connection: ProviderConnection, payload: ProviderConnectionUpdate
) -> None:
    if payload.base_url is None:
        return
    _require_approved_endpoint(connection.transport_provider, payload.base_url)
    old_destination = connection.base_url or configured_endpoint(
        connection.transport_provider
    )
    new_destination = payload.base_url or configured_endpoint(
        connection.transport_provider
    )
    has_fresh_key = bool(payload.api_key and payload.api_key.strip())
    if new_destination != old_destination and not has_fresh_key:
        raise InvalidProviderEndpointError(
            "Changing a provider endpoint requires a fresh API key"
        )
    connection.base_url = payload.base_url


def _apply_connection_update(
    connection: ProviderConnection, payload: ProviderConnectionUpdate
) -> None:
    if payload.label is not None:
        connection.label = payload.label
    _apply_endpoint_update(connection, payload)
    if payload.active is not None:
        connection.active = payload.active
    if payload.api_key is not None and payload.api_key.strip():
        connection.api_key_encrypted = encrypt_secret(payload.api_key.strip())
    if payload.routes is not None:
        connection.routes = _build_routes(
            workspace_id=connection.workspace_id,
            transport_provider=connection.transport_provider,
            items=payload.routes,
        )


async def update_connection(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
    payload: ProviderConnectionUpdate,
) -> ProviderConnection:
    connection = await get_connection(
        session, workspace_id=workspace_id, connection_id=connection_id
    )
    # Reject retired-transport connections before any mutation.
    if not is_active_transport(connection.transport_provider):
        raise RetiredConnectionReadOnlyError(
            "This connection uses a retired transport and is historical and "
            "read-only; create a new direct connection instead."
        )
    _apply_connection_update(connection, payload)
    await session.commit()
    return await get_connection(
        session, workspace_id=workspace_id, connection_id=connection_id
    )


async def delete_connection(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> None:
    connection = await get_connection(
        session, workspace_id=workspace_id, connection_id=connection_id
    )
    # Delete the connection's capacity buckets in the SAME transaction. The
    # bucket pool unique is nulls-not-distinct over (pool_kind, transport,
    # connection_id, billing_account_id), so the SET NULL FK would otherwise
    # collapse two same-transport connection deletes onto one identity and
    # 23505 the second delete. A dead connection's pacing state is garbage
    # anyway; the bucket's leases cascade with it.
    await session.execute(
        delete(ProviderCapacityBucket).where(
            ProviderCapacityBucket.connection_id == connection.id
        )
    )
    await session.delete(connection)
    await session.commit()


async def run_connection_test(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> ProviderConnectionTestResponse:
    """Perform a live-ish connectivity probe through the adapter.

    Decrypts the key here (only here), builds a short-lived adapter, and fires a
    neutral, brand-free probe prompt. Records an append-only
    ``ProviderConnectionTest`` row and denormalizes the outcome onto the
    connection. The key is never logged or persisted (invariant 6).

    The probe request carries its OWN config-owned policy
    (``PROVIDER_TEST_RETRIEVAL_ENABLED`` / ``PROVIDER_TEST_MAX_OUTPUT_TOKENS`` /
    ``PROVIDER_TEST_TIMEOUT_SECONDS``): retrieval OFF so a connectivity test
    never performs a billable grounded search, and a tiny output cap.
    """
    connection = await get_connection(
        session, workspace_id=workspace_id, connection_id=connection_id
    )
    transport = connection.transport_provider
    # Refuse to test a retired-transport connection before decrypting the key
    # or issuing any network call (invariant 6 + 10).
    if not is_active_transport(transport):
        raise RetiredConnectionReadOnlyError(
            "This connection uses a retired transport and is historical and "
            "read-only; create a new direct connection instead."
        )
    _require_approved_endpoint(transport, connection.base_url)
    # Connectivity probes use the exact approved route.
    logical_engine = default_probe_engine(transport)
    model = measurement_route(logical_engine).transport_model
    for route in connection.routes:
        logical_engine = route.logical_engine
        model = measurement_route(logical_engine).transport_model
        break

    status = TEST_STATUS_OK
    error_code = ""
    detail = "Connection succeeded"
    latency_ms: int | None = None
    resolved_model = model

    started = time.monotonic()
    try:
        api_key = decrypt_secret(connection.api_key_encrypted)
        adapter = build_adapter(
            logical_engine=logical_engine,
            transport_provider=transport,
            api_key=api_key,
            base_url=connection.base_url,
        )
        response = await adapter.execute(
            AnswerEngineRequest(
                prompt=PROBE_PROMPT,
                system_instruction="",
                model=model,
                timeout_seconds=provider_catalog_settings.test_timeout_seconds,
                # A connectivity probe is a LIVENESS check, not a measurement:
                # retrieval is disabled so testing a key never triggers (or
                # pays for) a billable grounded search, and the cap is the tiny
                # probe cap — both config-owned (invariant 1), never the
                # measurement caps. No reasoning pin: the probe carries no
                # measurement policy, so it must not invent one.
                retrieval_enabled=provider_catalog_settings.test_retrieval_enabled,
                max_output_tokens=provider_catalog_settings.test_max_output_tokens,
                reasoning_effort=measurement_route(logical_engine).reasoning_effort,
            )
        )
        latency_ms = response.latency_ms
        resolved_model = response.transport_model or model
    except ProviderError as exc:
        status = TEST_STATUS_FAILED
        error_code = exc.error_code
        detail = str(exc)
        latency_ms = int((time.monotonic() - started) * 1000)
    except Exception as exc:  # noqa: BLE001 - any transport fault is a failure
        status = TEST_STATUS_FAILED
        error_code = ERROR_PARSE
        detail = f"Unexpected error: {type(exc).__name__}"
        latency_ms = int((time.monotonic() - started) * 1000)

    tested_at = datetime.now(UTC)
    test_row = ProviderConnectionTest(
        workspace_id=workspace_id,
        connection_id=connection.id,
        status=status,
        error_code=error_code,
        detail=detail[:1024],
        latency_ms=latency_ms,
        logical_engine=logical_engine,
        transport_provider=transport,
        transport_model=resolved_model,
    )
    session.add(test_row)
    connection.last_tested_at = tested_at
    connection.last_test_status = status
    await session.commit()

    return ProviderConnectionTestResponse(
        connection_id=connection.id,
        status=status,
        error_code=error_code,
        detail=detail,
        latency_ms=latency_ms,
        logical_engine=logical_engine,
        transport_provider=transport,
        transport_model=resolved_model,
        tested_at=tested_at,
    )


# --- Workspace connection states (authenticated commercial surface) --------


def _paused_state_response(
    entry: ProviderCatalogEntry,
    connection: ProviderConnection,
    latest_probe: ProviderConnectionTest,
) -> ProviderConnectionStateResponse:
    """The ``failed`` DTO for a paused connection with a probe history.

    The reason is the safe pause classification token, never raw detail; the
    probe row's own status is preserved with the same overridden reason.
    """
    reason = connection.pause_reason or ERROR_UNKNOWN
    return ProviderConnectionStateResponse(
        key=entry.key,
        label=entry.label,
        state="failed",
        safe_reason=reason,
        grant_key=entry.grant_key,
        latest_probe=ProviderProbeResponse(
            status=(
                TEST_STATUS_OK
                if latest_probe.status == TEST_STATUS_OK
                else TEST_STATUS_FAILED
            ),
            safe_reason=reason,
            tested_at=latest_probe.created_at,
            model=latest_probe.transport_model or None,
            latency_ms=latest_probe.latency_ms,
        ),
    )


def _connection_state_response(
    entry: ProviderCatalogEntry,
    *,
    state: str,
    safe_reason: str | None,
    probe: ProviderConnectionTest | None,
) -> ProviderConnectionStateResponse:
    latest_probe = None
    if probe is not None:
        latest_probe = ProviderProbeResponse(
            status=(
                TEST_STATUS_OK if probe.status == TEST_STATUS_OK else TEST_STATUS_FAILED
            ),
            safe_reason=safe_reason,
            tested_at=probe.created_at,
            model=probe.transport_model or None,
            latency_ms=probe.latency_ms,
        )
    return ProviderConnectionStateResponse(
        key=entry.key,
        label=entry.label,
        state=state,
        safe_reason=safe_reason,
        grant_key=entry.grant_key,
        latest_probe=latest_probe,
    )


def derive_connection_state(
    entry: ProviderCatalogEntry,
    connection: ProviderConnection | None,
    latest_probe: ProviderConnectionTest | None,
    *,
    at: datetime | None = None,
) -> ProviderConnectionStateResponse:
    """Derive one catalog provider's workspace state (pure, fail closed).

    ``connection`` is the workspace's active BYOK connection for the entry's
    transport identity (or None); ``latest_probe`` is that connection's most
    recent append-only probe row (or None). Precedence: ``unavailable`` when
    no adapter ships; ``missing`` when no active key-set connection exists or
    the configured key has never been successfully probed; ``failed`` when
    the connection is paused (safe reason from the pause classification —
    never raw detail) or the latest attempted probe failed; ``connected``
    only after a successful probe while the connection remains active,
    key-set, and NOT paused. An unprobed key is NEVER connected. The probe's
    ``detail`` column never leaves the database — the DTO carries the
    classification token only (invariant 6).

    ``at`` makes the pause deadline clock explicit; without it any pause
    marker fails closed as paused.
    """
    if not entry.adapter_shipped:
        return _connection_state_response(
            entry, state="unavailable", safe_reason=entry.unavailable_reason, probe=None
        )
    if (
        connection is None
        or not connection.active
        or not connection.api_key_encrypted
        or latest_probe is None
    ):
        # Fail closed: no active connection, no key material set, or the
        # configured key has never had a successful probe (latest_probe=None
        # for never-probed).
        return _connection_state_response(
            entry,
            state="missing",
            safe_reason=REASON_VERIFICATION_REQUIRED,
            probe=None,
        )
    paused = (
        connection.paused_at is not None
        if at is None
        else connection_paused(connection, at=at)
    )
    if paused:
        return _paused_state_response(entry, connection, latest_probe)
    if latest_probe.status == TEST_STATUS_OK:
        return _connection_state_response(
            entry, state="connected", safe_reason=None, probe=latest_probe
        )
    reason = latest_probe.error_code or ERROR_UNKNOWN
    return _connection_state_response(
        entry, state="failed", safe_reason=reason, probe=latest_probe
    )


async def _latest_probes(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    connection_ids: list[uuid.UUID],
) -> dict[uuid.UUID, ProviderConnectionTest]:
    """Latest probe per connection in one DISTINCT ON round trip.

    The probe table is append-only (invariant 3) and unbounded per
    connection, so this never loads full history. ``workspace_id`` is
    filtered even though the ids are already workspace-scoped (invariant 5).
    """
    if not connection_ids:
        return {}
    result = await session.execute(
        select(ProviderConnectionTest)
        .where(
            ProviderConnectionTest.workspace_id == workspace_id,
            ProviderConnectionTest.connection_id.in_(connection_ids),
        )
        .order_by(
            ProviderConnectionTest.connection_id,
            ProviderConnectionTest.created_at.desc(),
            ProviderConnectionTest.id.desc(),
        )
        .distinct(ProviderConnectionTest.connection_id)
    )
    return {probe.connection_id: probe for probe in result.scalars()}


async def get_connection_states(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> ProviderConnectionStatesResponse:
    """Per-provider workspace states for ``GET /provider-connections/states``.

    Every catalog row is present exactly once, in catalog order. Catalog
    entries map to connections through the transport identity the connection
    row carries (invariant 10); the most recently created active connection
    per transport wins. Reads only this workspace's BYOK rows in a non-system
    workspace (invariant 5) — platform-funded rows never appear in tenant
    states (T11).
    """
    result = await session.execute(
        select(ProviderConnection)
        .join(Workspace, Workspace.id == ProviderConnection.workspace_id)
        .where(
            ProviderConnection.workspace_id == workspace_id,
            ProviderConnection.active.is_(True),
            ProviderConnection.credential_source == CREDENTIAL_SOURCE_BYOK,
            Workspace.is_system.is_(False),
        )
        .order_by(ProviderConnection.created_at.desc())
    )
    by_transport: dict[str, ProviderConnection] = {}
    # Named apart from the per-catalog-entry ``connection`` below, which is
    # nullable: one name for both would make the optional lookup an assignment
    # to a non-optional variable.
    for candidate in result.scalars():
        by_transport.setdefault(candidate.transport_provider, candidate)
    latest_probes = await _latest_probes(
        session,
        workspace_id=workspace_id,
        connection_ids=[c.id for c in by_transport.values()],
    )
    derived_at = datetime.now(UTC)
    providers: list[ProviderConnectionStateResponse] = []
    for entry in PUBLIC_PROVIDER_CATALOG:
        routes = public_provider_routes(entry.key)
        transport = _catalog_transport(entry.key, routes)
        connection = by_transport.get(transport) if transport is not None else None
        probe = latest_probes.get(connection.id) if connection is not None else None
        providers.append(
            derive_connection_state(entry, connection, probe, at=derived_at)
        )
    return ProviderConnectionStatesResponse(
        workspace_id=workspace_id, providers=providers
    )


def _catalog_transport(
    provider_key: str, routes: tuple[MeasurementRoute, ...]
) -> str | None:
    transports = {route.transport_provider for route in routes}
    if len(transports) > 1:
        raise RuntimeError(
            f"provider {provider_key!r} has routes across multiple transports"
        )
    return next(iter(transports), None)
