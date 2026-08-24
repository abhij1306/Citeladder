"""Component tests for the BYOK provider-connections API (v2 direct-only).

Covers the v2 acceptance:
  - connection CRUD is workspace-scoped (invariant 5);
  - the BYOK secret is encrypted at rest and NEVER present in any response DTO
    or log line (explicit redaction assertion, invariant 6);
  - the active surface is exactly the three direct transports
    ``{openai, anthropic, google}``;
  - ``POST /{id}/test`` returns a status (transport mocked, no real spend);
  - ``GET /provider-catalog`` lists the direct transports/routes only.
"""

from __future__ import annotations

import json
import logging
import uuid
from decimal import Decimal
from typing import Any

import httpx
import pytest
from sqlalchemy import func, select

from app.core.config.audits import POOL_KIND_CONNECTION
from app.core.config.provider_catalog import PROBE_PROMPT, provider_catalog_settings
from app.core.security import decrypt_secret
from app.models.audit import ProviderCapacityBucket

_SECRET = "sk-test-fake-byok-value-123456"  # pragma: allowlist secret


async def _register(client: httpx.AsyncClient, email: str) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "password123"},
    )
    assert resp.status_code == 202
    login_response = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "password123"},
    )
    assert login_response.status_code == 200


def _connection_payload(**overrides: object) -> dict:
    payload: dict[str, Any] = {
        "label": "Prod OpenAI",
        "transport_provider": "openai",
        "api_key": _SECRET,
        "routes": [
            {"logical_engine": "chatgpt", "is_default": True},
        ],
    }
    payload.update(overrides)
    return payload


def _assert_no_secret(blob: object) -> None:
    """Fail if the raw secret or its ciphertext field leaks into a DTO.

    ``api_key_set`` (a boolean presence flag) is allowed; the raw ``api_key``
    value and the ``api_key_encrypted`` ciphertext column are not.
    """
    text = str(blob)
    assert _SECRET not in text
    assert "api_key_encrypted" not in text
    # The write-only "api_key" value field must never round-trip in a response.
    assert '"api_key"' not in text and "'api_key'" not in text


async def _resolve_workspace_id(db_session) -> object:
    from sqlalchemy import select

    from app.models.workspace import Workspace

    return (await db_session.execute(select(Workspace))).scalars().first().id


@pytest.mark.asyncio
async def test_create_connection_redacts_secret_in_response(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "prov1@example.com")
    resp = await client.post("/api/v1/provider-connections", json=_connection_payload())
    assert resp.status_code == 201
    body = resp.json()
    assert "-" in body["id"] and "-" in body["workspace_id"]
    assert body["transport_provider"] == "openai"
    assert body["api_key_set"] is True
    # Invariant 6: the secret and any key field are absent from the DTO.
    _assert_no_secret(body)
    # Provenance recorded on routes (invariant 10).
    engines = {r["logical_engine"]: r for r in body["routes"]}
    assert engines["chatgpt"]["transport_provider"] == "openai"
    assert engines["chatgpt"]["transport_model"] == "gpt-5.6-sol"
    assert engines["chatgpt"]["is_default"] is True
    # New routes are active.
    assert engines["chatgpt"]["active"] is True


