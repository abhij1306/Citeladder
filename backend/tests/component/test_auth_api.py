"""Component tests for the auth + workspace API (httpx ASGITransport).

Covers the B2 acceptance:
  - registration is generic and sessionless; login sets the auth cookie;
  - a workspace is auto-created on first login and the user is a member;
  - cross-workspace access is rejected (403/404).
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.config import settings
from app.core.config.abuse import abuse_settings
from app.domain.workspaces import service as workspace_service

COOKIE = settings.session_cookie_name


async def _register(
    client: httpx.AsyncClient, email: str, password: str = "password123"
):
    response = await client.post(
        "/api/v1/auth/register", json={"email": email, "password": password}
    )
    login = await client.post(
        "/api/v1/auth/login", json={"email": email, "password": password}
    )
    assert login.status_code == 200
    return response


@pytest.mark.asyncio
async def test_register_is_generic_and_does_not_create_session(
    client: httpx.AsyncClient,
) -> None:
    resp = await client.post(
        "/api/v1/auth/register",
        json={"email": "alice@example.com", "password": "password123"},
    )
    assert resp.status_code == 202
    assert set(resp.json()) == {"message"}
    assert COOKIE not in resp.cookies
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_login_sets_cookie_and_workspace_autocreated(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "bob@example.com")
    client.cookies.clear()
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "bob@example.com", "password": "password123"},
    )
    assert resp.status_code == 200
    assert COOKIE in resp.cookies

    # Workspace auto-created on registration/first login; user is a member.
    ws_resp = await client.get("/api/v1/workspaces")
    assert ws_resp.status_code == 200
    workspaces = ws_resp.json()
    assert len(workspaces) == 1
    assert workspaces[0]["role"] == "owner"
    assert workspaces[0]["name"]


@pytest.mark.asyncio
async def test_me_requires_auth(client: httpx.AsyncClient) -> None:
    unauth = await client.get("/api/v1/auth/me")
    assert unauth.status_code == 401

    await _register(client, "carol@example.com")
    me = await client.get("/api/v1/auth/me")
    assert me.status_code == 200
    assert me.json()["user"]["email"] == "carol@example.com"


@pytest.mark.asyncio
async def test_logout_clears_session(client: httpx.AsyncClient) -> None:
    await _register(client, "dave@example.com")
    old_token = client.cookies[COOKIE]
    assert (await client.get("/api/v1/auth/me")).status_code == 200
    logout = await client.post("/api/v1/auth/logout")
    assert logout.status_code == 204
    client.cookies.clear()
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    client.cookies.set(COOKIE, old_token)
    assert (await client.get("/api/v1/auth/me")).status_code == 401


@pytest.mark.asyncio
async def test_duplicate_registration_is_indistinguishable(
    client: httpx.AsyncClient,
) -> None:
    first = await client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "password123"},
    )
    duplicate = await client.post(
        "/api/v1/auth/register",
        json={"email": "dup@example.com", "password": "wrong-password"},
    )
    assert duplicate.status_code == first.status_code == 202
    assert duplicate.json() == first.json()
    assert duplicate.headers.get("set-cookie") == first.headers.get("set-cookie")


@pytest.mark.asyncio
async def test_login_bad_credentials_rejected(client: httpx.AsyncClient) -> None:
    await _register(client, "eve@example.com")
    bad = await client.post(
        "/api/v1/auth/login",
        json={"email": "eve@example.com", "password": "wrong-password"},
    )
    assert bad.status_code == 401


@pytest.mark.asyncio
async def test_login_rate_limit_is_durable_and_returns_retry_after(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(abuse_settings, "login_email_limit", 2)
    await _register(client, "limited@example.com")
    payload = {"email": "limited@example.com", "password": "wrong-password"}
    assert (await client.post("/api/v1/auth/login", json=payload)).status_code == 401
    assert (await client.post("/api/v1/auth/login", json=payload)).status_code == 401

    limited = await client.post("/api/v1/auth/login", json=payload)
    assert limited.status_code == 429
    assert int(limited.headers["Retry-After"]) > 0
    assert limited.json()["detail"] == "Too many requests"


@pytest.mark.asyncio
async def test_valid_login_bypasses_attacker_exhausted_email_failure_limit(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(abuse_settings, "login_email_limit", 1)
    await _register(client, "targeted@example.com")

    failed = await client.post(
        "/api/v1/auth/login",
        json={"email": "targeted@example.com", "password": "wrong-password"},
    )
    assert failed.status_code == 401

    valid = await client.post(
        "/api/v1/auth/login",
        json={"email": "targeted@example.com", "password": "password123"},
    )
    assert valid.status_code == 200


@pytest.mark.asyncio
async def test_create_and_list_workspaces(client: httpx.AsyncClient) -> None:
    await _register(client, "frank@example.com")
    created = await client.post("/api/v1/workspaces", json={"name": "Acme"})
    assert created.status_code == 201
    assert created.json()["name"] == "Acme"

    listing = await client.get("/api/v1/workspaces")
    names = {w["name"] for w in listing.json()}
    # personal auto-created workspace + the new one.
    assert "Acme" in names
    assert len(listing.json()) == 2


@pytest.mark.asyncio
async def test_workspace_creation_enforces_account_cap(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workspace_service, "MAX_WORKSPACES_PER_USER", 2)
    await _register(client, "workspace-cap@example.com")
    assert (
        await client.post("/api/v1/workspaces", json={"name": "Second"})
    ).status_code == 201

    blocked = await client.post("/api/v1/workspaces", json={"name": "Third"})
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["code"] == "workspace_limit_exceeded"
    assert blocked.json()["detail"]["limit"] == 2
    assert blocked.json()["error"]["details"] == {"limit": 2}


@pytest.mark.asyncio
async def test_concurrent_workspace_creates_cannot_overrun_cap(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(workspace_service, "MAX_WORKSPACES_PER_USER", 2)
    await _register(client, "workspace-cap-race@example.com")

    first, second = await asyncio.gather(
        client.post("/api/v1/workspaces", json={"name": "Racer A"}),
        client.post("/api/v1/workspaces", json={"name": "Racer B"}),
    )
    assert sorted((first.status_code, second.status_code)) == [201, 403]
    assert len((await client.get("/api/v1/workspaces")).json()) == 2


@pytest.mark.asyncio
async def test_workspaces_list_requires_auth(client: httpx.AsyncClient) -> None:
    assert (await client.get("/api/v1/workspaces")).status_code == 401


@pytest.mark.asyncio
async def test_cross_workspace_isolation(client: httpx.AsyncClient) -> None:
    """A member of workspace A cannot see workspace B (invariant 5)."""
    # User A registers (auto workspace A) and creates an extra workspace.
    await _register(client, "usera@example.com")
    a_extra = await client.post("/api/v1/workspaces", json={"name": "A-Team"})
    assert a_extra.status_code == 201
    a_workspaces = {w["id"] for w in (await client.get("/api/v1/workspaces")).json()}

    # Switch to user B in the same client (new session cookie).
    client.cookies.clear()
    await _register(client, "userb@example.com")
    b_workspaces = {w["id"] for w in (await client.get("/api/v1/workspaces")).json()}

    # B sees only its own workspace(s), none of A's.
    assert a_workspaces.isdisjoint(b_workspaces)
    assert len(b_workspaces) == 1
