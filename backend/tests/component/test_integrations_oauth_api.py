"""Component tests for the integrations OAuth connect API (I3).

Drives the real 302 start/callback flow through the ASGI app with a fake
OAuth server injected via ``httpx.MockTransport`` (the connector test seam).
Covers: the token round-trip onto the grant (Fernet-encrypted at rest), the
shared-grant shape (one Google consent ⇒ gsc + ga4 connections on ONE
grant), atomic one-time state consumption (replay rejected), cross-user and
cross-workspace state rejection, exchange-failure landing, the Microsoft
(Bing) transport, and that no token/client secret appears in any response or
log line (invariant 6).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from sqlalchemy import delete, func, select, update

from app.connectors.integrations import oauth as integration_oauth
from app.core.config import settings
from app.core.config.integrations_transport import (
    INTEGRATION_OAUTH_TRANSACTION_COOKIE,
    INTEGRATION_OAUTH_TRANSACTION_COOKIE_PATH,
)
from app.core.config.oauth import oauth_settings
from app.core.security import decrypt_secret
from app.models.integrations import (
    IntegrationConnection,
    IntegrationEvent,
    IntegrationOAuthGrant,
    IntegrationOAuthState,
)
from app.models.workspace import WorkspaceMember

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "integrations"
_BASE = "/api/v1/integrations"

_GOOGLE_CLIENT_ID = "test-google-client-id"
_GOOGLE_CLIENT_SECRET = "test-google-client-secret"  # pragma: allowlist secret
_MS_CLIENT_ID = "test-ms-client-id"
_MS_CLIENT_SECRET = "test-ms-client-secret"  # pragma: allowlist secret
_SHOPIFY_CLIENT_ID = "test-shopify-client-id"
_SHOPIFY_CLIENT_SECRET = "test-shopify-client-secret"  # pragma: allowlist secret
_SHOP = "volt-city.myshopify.com"

_GOOGLE_SCOPES = {
    "https://www.googleapis.com/auth/webmasters.readonly",
    "https://www.googleapis.com/auth/analytics.readonly",
}


def _landing(query: str) -> str:
    """Expected absolute frontend landing URL (contract C2).

    Absolute because the provider navigates the browser to the *backend*
    callback: a bare path would resolve against the backend origin, which
    serves no ``/settings`` route.
    """
    return f"{settings.frontend_url.rstrip('/')}/settings?tab=integrations&{query}"


def _callback_uri(provider: str) -> str:
    """Expected registered redirect URI: the APP origin, not ``base_url``.

    Anchored on ``frontend_url`` so the provider's post-consent navigation
    returns through the same-origin proxy and carries the session cookie the
    callback authenticates with (a backend-origin callback arrives cookieless
    whenever the app is served from a different host — 127.0.0.1 vs
    localhost, or a tunnel — and 401s).
    """
    return (
        f"{settings.frontend_url.rstrip('/')}"
        f"/api/v1/integrations/oauth/{provider}/callback"
    )


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


def _google_tokens() -> dict:
    return _fixture("google_token_response.json")


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


@pytest.fixture
def _oauth_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "integration_google_client_id", _GOOGLE_CLIENT_ID)
    monkeypatch.setattr(
        settings, "integration_google_client_secret", _GOOGLE_CLIENT_SECRET
    )
    monkeypatch.setattr(settings, "integration_microsoft_client_id", _MS_CLIENT_ID)
    monkeypatch.setattr(
        settings, "integration_microsoft_client_secret", _MS_CLIENT_SECRET
    )
    monkeypatch.setattr(settings, "integration_shopify_client_id", _SHOPIFY_CLIENT_ID)
    monkeypatch.setattr(
        settings, "integration_shopify_client_secret", _SHOPIFY_CLIENT_SECRET
    )


class _FakeOAuthServer:
    """MockTransport-backed fake OAuth server routing by host + path."""

    def __init__(
        self,
        *,
        google_token_status: int = 200,
        google_token_payload: dict | None = None,
        microsoft_token_status: int = 200,
    ) -> None:
        self.google_token_status = google_token_status
        self.google_token_payload = google_token_payload or _google_tokens()
        self.microsoft_token_status = microsoft_token_status
        self.requests: list[httpx.Request] = []

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host = request.url.host
        if host == "oauth2.googleapis.com" and request.url.path == "/token":
            return httpx.Response(
                self.google_token_status, json=self.google_token_payload
            )
        if host == "oauth2.googleapis.com" and request.url.path == "/revoke":
            return httpx.Response(200)
        if host == "www.googleapis.com":
            return httpx.Response(200, json=_fixture("gsc_sites_response.json"))
        if host == _SHOP and request.url.path == "/admin/oauth/access_token":
            return httpx.Response(
                200,
                json={
                    # pragma: allowlist secret
                    "access_token": "shpat_fake-offline-token",
                    "scope": "read_products,read_orders",
                },
            )
        if host == "login.microsoftonline.com" and request.url.path.endswith("/token"):
            if self.microsoft_token_status != 200:
                return httpx.Response(
                    self.microsoft_token_status,
                    json={
                        "error": "temporarily_unavailable",
                        "error_description": "microsoft boom",
                    },
                )
            return httpx.Response(200, json=_fixture("microsoft_token_response.json"))
        return httpx.Response(404, json={"error": "unexpected"})

    def token_calls(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path.endswith("/token")]

    def shopify_token_calls(self) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.path == "/admin/oauth/access_token"]


@pytest.fixture
def _fake_oauth(monkeypatch: pytest.MonkeyPatch) -> _FakeOAuthServer:
    """Inject the fake OAuth server into the domain service's client factory."""
    server = _FakeOAuthServer()

    def _build(transport_kind: str, *, transport=None, provider_account_ref: str = ""):
        return integration_oauth.IntegrationOAuthClient(
            transport_kind,
            transport=server.transport,
            provider_account_ref=provider_account_ref,
        )

    monkeypatch.setattr(integration_oauth, "build_oauth_client", _build)
    return server