@pytest.mark.asyncio
async def test_create_unknown_connection_rejected(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "prov-unknown@example.com")
    # Unknown values are rejected at request validation (422).
    resp = await client.post(
        "/api/v1/provider-connections",
        json={
            "transport_provider": "unsupported",
            "api_key": _SECRET,
            "routes": [{"logical_engine": "chatgpt"}],
        },
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_secret_encrypted_at_rest(client: httpx.AsyncClient, db_session) -> None:
    from sqlalchemy import select

    from app.models.provider import ProviderConnection

    await _register(client, "prov2@example.com")
    resp = await client.post("/api/v1/provider-connections", json=_connection_payload())
    assert resp.status_code == 201

    row = (await db_session.execute(select(ProviderConnection))).scalar_one()
    # Ciphertext at rest is NOT the plaintext, and decrypts back to it.
    assert row.api_key_encrypted != _SECRET
    assert _SECRET not in row.api_key_encrypted
    assert decrypt_secret(row.api_key_encrypted) == _SECRET


@pytest.mark.asyncio
async def test_list_and_get_never_return_secret(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "prov3@example.com")
    await client.post("/api/v1/provider-connections", json=_connection_payload())
    listed = await client.get("/api/v1/provider-connections")
    assert listed.status_code == 200
    _assert_no_secret(listed.json())
    assert listed.json()[0]["api_key_set"] is True


@pytest.mark.asyncio
async def test_update_rotates_key_without_exposing_it(
    client: httpx.AsyncClient, db_session
) -> None:
    from sqlalchemy import select

    from app.models.provider import ProviderConnection

    await _register(client, "prov4@example.com")
    created = await client.post(
        "/api/v1/provider-connections", json=_connection_payload()
    )
    conn_id = created.json()["id"]

    new_secret = "sk-test-fake-rotated-key-987654321"  # pragma: allowlist secret
    resp = await client.patch(
        f"/api/v1/provider-connections/{conn_id}",
        json={"label": "Renamed", "api_key": new_secret},
    )
    assert resp.status_code == 200
    assert resp.json()["label"] == "Renamed"
    _assert_no_secret(resp.json())

    row = (await db_session.execute(select(ProviderConnection))).scalar_one()
    assert decrypt_secret(row.api_key_encrypted) == new_secret


@pytest.mark.asyncio
async def test_update_without_key_leaves_secret_unchanged(
    client: httpx.AsyncClient, db_session
) -> None:
    from sqlalchemy import select

    from app.models.provider import ProviderConnection

    await _register(client, "prov5@example.com")
    created = await client.post(
        "/api/v1/provider-connections", json=_connection_payload()
    )
    conn_id = created.json()["id"]
    await client.patch(
        f"/api/v1/provider-connections/{conn_id}",
        json={"active": False},
    )
    row = (await db_session.execute(select(ProviderConnection))).scalar_one()
    assert decrypt_secret(row.api_key_encrypted) == _SECRET
    assert row.active is False


@pytest.mark.asyncio
async def test_arbitrary_endpoint_is_rejected_and_change_requires_fresh_key(
    client: httpx.AsyncClient, monkeypatch
) -> None:
    from app.core.config.provider_catalog import provider_catalog_settings

    await _register(client, "prov-endpoint@example.com")
    rejected = await client.post(
        "/api/v1/provider-connections",
        json=_connection_payload(base_url="https://attacker.example/v1"),
    )
    assert rejected.status_code == 400

    created = await client.post(
        "/api/v1/provider-connections",
        json=_connection_payload(base_url="https://api.openai.com/v1/responses"),
    )
    conn_id = created.json()["id"]
    operator_gateway = "https://gateway.operator.example/v1/responses"
    monkeypatch.setattr(
        provider_catalog_settings, "openai_responses_url", operator_gateway
    )
    endpoint_change = await client.patch(
        f"/api/v1/provider-connections/{conn_id}",
        json={"base_url": operator_gateway},
    )
    assert endpoint_change.status_code == 400
    assert "fresh API key" in endpoint_change.json()["detail"]

    rotated = await client.patch(
        f"/api/v1/provider-connections/{conn_id}",
        json={"base_url": operator_gateway, "api_key": "fresh-key"},
    )
    assert rotated.status_code == 200


@pytest.mark.asyncio
async def test_delete_connection(client: httpx.AsyncClient) -> None:
    await _register(client, "prov6@example.com")
    created = await client.post(
        "/api/v1/provider-connections", json=_connection_payload()
    )
    conn_id = created.json()["id"]
    resp = await client.delete(f"/api/v1/provider-connections/{conn_id}")
    assert resp.status_code == 204
    listed = await client.get("/api/v1/provider-connections")
    assert listed.json() == []


@pytest.mark.asyncio
async def test_delete_two_same_transport_connections_clears_capacity_buckets(
    client: httpx.AsyncClient, db_session
) -> None:
    """Two same-transport BYOK connections each own a connection-pool capacity
    bucket; deleting BOTH must not trip the nulls-not-distinct pool unique
    (the SET NULL FK would otherwise collapse both buckets onto one identity).
    """
    await _register(client, "prov-buckets@example.com")
    first = await client.post(
        "/api/v1/provider-connections",
        json=_connection_payload(label="OpenAI A"),
    )
    second = await client.post(
        "/api/v1/provider-connections",
        json=_connection_payload(label="OpenAI B"),
    )
    assert first.status_code == 201
    assert second.status_code == 201
    first_id, second_id = first.json()["id"], second.json()["id"]

    for connection_id in (first_id, second_id):
        db_session.add(
            ProviderCapacityBucket(
                pool_kind=POOL_KIND_CONNECTION,
                transport_provider="openai",
                connection_id=uuid.UUID(connection_id),
                billing_account_id=None,
                capacity=Decimal("5"),
                tokens=Decimal("0"),
                refill_tokens_per_second=Decimal("0"),
            )
        )
    await db_session.commit()

    delete_first = await client.delete(f"/api/v1/provider-connections/{first_id}")
    assert delete_first.status_code == 204
    # Before the fix this second delete 500'd on uq_provider_capacity_bucket_pool.
    delete_second = await client.delete(f"/api/v1/provider-connections/{second_id}")
    assert delete_second.status_code == 204

    listed = await client.get("/api/v1/provider-connections")
    assert listed.json() == []
    assert await db_session.scalar(select(func.count(ProviderCapacityBucket.id))) == 0


@pytest.mark.asyncio
async def test_invalid_route_rejected(client: httpx.AsyncClient) -> None:
    await _register(client, "prov7@example.com")
    # chatgpt is served ONLY via openai now; chatgpt over anthropic is not
    # an approved route.
    resp = await client.post(
        "/api/v1/provider-connections",
        json={
            "transport_provider": "anthropic",
            "api_key": _SECRET,
            "routes": [{"logical_engine": "chatgpt"}],
        },
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_test_endpoint_returns_status_success(
    client: httpx.AsyncClient, monkeypatch
) -> None:
    await _register(client, "prov8@example.com")
    created = await client.post(
        "/api/v1/provider-connections", json=_connection_payload()
    )
    conn_id = created.json()["id"]

    # Mock the transport so no real API call is made.
    from app.connectors.answer_engines import openai as openai_mod

    payload = {
        "id": "resp-x",
        "object": "response",
        "status": "completed",
        "model": "gpt-5.6-luna",
        "output": [
            {
                "type": "message",
                "id": "m",
                "content": [{"type": "output_text", "text": "ok"}],
            }
        ],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=payload)

    # Patch the POOLED-CLIENT ACCESSOR, not `httpx.AsyncClient`. Adapters no
    # longer construct a client per call (they reuse one keep-alive connection
    # per provider host), so patching the constructor only landed if this test
    # happened to be the one that created the pooled client.
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(openai_mod, "shared_client", lambda: mock_client)

    resp = await client.post(f"/api/v1/provider-connections/{conn_id}/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["connection_id"] == conn_id
    # Provenance of the probe is recorded (invariant 10).
    assert body["transport_provider"] == "openai"
    assert body["logical_engine"] == "chatgpt"
    _assert_no_secret(body)


@pytest.mark.asyncio
async def test_test_endpoint_probe_is_a_liveness_check_not_a_measurement(
    client: httpx.AsyncClient, monkeypatch
) -> None:
    """The ``/test`` probe never buys a grounded search and stays tiny.

    A connectivity probe proves the key reaches the provider. It must not attach
    the billable web-search tool and must cap output at the config-owned probe
    cap (invariant 1 — no inline caps), which is independent of the measurement
    caps a real audit freezes.
    """
    await _register(client, "prov8probe@example.com")
    created = await client.post(
        "/api/v1/provider-connections", json=_connection_payload()
    )
    conn_id = created.json()["id"]

    from app.connectors.answer_engines import openai as openai_mod

    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "id": "resp-probe",
                "object": "response",
                "status": "completed",
                "model": "gpt-5.6-luna",
                "output": [
                    {
                        "type": "message",
                        "id": "m",
                        "content": [{"type": "output_text", "text": "ok"}],
                    }
                ],
                "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
            },
        )

    # Patch the pooled-client accessor — see the note in the success-path test.
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(openai_mod, "shared_client", lambda: mock_client)

    resp = await client.post(f"/api/v1/provider-connections/{conn_id}/test")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"

    assert len(sent) == 1
    body = sent[0]
    # Retrieval off -> the built-in web-search tool is never attached.
    assert "tools" not in body
    assert body["max_output_tokens"] == (
        provider_catalog_settings.test_max_output_tokens
    )
    assert body["input"]
    assert PROBE_PROMPT in json.dumps(body["input"])


@pytest.mark.asyncio
async def test_test_endpoint_reports_failure_and_redacts_logs(
    client: httpx.AsyncClient, monkeypatch, caplog
) -> None:
    await _register(client, "prov9@example.com")
    created = await client.post(
        "/api/v1/provider-connections", json=_connection_payload()
    )
    conn_id = created.json()["id"]

    from app.connectors.answer_engines import openai as openai_mod

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    # Patch the pooled-client accessor — see the note in the success-path test.
    mock_client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    monkeypatch.setattr(openai_mod, "shared_client", lambda: mock_client)

    with caplog.at_level(logging.DEBUG):
        resp = await client.post(f"/api/v1/provider-connections/{conn_id}/test")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error_code"] == "auth_failure"
    # Invariant 6: the secret never appears in the response or any log line.
    _assert_no_secret(body)
    assert _SECRET not in caplog.text


@pytest.mark.asyncio
async def test_provider_catalog_lists_direct_routes_only(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.get("/api/v1/provider-catalog")
    assert resp.status_code == 200
    body = resp.json()
    # Active surface is exactly the three direct transports.
    assert set(body["transports"]) == {"openai", "anthropic", "google"}
    engines = {e["logical_engine"]: e for e in body["engines"]}
    # chatgpt is served ONLY via direct openai now.
    chatgpt_transports = {r["transport_provider"] for r in engines["chatgpt"]["routes"]}
    assert chatgpt_transports == {"openai"}
    gemini_transports = {r["transport_provider"] for r in engines["gemini"]["routes"]}
    assert gemini_transports == {"google"}
    claude_transports = {r["transport_provider"] for r in engines["claude"]["routes"]}
    assert claude_transports == {"anthropic"}


@pytest.mark.asyncio
async def test_cross_workspace_access_denied(
    client: httpx.AsyncClient,
) -> None:
    # Owner creates a connection.
    await _register(client, "owner@example.com")
    created = await client.post(
        "/api/v1/provider-connections", json=_connection_payload()
    )
    conn_id = created.json()["id"]

    # A different user (fresh workspace) must not see or touch it.
    await client.post("/api/v1/auth/logout")
    await _register(client, "intruder@example.com")
    listed = await client.get("/api/v1/provider-connections")
    assert listed.status_code == 200
    assert listed.json() == []

    got = await client.patch(
        f"/api/v1/provider-connections/{conn_id}",
        json={"label": "hijack"},
    )
    assert got.status_code == 404
    tested = await client.post(f"/api/v1/provider-connections/{conn_id}/test")
    assert tested.status_code == 404


# ---------------------------------------------------------------------------
# T11: platform credentials + the system workspace are tenant-invisible
# ---------------------------------------------------------------------------

_PLATFORM_SECRET = "platform-secret-test-key"  # pragma: allowlist secret


async def _seed_platform_connection_id(db_session) -> str:
    """Seed THE system workspace with a healthy platform connection (T11)."""
    from sqlalchemy import select

    from app.models.provider import ProviderConnection
    from tests.component.audit_helpers import seed_platform_connection

    system = await seed_platform_connection(db_session, engines=("claude",))
    await db_session.commit()
    connection = await db_session.scalar(
        select(ProviderConnection).where(ProviderConnection.workspace_id == system.id)
    )
    assert connection is not None
    return str(connection.id)


@pytest.mark.asyncio
async def test_platform_connection_invisible_to_tenant_crud_and_test(
    client: httpx.AsyncClient, db_session
) -> None:
    await _register(client, "platform-tenant@example.com")
    platform_id = await _seed_platform_connection_id(db_session)

    listed = await client.get("/api/v1/provider-connections")
    assert listed.status_code == 200
    assert listed.json() == []
    assert _PLATFORM_SECRET not in str(listed.json())

    patched = await client.patch(
        f"/api/v1/provider-connections/{platform_id}", json={"label": "hijack"}
    )
    assert patched.status_code == 404
    assert patched.json()["detail"] == "Provider connection not found"

    deleted = await client.delete(f"/api/v1/provider-connections/{platform_id}")
    assert deleted.status_code == 404
    assert deleted.json()["detail"] == "Provider connection not found"

    tested = await client.post(f"/api/v1/provider-connections/{platform_id}/test")
    assert tested.status_code == 404
    assert tested.json()["detail"] == "Provider connection not found"

    for body in (patched.json(), deleted.json(), tested.json()):
        assert _PLATFORM_SECRET not in str(body)


@pytest.mark.asyncio
async def test_system_workspace_hidden_and_membership_inert(
    client: httpx.AsyncClient, db_session
) -> None:
    """The system workspace never appears in workspace lists, and a forged
    membership row on it grants NOTHING (``get_membership`` fails closed)."""
    await _register(client, "system-member@example.com")
    platform_id = await _seed_platform_connection_id(db_session)

    from sqlalchemy import select

    from app.models.user import User
    from app.models.workspace import Workspace, WorkspaceMember

    user = await db_session.scalar(
        select(User).where(User.email == "system-member@example.com")
    )
    system = await db_session.scalar(
        select(Workspace).where(Workspace.is_system.is_(True))
    )
    assert user is not None and system is not None
    # A membership row naming the system workspace exists (e.g. seeded by a
    # future provisioning flow) — it must stay inert.
    db_session.add(
        WorkspaceMember(workspace_id=system.id, user_id=user.id, role="owner")
    )
    await db_session.commit()

    listed = await client.get("/api/v1/workspaces")
    assert listed.status_code == 200
    workspace_ids = {w["id"] for w in listed.json()}
    assert str(system.id) not in workspace_ids
    assert len(workspace_ids) == 1  # only the auto-created tenant workspace

    # Selecting the system workspace explicitly is indistinguishable from a
    # missing workspace (invariant 5).
    selected = await client.get(
        "/api/v1/provider-connections", headers={"X-Workspace-Id": str(system.id)}
    )
    assert selected.status_code == 404
    assert selected.json()["detail"] == "Workspace not found"
    assert _PLATFORM_SECRET not in str(selected.json())
    assert platform_id not in str(selected.json())
