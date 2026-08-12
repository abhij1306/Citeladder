"""Component tests for ``GET /api/v1/provider-connections/states`` (v8 Task 3).

The authenticated workspace-state surface derives every public catalog entry's
state fail closed from the workspace's connections and their append-only
probe history (invariants 3, 5, 6):

  - adapter-less providers (grok/perplexity/copilot) are ``unavailable`` with
    ``latest_probe=None``;
  - no active connection — or a configured-but-never-probed key — is
    ``missing`` with ``verification_required`` (an unprobed key is NEVER
    ``connected``);
  - a failed latest probe is ``failed`` carrying the classification token
    only (never key material, never the internal ``detail`` message);
  - the latest probe wins; another workspace's probes never leak.

Probes are seeded directly as ``ProviderConnectionTest`` rows with explicit
timestamps so latest-wins ordering is deterministic without transport mocks.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import select

from app.core.config.provider_catalog import (
    ERROR_AUTH,
    PUBLIC_PROVIDER_CATALOG,
    REASON_PROVIDER_UNAVAILABLE,
    REASON_VERIFICATION_REQUIRED,
    TEST_STATUS_FAILED,
    TEST_STATUS_OK,
)
from app.domain.billing.schemas import (
    ProviderConnectionStateResponse,
    ProviderConnectionStatesResponse,
)
from app.models.provider import ProviderConnectionTest
from app.models.workspace import Workspace
from tests.component.auth_helpers import register_and_login as _register

_SECRET = "sk-test-fake-byok-value-123456"  # pragma: allowlist secret
_T0 = datetime(2026, 7, 31, 12, 0, 0, tzinfo=UTC)


async def _workspace_id(db_session) -> uuid.UUID:
    return (await db_session.execute(select(Workspace))).scalars().first().id


async def _create_connection(
    client: httpx.AsyncClient, *, transport: str, engine: str
) -> str:
    resp = await client.post(
        "/api/v1/provider-connections",
        json={
            "label": f"{engine} key",
            "transport_provider": transport,
            "api_key": _SECRET,
            "routes": [{"logical_engine": engine, "is_default": True}],
        },
    )
    assert resp.status_code == 201
    return resp.json()["id"]


async def _seed_probe(
    db_session,
    *,
    workspace_id: uuid.UUID,
    connection_id: str,
    status: str,
    created_at: datetime,
    error_code: str = "",
    detail: str = "",
    latency_ms: int | None = 42,
    model: str = "gpt-5.4",
) -> None:
    db_session.add(
        ProviderConnectionTest(
            workspace_id=workspace_id,
            connection_id=uuid.UUID(connection_id),
            status=status,
            error_code=error_code,
            detail=detail,
            latency_ms=latency_ms,
            logical_engine="chatgpt",
            transport_provider="openai",
            transport_model=model,
            created_at=created_at,
        )
    )
    await db_session.commit()


async def _get_states(client: httpx.AsyncClient) -> ProviderConnectionStatesResponse:
    """Fetch and validate against the strict contract (``extra='forbid'``)."""
    resp = await client.get("/api/v1/provider-connections/states")
    assert resp.status_code == 200
    return ProviderConnectionStatesResponse.model_validate(resp.json())


def _state(
    states: ProviderConnectionStatesResponse, key: str
) -> ProviderConnectionStateResponse:
    return next(p for p in states.providers if p.key == key)


@pytest.mark.asyncio
async def test_states_without_connections_fail_closed(
    client: httpx.AsyncClient, db_session
) -> None:
    await _register(client, "states-empty@example.com")
    workspace_id = await _workspace_id(db_session)

    raw = await client.get("/api/v1/provider-connections/states")
    assert raw.status_code == 200
    body = raw.json()
    # The strict contract: exactly the frozen field set, never null lists.
    assert set(body) == {"workspace_id", "providers"}
    assert all(
        set(p) == {"key", "label", "state", "safe_reason", "grant_key", "latest_probe"}
        for p in body["providers"]
    )

    states = ProviderConnectionStatesResponse.model_validate(body)
    assert states.workspace_id == workspace_id
    entries = {e.key: e for e in PUBLIC_PROVIDER_CATALOG}
    # Every catalog row is present exactly once, in catalog order.
    assert [p.key for p in states.providers] == [e.key for e in PUBLIC_PROVIDER_CATALOG]
    for provider in states.providers:
        entry = entries[provider.key]
        assert provider.label == entry.label
        assert provider.grant_key == entry.grant_key
        assert provider.latest_probe is None
        if entry.adapter_shipped:
            assert provider.state == "missing"
            assert provider.safe_reason == REASON_VERIFICATION_REQUIRED
        else:
            assert provider.state == "unavailable"
            assert provider.safe_reason == REASON_PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_states_unprobed_connection_is_still_missing(
    client: httpx.AsyncClient, db_session
) -> None:
    """The fail-closed pin: a configured key with no probe is NEVER connected."""
    await _register(client, "states-unprobed@example.com")
    await _create_connection(client, transport="openai", engine="chatgpt")

    states = await _get_states(client)
    chatgpt = _state(states, "chatgpt")
    assert chatgpt.state == "missing"
    assert chatgpt.safe_reason == REASON_VERIFICATION_REQUIRED
    assert chatgpt.latest_probe is None
    # Untouched shipped providers are missing; adapter-less stay unavailable.
    assert _state(states, "claude").state == "missing"
    assert _state(states, "gemini").state == "missing"
    assert _state(states, "grok").state == "unavailable"


@pytest.mark.asyncio
async def test_states_failed_probe_reports_safe_reason(
    client: httpx.AsyncClient, db_session
) -> None:
    await _register(client, "states-failed@example.com")
    workspace_id = await _workspace_id(db_session)
    connection_id = await _create_connection(
        client, transport="openai", engine="chatgpt"
    )
    internal_detail = "internal probe detail never for the api"
    await _seed_probe(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        status=TEST_STATUS_FAILED,
        error_code=ERROR_AUTH,
        detail=internal_detail,
        created_at=_T0,
    )

    raw = await client.get("/api/v1/provider-connections/states")
    assert raw.status_code == 200
    # Invariant 6: classification token only — the internal detail message and
    # the BYOK secret never leave the database.
    assert internal_detail not in raw.text
    assert _SECRET not in raw.text

    states = ProviderConnectionStatesResponse.model_validate(raw.json())
    chatgpt = _state(states, "chatgpt")
    assert chatgpt.state == "failed"
    assert chatgpt.safe_reason == ERROR_AUTH
    probe = chatgpt.latest_probe
    assert probe is not None
    assert probe.status == "failed"
    assert probe.safe_reason == ERROR_AUTH
    assert probe.tested_at == _T0
    assert probe.model == "gpt-5.4"
    assert probe.latency_ms == 42


@pytest.mark.asyncio
async def test_states_successful_probe_is_connected(
    client: httpx.AsyncClient, db_session
) -> None:
    await _register(client, "states-connected@example.com")
    workspace_id = await _workspace_id(db_session)
    connection_id = await _create_connection(
        client, transport="openai", engine="chatgpt"
    )
    await _seed_probe(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        status=TEST_STATUS_OK,
        created_at=_T0,
    )

    states = await _get_states(client)
    chatgpt = _state(states, "chatgpt")
    assert chatgpt.state == "connected"
    assert chatgpt.safe_reason is None
    probe = chatgpt.latest_probe
    assert probe is not None
    assert probe.status == "ok"
    assert probe.safe_reason is None
    assert probe.tested_at == _T0
    # Other providers are unaffected by the openai connection.
    assert _state(states, "claude").state == "missing"


@pytest.mark.asyncio
async def test_states_latest_probe_wins(client: httpx.AsyncClient, db_session) -> None:
    await _register(client, "states-latest@example.com")
    workspace_id = await _workspace_id(db_session)
    connection_id = await _create_connection(
        client, transport="openai", engine="chatgpt"
    )

    await _seed_probe(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        status=TEST_STATUS_OK,
        created_at=_T0,
    )
    assert _state(await _get_states(client), "chatgpt").state == "connected"

    # A newer failed probe flips the state: latest wins over earlier success.
    await _seed_probe(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        status=TEST_STATUS_FAILED,
        error_code=ERROR_AUTH,
        created_at=_T0 + timedelta(minutes=1),
    )
    chatgpt = _state(await _get_states(client), "chatgpt")
    assert chatgpt.state == "failed"
    assert chatgpt.safe_reason == ERROR_AUTH
    assert chatgpt.latest_probe is not None
    assert chatgpt.latest_probe.tested_at == _T0 + timedelta(minutes=1)

    # A newer success recovers it (append-only history, latest row decides).
    await _seed_probe(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        status=TEST_STATUS_OK,
        created_at=_T0 + timedelta(minutes=2),
    )
    assert _state(await _get_states(client), "chatgpt").state == "connected"


@pytest.mark.asyncio
async def test_states_cross_workspace_probes_never_leak(
    client: httpx.AsyncClient, db_session
) -> None:
    # Workspace A has a connected provider with probe history.
    await _register(client, "states-owner@example.com")
    workspace_a = await _workspace_id(db_session)
    connection_id = await _create_connection(
        client, transport="openai", engine="chatgpt"
    )
    await _seed_probe(
        db_session,
        workspace_id=workspace_a,
        connection_id=connection_id,
        status=TEST_STATUS_OK,
        created_at=_T0,
    )
    owner_states = await _get_states(client)
    assert owner_states.workspace_id == workspace_a
    assert _state(owner_states, "chatgpt").state == "connected"

    # A different user's workspace sees none of it (invariant 5).
    await client.post("/api/v1/auth/logout")
    await _register(client, "states-intruder@example.com")
    intruder_states = await _get_states(client)
    assert intruder_states.workspace_id != workspace_a
    chatgpt = _state(intruder_states, "chatgpt")
    assert chatgpt.state == "missing"
    assert chatgpt.safe_reason == REASON_VERIFICATION_REQUIRED
    assert chatgpt.latest_probe is None


# ---------------------------------------------------------------------------
# T11: platform rows are excluded; paused connections report failed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_states_exclude_platform_rows(
    client: httpx.AsyncClient, db_session
) -> None:
    """A healthy platform connection in the system workspace must NEVER make
    the tenant's state surface report connected (or leak its key)."""
    await _register(client, "states-platform@example.com")
    from tests.component.audit_helpers import seed_platform_connection

    await seed_platform_connection(db_session, engines=("claude",))
    await db_session.commit()

    raw = await client.get("/api/v1/provider-connections/states")
    assert raw.status_code == 200
    assert "platform-secret-test-key" not in str(raw.json())
    states = ProviderConnectionStatesResponse.model_validate(raw.json())
    claude = _state(states, "claude")
    assert claude.state == "missing"
    assert claude.safe_reason == REASON_VERIFICATION_REQUIRED
    assert claude.latest_probe is None