async def _start(client: httpx.AsyncClient, provider: str, **kwargs) -> httpx.Response:
    resp = await client.get(f"{_BASE}/oauth/{provider}/start", **kwargs)
    assert resp.status_code == 302
    return resp


def _state_from_start(resp: httpx.Response) -> str:
    location = resp.headers["location"]
    return parse_qs(urlsplit(location).query)["state"][0]


async def _callback(
    client: httpx.AsyncClient, provider: str, state: str, code: str = "fake-auth-code"
) -> httpx.Response:
    return await client.get(
        f"{_BASE}/oauth/{provider}/callback",
        params={"code": code, "state": state},
    )


async def _grants(db_session) -> list[IntegrationOAuthGrant]:
    return list((await db_session.execute(select(IntegrationOAuthGrant))).scalars())


async def _connections(db_session) -> list[IntegrationConnection]:
    return list((await db_session.execute(select(IntegrationConnection))).scalars())


@pytest.mark.asyncio
async def test_google_connect_happy_path_shared_grant(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _register(client, "int-google@example.com")
    start = await _start(client, "gsc")
    location = start.headers["location"]
    assert location.startswith("https://accounts.google.com/o/oauth2/v2/auth?")
    query = parse_qs(urlsplit(location).query)
    assert query["client_id"] == [_GOOGLE_CLIENT_ID]
    assert query["redirect_uri"] == [_callback_uri("gsc")]
    assert query["response_type"] == ["code"]
    assert set(query["scope"][0].split(" ")) == _GOOGLE_SCOPES
    assert query["access_type"] == ["offline"]
    state = query["state"][0]
    # The client secret never leaves the server (invariant 6).
    assert _GOOGLE_CLIENT_SECRET not in location

    cookie = start.headers["set-cookie"]
    assert f"{INTEGRATION_OAUTH_TRANSACTION_COOKIE}=" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie
    assert f"Path={INTEGRATION_OAUTH_TRANSACTION_COOKIE_PATH}" in cookie
    assert f"Max-Age={oauth_settings.state_ttl_seconds}" in cookie
    transaction_nonce = client.cookies.get(INTEGRATION_OAUTH_TRANSACTION_COOKIE)
    assert transaction_nonce
    assert transaction_nonce not in location
    assert ("Secure" in cookie) is (
        settings.app_env.lower()
        not in {"", "development", "dev", "local", "test", "testing"}
    )

    # The state row is persisted, unconsumed, and bound to the workspace/user.
    state_row = (await db_session.execute(select(IntegrationOAuthState))).scalar_one()
    assert state_row.consumed_at is None
    assert state_row.provider == "gsc"

    with caplog.at_level(logging.DEBUG):
        callback = await _callback(client, "gsc", state)
    assert callback.status_code == 302
    assert callback.headers["location"] == _landing("connected=gsc")
    assert "Max-Age=0" in callback.headers["set-cookie"]

    # One grant carries the Fernet-encrypted tokens (never the plaintext).
    (grant,) = await _grants(db_session)
    assert grant.transport == "google_oauth"
    assert grant.status == "connected"
    expected = _google_tokens()
    assert grant.access_token_encrypted != expected["access_token"]
    assert decrypt_secret(grant.access_token_encrypted) == expected["access_token"]
    assert decrypt_secret(grant.refresh_token_encrypted) == expected["refresh_token"]
    assert grant.token_expires_at is not None
    assert set(grant.granted_scopes) == _GOOGLE_SCOPES

    # Shared-grant shape: one consent ⇒ gsc + ga4 rows on the ONE grant.
    connections = await _connections(db_session)
    assert {c.provider for c in connections} == {"gsc", "ga4"}
    assert {c.grant_id for c in connections} == {grant.id}
    assert {c.workspace_id for c in connections} == {grant.workspace_id}

    # The state row is consumed and the connect event appended.
    await db_session.refresh(state_row)
    assert state_row.consumed_at is not None
    events = list((await db_session.execute(select(IntegrationEvent))).scalars())
    assert [e.event_type for e in events] == ["integration.connected"]
    assert events[0].grant_id == grant.id
    assert sorted(events[0].payload["providers"]) == ["ga4", "gsc"]

    # Invariant 6: no token or client secret in any response or log line.
    forbidden = [
        expected["access_token"],
        expected["refresh_token"],
        _GOOGLE_CLIENT_SECRET,
    ]
    blob = caplog.text + start.text + callback.text
    for value in forbidden:
        assert value not in blob
    assert "access_token" not in callback.text


@pytest.mark.asyncio
async def test_callback_uses_transaction_nonce_without_a_valid_login_session(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    await _register(client, "int-stale-session@example.com")
    state = _state_from_start(await _start(client, "gsc"))
    client.cookies.delete(settings.session_cookie_name)
    client.cookies.set(settings.session_cookie_name, "stale-session", path="/")

    callback = await _callback(client, "gsc", state)

    assert callback.status_code == 302
    assert callback.headers["location"] == _landing("connected=gsc")
    assert len(_fake_oauth.token_calls()) == 1
    assert len(await _grants(db_session)) == 1


@pytest.mark.asyncio
async def test_missing_and_wrong_transaction_nonce_fail_before_exchange(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    await _register(client, "int-nonce@example.com")
    missing_state = _state_from_start(await _start(client, "gsc"))
    client.cookies.delete(INTEGRATION_OAUTH_TRANSACTION_COOKIE)
    missing = await _callback(client, "gsc", missing_state)
    assert missing.headers["location"] == _landing("error=oauth_state_invalid")

    wrong_state = _state_from_start(await _start(client, "gsc"))
    client.cookies.delete(INTEGRATION_OAUTH_TRANSACTION_COOKIE)
    client.cookies.set(
        INTEGRATION_OAUTH_TRANSACTION_COOKIE,
        "wrong-nonce",
        path=INTEGRATION_OAUTH_TRANSACTION_COOKIE_PATH,
    )
    wrong = await _callback(client, "gsc", wrong_state)
    assert wrong.headers["location"] == _landing("error=oauth_state_invalid")
    assert _fake_oauth.token_calls() == []
    assert await _grants(db_session) == []


@pytest.mark.asyncio
async def test_expired_state_and_lost_membership_fail_before_exchange(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    await _register(client, "int-state-guards@example.com")
    expired_state = _state_from_start(await _start(client, "gsc"))
    expired_row = (await db_session.execute(select(IntegrationOAuthState))).scalar_one()
    await db_session.execute(
        update(IntegrationOAuthState)
        .where(IntegrationOAuthState.id == expired_row.id)
        .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
    )
    await db_session.commit()
    expired = await _callback(client, "gsc", expired_state)
    assert expired.headers["location"] == _landing("error=oauth_state_invalid")

    membership_state = _state_from_start(await _start(client, "gsc"))
    membership_row = (
        await db_session.execute(
            select(IntegrationOAuthState).where(
                IntegrationOAuthState.expires_at > datetime.now(UTC)
            )
        )
    ).scalar_one()
    await db_session.execute(
        delete(WorkspaceMember).where(
            WorkspaceMember.workspace_id == membership_row.workspace_id,
            WorkspaceMember.user_id == membership_row.user_id,
        )
    )
    await db_session.commit()
    lost = await _callback(client, "gsc", membership_state)
    assert lost.headers["location"] == _landing("error=oauth_state_invalid")
    assert _fake_oauth.token_calls() == []
    assert await _grants(db_session) == []


@pytest.mark.asyncio
async def test_replayed_state_rejected(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    await _register(client, "int-replay@example.com")
    state = _state_from_start(await _start(client, "gsc"))
    first = await _callback(client, "gsc", state)
    assert "connected=gsc" in first.headers["location"]

    replay = await _callback(client, "gsc", state)
    assert replay.status_code == 302
    assert replay.headers["location"] == _landing("error=oauth_state_invalid")
    # The exchange ran exactly once; the grant graph is unchanged.
    assert len(_fake_oauth.token_calls()) == 1
    assert len(await _grants(db_session)) == 1
    assert len(await _connections(db_session)) == 2


@pytest.mark.asyncio
async def test_cross_user_state_rejected(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    await _register(client, "int-owner@example.com")
    state = _state_from_start(await _start(client, "gsc"))

    # Logout/login clears the transaction cookie, so an account switch cannot
    # carry the owner's integration transaction into the new account.
    await client.post("/api/v1/auth/logout")
    await _register(client, "int-intruder@example.com")
    callback = await _callback(client, "gsc", state)
    assert callback.status_code == 302
    assert callback.headers["location"] == _landing("error=oauth_state_invalid")
    assert _fake_oauth.token_calls() == []
    assert await _grants(db_session) == []


@pytest.mark.asyncio
async def test_workspace_comes_from_verified_state_not_client(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    await _register(client, "int-crossws@example.com")
    second = await client.post("/api/v1/workspaces", json={"name": "Second WS"})
    assert second.status_code == 201
    ws2 = second.json()["id"]

    # Start bound to the SECOND workspace via the active-workspace header.
    start = await _start(client, "gsc", headers={"X-Workspace-Id": ws2})
    state = _state_from_start(start)

    # The callback carries NO workspace selection: the grant must land on the
    # state-bound workspace, never on a client-influenced one (invariant 5).
    callback = await client.get(
        f"{_BASE}/oauth/gsc/callback",
        params={"code": "fake-auth-code", "state": state},
    )
    assert "connected=gsc" in callback.headers["location"]
    (grant,) = await _grants(db_session)
    assert str(grant.workspace_id) == ws2


@pytest.mark.asyncio
async def test_callback_landing_is_absolute_frontend_url(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The landing target is absolute and points at the frontend origin.

    Regression guard: the provider navigates the browser to the *backend*
    callback, so a relative ``/settings?...`` target resolved against the
    backend origin and dead-ended on a 404 even though the connect succeeded.
    """
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:3000")
    await _register(client, "int-absolute-landing@example.com")
    state = _state_from_start(await _start(client, "gsc"))
    callback = await _callback(client, "gsc", state)

    location = callback.headers["location"]
    assert location == ("http://localhost:3000/settings?tab=integrations&connected=gsc")
    # An absolute URL on the frontend origin, NOT a backend-relative path.
    split = urlsplit(location)
    assert split.scheme == "http"
    assert split.netloc == "localhost:3000"
    assert split.path == "/settings"

    # A trailing slash on the configured origin must not double up.
    monkeypatch.setattr(settings, "frontend_url", "http://localhost:3000/")
    state2 = _state_from_start(await _start(client, "ga4"))
    callback2 = await _callback(client, "ga4", state2)
    assert callback2.headers["location"] == (
        "http://localhost:3000/settings?tab=integrations&connected=ga4"
    )


@pytest.mark.asyncio
async def test_redirect_uri_is_app_origin_not_request_host(
    client: httpx.AsyncClient,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The registered redirect URI tracks ``frontend_url``, never the host.

    Regression guard: it was built from ``request.base_url``. The browser
    reaches the backend through the Next ``rewrites()`` proxy, which sets
    ``changeOrigin`` — so the backend sees its OWN host and handed the
    provider a BACKEND-origin redirect URI. The post-consent navigation then
    bypassed the proxy and arrived without the app-origin session cookie,
    and the callback's ``get_current_user`` 401'd ("Not authenticated")
    whenever the app was served from a different host than the backend
    (127.0.0.1 vs localhost, or a tunnel).
    """
    await _register(client, "int-redirect-origin@example.com")
    monkeypatch.setattr(settings, "frontend_url", "https://app.example.test/")

    query = parse_qs(urlsplit((await _start(client, "gsc")).headers["location"]).query)
    # No trailing-slash doubling, and the request's own host is absent.
    assert query["redirect_uri"] == [
        "https://app.example.test/api/v1/integrations/oauth/gsc/callback"
    ]
    assert "testserver" not in query["redirect_uri"][0]


@pytest.mark.asyncio
async def test_exchange_failure_landing_and_state_consumed(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    _fake_oauth.google_token_status = 400
    _fake_oauth.google_token_payload = _fixture("google_token_error.json")
    await _register(client, "int-exchange-fail@example.com")
    state = _state_from_start(await _start(client, "gsc"))
    callback = await _callback(client, "gsc", state)
    assert callback.status_code == 302
    assert callback.headers["location"] == _landing("error=oauth_exchange_failed")
    assert await _grants(db_session) == []
    # The state was consumed before the exchange — a retry is a replay.
    retry = await _callback(client, "gsc", state)
    assert "oauth_state_invalid" in retry.headers["location"]
    assert len(_fake_oauth.token_calls()) == 1


@pytest.mark.asyncio
async def test_provider_error_param_and_missing_params(
    client: httpx.AsyncClient,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    await _register(client, "int-params@example.com")
    denied = await client.get(
        f"{_BASE}/oauth/gsc/callback",
        params={"error": "access_denied", "state": "whatever"},
    )
    assert denied.status_code == 302
    assert "error=oauth_exchange_failed" in denied.headers["location"]

    missing = await client.get(f"{_BASE}/oauth/gsc/callback")
    assert missing.status_code == 302
    assert "error=oauth_state_invalid" in missing.headers["location"]
    assert _fake_oauth.token_calls() == []


@pytest.mark.asyncio
async def test_microsoft_connect_attaches_bing_connection(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    await _register(client, "int-bing@example.com")
    start = await _start(client, "bing")
    location = start.headers["location"]
    assert location.startswith(
        "https://login.microsoftonline.com/common/oauth2/v2.0/authorize?"
    )
    query = parse_qs(urlsplit(location).query)
    assert query["client_id"] == [_MS_CLIENT_ID]
    # The pinned Bing Webmaster scope (I12) + offline_access for refresh.
    assert set(query["scope"][0].split(" ")) == {
        "offline_access",
        "https://webmaster.bing.com/api/webmaster.manage",
    }
    # Google-only offline/consent params are not sent to Microsoft.
    assert "access_type" not in query
    assert _MS_CLIENT_SECRET not in location

    callback = await _callback(client, "bing", _state_from_start(start))
    assert callback.headers["location"] == _landing("connected=bing")

    (grant,) = await _grants(db_session)
    assert grant.transport == "microsoft_oauth"
    assert grant.status == "connected"
    expected = _fixture("microsoft_token_response.json")
    assert decrypt_secret(grant.access_token_encrypted) == expected["access_token"]
    assert decrypt_secret(grant.refresh_token_encrypted) == expected["refresh_token"]
    assert set(grant.granted_scopes) == {
        "offline_access",
        "https://webmaster.bing.com/api/webmaster.manage",
    }
    connections = await _connections(db_session)
    assert [c.provider for c in connections] == ["bing"]
    assert connections[0].grant_id == grant.id


@pytest.mark.asyncio
async def test_bing_reconnect_keeps_single_grant_and_connection(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    """A second Bing consent rotates tokens on the ONE Microsoft grant."""
    await _register(client, "int-bing-reconnect@example.com")
    await _callback(client, "bing", _state_from_start(await _start(client, "bing")))
    (grant,) = await _grants(db_session)
    grant_id = grant.id

    state2 = _state_from_start(await _start(client, "bing"))
    callback2 = await _callback(client, "bing", state2)
    assert "connected=bing" in callback2.headers["location"]

    # Find-or-create: still ONE microsoft_oauth grant, ONE bing connection.
    grants = await _grants(db_session)
    assert [g.id for g in grants] == [grant_id]
    connections = await _connections(db_session)
    assert [c.provider for c in connections] == ["bing"]
    assert len(_fake_oauth.token_calls()) == 2


@pytest.mark.asyncio
async def test_bing_exchange_failure_landing(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    await _register(client, "int-bing-xfail@example.com")
    _fake_oauth.microsoft_token_status = 400
    state = _state_from_start(await _start(client, "bing"))
    callback = await _callback(client, "bing", state)
    assert callback.status_code == 302
    assert callback.headers["location"] == _landing("error=oauth_exchange_failed")
    assert await _grants(db_session) == []
    assert await _connections(db_session) == []
    # The state was consumed before the exchange — a retry is a replay.
    retry = await _callback(client, "bing", state)
    assert "oauth_state_invalid" in retry.headers["location"]


@pytest.mark.asyncio
async def test_reconnect_rotates_tokens_on_same_grant(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    await _register(client, "int-reconnect@example.com")
    state = _state_from_start(await _start(client, "gsc"))
    await _callback(client, "gsc", state)
    (grant,) = await _grants(db_session)
    grant_id = grant.id

    rotated = dict(_google_tokens())
    # pragma: allowlist secret
    rotated["access_token"] = "ya29.fake-rotated-access-token"
    _fake_oauth.google_token_payload = rotated
    state2 = _state_from_start(await _start(client, "gsc"))
    callback2 = await _callback(client, "gsc", state2)
    assert "connected=gsc" in callback2.headers["location"]

    # Find-or-create: still ONE grant, tokens rotated, no duplicate rows.
    grants = await _grants(db_session)
    assert [g.id for g in grants] == [grant_id]
    await db_session.refresh(grants[0])
    assert decrypt_secret(grants[0].access_token_encrypted) == rotated["access_token"]
    connections = await _connections(db_session)
    assert {c.provider for c in connections} == {"gsc", "ga4"}
    assert len(connections) == 2
    count = (
        await db_session.execute(select(func.count(IntegrationEvent.id)))
    ).scalar_one()
    assert count == 2


@pytest.mark.asyncio
async def test_unknown_provider_404(
    client: httpx.AsyncClient, _oauth_credentials: None
) -> None:
    await _register(client, "int-unknown@example.com")
    start = await client.get(f"{_BASE}/oauth/netscape/start")
    assert start.status_code == 404
    callback = await client.get(f"{_BASE}/oauth/netscape/callback")
    assert callback.status_code == 404


@pytest.mark.asyncio
async def test_unauthenticated_flow_rejected(client: httpx.AsyncClient) -> None:
    start = await client.get(f"{_BASE}/oauth/gsc/start")
    assert start.status_code == 401
    callback = await client.get(
        f"{_BASE}/oauth/gsc/callback", params={"code": "x", "state": "y"}
    )
    assert callback.status_code == 302
    assert callback.headers["location"] == _landing("error=oauth_state_invalid")


@pytest.mark.asyncio
async def test_start_unconfigured_provider_503(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "integration_google_client_id", "")
    monkeypatch.setattr(settings, "integration_google_client_secret", "")
    await _register(client, "int-unconfigured@example.com")
    resp = await client.get(f"{_BASE}/oauth/gsc/start")
    assert resp.status_code == 503
    body = resp.json()
    assert body["detail"] == "oauth_not_configured"
    assert body["error"]["code"] == "oauth_not_configured"
    assert body["error"]["message"] == "The integration provider is not configured"


@pytest.mark.asyncio
async def test_state_minted_for_one_provider_cannot_complete_another(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    await _register(client, "int-provider-mix@example.com")
    state = _state_from_start(await _start(client, "gsc"))
    callback = await _callback(client, "ga4", state)
    assert "error=oauth_state_invalid" in callback.headers["location"]
    assert _fake_oauth.token_calls() == []
    assert await _grants(db_session) == []
    # Every callback clears the browser transaction. A fresh Connect action is
    # required even though the mismatched attempt did not consume the DB row.
    fresh = _state_from_start(await _start(client, "gsc"))
    ok = await _callback(client, "gsc", fresh)
    assert "connected=gsc" in ok.headers["location"]


@pytest.mark.asyncio
async def test_auth_scaffold_state_cannot_drive_connect(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    """A sign-in scaffold state (no jti/workspace/user claims) is rejected."""
    from app.core.security import create_oauth_state

    await _register(client, "int-scaffold@example.com")
    scaffold_state, _nonce = create_oauth_state("gsc")
    callback = await _callback(client, "gsc", scaffold_state)
    assert "error=oauth_state_invalid" in callback.headers["location"]
    assert _fake_oauth.token_calls() == []
    assert await _grants(db_session) == []


@pytest.mark.asyncio
async def test_state_rows_are_bound_per_mint(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
) -> None:
    """Starting again replaces the browser's one pending transaction nonce."""
    await _register(client, "int-jti@example.com")
    state1 = _state_from_start(await _start(client, "gsc"))
    state2 = _state_from_start(await _start(client, "gsc"))
    assert state1 != state2
    rows = list((await db_session.execute(select(IntegrationOAuthState))).scalars())
    assert len(rows) == 2
    assert len({r.jti for r in rows}) == 2
    stale = await _callback(client, "gsc", state1)
    assert "oauth_state_invalid" in stale.headers["location"]
    # The failed callback clears the nonce, so resume through a fresh start.
    state3 = _state_from_start(await _start(client, "gsc"))
    ok = await _callback(client, "gsc", state3)
    assert "connected=gsc" in ok.headers["location"]
    rows = list((await db_session.execute(select(IntegrationOAuthState))).scalars())
    for row in rows:
        await db_session.refresh(row)
    consumed = [row for row in rows if row.consumed_at is not None]
    assert len(consumed) == 1
    # uuid sanity: the grant id is a real UUID.
    (grant,) = await _grants(db_session)
    assert isinstance(grant.id, uuid.UUID)


# ---------------------------------------------------------------------------
# Shopify transport: per-shop authorize URL, callback HMAC, three-way shop
# match, offline (non-refreshable) token grant (commerce suite WS-B task 2).
# ---------------------------------------------------------------------------


def _shopify_signed_callback_params(**params: str) -> dict[str, str]:
    """Sign callback params exactly as Shopify would (HMAC-SHA256 hex)."""
    canonical = "&".join(f"{key}={value}" for key, value in sorted(params.items()))
    signature = hmac.new(
        _SHOPIFY_CLIENT_SECRET.encode("utf-8"),
        canonical.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {**params, "hmac": signature}


async def _shopify_callback(
    client: httpx.AsyncClient, state: str, *, shop: str = _SHOP, tamper: str = ""
) -> httpx.Response:
    params = _shopify_signed_callback_params(
        code="fake-auth-code", shop=shop, state=state, timestamp="1700000000"
    )
    if tamper:
        params[tamper] = "tampered" if tamper != "hmac" else "0" * 64
    return await client.get(f"{_BASE}/oauth/shopify/callback", params=params)


@pytest.mark.asyncio
async def test_shopify_connect_happy_path(
    client: httpx.AsyncClient,
    db_session,
    _oauth_credentials: None,
    _fake_oauth: _FakeOAuthServer,
    caplog: pytest.LogCaptureFixture,
) -> None:
    await _register(client, "int-shopify@example.com")
    # A bare shop name canonicalizes onto the per-shop authorize endpoint.
    start = await client.get(
        f"{_BASE}/oauth/shopify/start", params={"shop": " Volt-City "}
    )
    assert start.status_code == 302
    location = start.headers["location"]
    assert location.startswith(f"https://{_SHOP}/admin/oauth/authorize?")
    query = parse_qs(urlsplit(location).query)
    assert query["client_id"] == [_SHOPIFY_CLIENT_ID]
    assert query["redirect_uri"] == [_callback_uri("shopify")]
    # Comma-joined scopes; NO response_type/access_type/prompt extras.
    assert query["scope"] == ["read_products,read_orders"]
    assert "response_type" not in query
    assert "access_type" not in query
    assert "prompt" not in query
    assert _SHOPIFY_CLIENT_SECRET not in location
    state = query["state"][0]

    # The state row persists the per-shop target (and the JWT signs it).
    state_row = (await db_session.execute(select(IntegrationOAuthState))).scalar_one()
    assert state_row.provider == "shopify"
    assert state_row.provider_account_ref == _SHOP
    assert state_row.consumed_at is None

    with caplog.at_level(logging.DEBUG):
        callback = await _shopify_callback(client, state)
    assert callback.status_code == 302
    assert callback.headers["location"] == _landing("connected=shopify")

    # The offline token lands Fernet-encrypted on a shopify_oauth grant with
    # NO expiry (non-refreshable transport) and comma-split scopes.
    (grant,) = await _grants(db_session)
    assert grant.transport == "shopify_oauth"
    assert grant.status == "connected"
    assert decrypt_secret(grant.access_token_encrypted) == "shpat_fake-offline-token"
    assert grant.token_expires_at is None
    assert set(grant.granted_scopes) == {"read_products", "read_orders"}

    # One shopify connection bound to the canonical shop host.
    (connection,) = await _connections(db_session)
    assert connection.provider == "shopify"
    assert connection.account_ref == _SHOP
    assert connection.grant_id == grant.id

    # The exchange form was EXACTLY client_id/client_secret/code, sent to
    # the per-shop token endpoint — no grant_type, no redirect_uri.
    (token_call,) = _fake_oauth.shopify_token_calls()
    assert str(token_call.url) == f"https://{_SHOP}/admin/oauth/access_token"
    form = parse_qs(token_call.content.decode("utf-8"))
    assert set(form) == {"client_id", "client_secret", "code"}

    # State consumed + connect event; no token/secret in any log or body.
    await db_session.refresh(state_row)
    assert state_row.consumed_at is not None
    events = list((await db_session.execute(select(IntegrationEvent))).scalars())
    assert [e.event_type for e in events] == ["integration.connected"]
    assert events[0].payload["providers"] == ["shopify"]
    assert _SHOP not in str(events[0].payload.get("connection_ids"))
    forbidden = ["shpat_fake-offline-token", _SHOPIFY_CLIENT_SECRET]
    blob = caplog.text + start.text + callback.text + json.dumps(events[0].payload)
    for value in forbidden:
        assert value not in blob