@pytest.mark.asyncio
async def test_states_paused_connection_reports_failed_with_safe_reason(
    client: httpx.AsyncClient, db_session
) -> None:
    """A paused (but probed) connection reports ``failed`` carrying the safe
    pause classification token — never key material, never raw detail."""
    await _register(client, "states-paused@example.com")
    workspace_id = await _workspace_id(db_session)
    connection_id = await _create_connection(
        client, transport="openai", engine="chatgpt"
    )
    await _seed_probe(
        db_session,
        workspace_id=workspace_id,
        connection_id=connection_id,
        status=TEST_STATUS_OK,
        created_at=_T0,
    )

    from app.models.provider import ProviderConnection

    connection = await db_session.get(ProviderConnection, uuid.UUID(connection_id))
    assert connection is not None
    connection.paused_at = _T0
    connection.pause_reason = ERROR_AUTH
    await db_session.commit()

    raw = await client.get("/api/v1/provider-connections/states")
    assert raw.status_code == 200
    assert _SECRET not in str(raw.json())
    states = ProviderConnectionStatesResponse.model_validate(raw.json())
    chatgpt = _state(states, "chatgpt")
    assert chatgpt.state == "failed"
    assert chatgpt.safe_reason == ERROR_AUTH
    probe = chatgpt.latest_probe
    assert probe is not None
    assert probe.status == TEST_STATUS_OK
    assert probe.safe_reason == ERROR_AUTH
    assert "detail" not in probe.model_dump()
