"""Property discovery + selection (the picker's backend).

A connected OAuth grant does not by itself tell a sync WHAT to pull. The
worker fetches from ``IntegrationConnection.account_ref`` and derivation
resolves that ref back to a project through an ACTIVE property mapping, so
until a property is selected a connection has nothing to sync. These tests
pin the three pieces that close that gap:

1. ``GET /integrations/{id}/properties`` lists what the grant can actually
   read at the provider, so a ref is chosen rather than typed.
2. Creating a mapping POINTS the connection at the selected property
   (``account_ref``), which is what makes the sync fetch a real URL.
3. Providers with no discoverable property list are an explicit 422.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from app.connectors.integrations import ga4 as ga4_connector
from app.connectors.integrations import gsc as gsc_connector
from app.connectors.integrations import oauth as integration_oauth
from app.core.security import decrypt_secret, encrypt_secret
from app.models.integrations import (
    IntegrationConnection,
    IntegrationOAuthGrant,
)
from app.models.project import OwnedDomain, Project
from app.models.workspace import Workspace
from tests.component.auth_helpers import register_and_login as _register

_BASE = "/api/v1/integrations"
_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "integrations"
_FAKE_ACCESS = "fake-seed-access-token"  # pragma: allowlist secret
_FAKE_REFRESH = "fake-seed-refresh-token"  # pragma: allowlist secret
_REFRESHED_ACCESS = "fake-rotated-access-token"  # pragma: allowlist secret


def _fixture(name: str) -> dict:
    return json.loads((_FIXTURES / name).read_text())


async def _seed_project(db_session, *, workspace_id: uuid.UUID) -> Project:
    """A project owning example.com — the GSC ref must resolve to it."""
    project = Project(workspace_id=workspace_id, name="Example")
    db_session.add(project)
    await db_session.flush()
    db_session.add(OwnedDomain(project_id=project.id, domain="example.com"))
    await db_session.commit()
    return project


async def _workspace_id(db_session) -> uuid.UUID:
    return (await db_session.execute(select(Workspace))).scalars().first().id


async def _seed(
    db_session,
    *,
    workspace_id: uuid.UUID,
    providers: tuple[str, ...] = ("gsc", "ga4"),
    transport: str = "google_oauth",
    account_ref: str = "",
) -> list[IntegrationConnection]:
    """Seed a connected grant whose connections have NO property selected."""
    grant = IntegrationOAuthGrant(
        workspace_id=workspace_id,
        transport=transport,
        access_token_encrypted=encrypt_secret(_FAKE_ACCESS),
        refresh_token_encrypted=encrypt_secret(_FAKE_REFRESH),
        token_expires_at=datetime.now(UTC) + timedelta(hours=1),
        granted_scopes=["scope-a"],
        status="connected",
    )
    db_session.add(grant)
    await db_session.flush()
    connections = [
        IntegrationConnection(
            workspace_id=workspace_id,
            grant_id=grant.id,
            provider=provider,
            label=f"{provider} label",
            account_ref=account_ref,
        )
        for provider in providers
    ]
    db_session.add_all(connections)
    await db_session.commit()
    return connections


class _FakeGoogle:
    """MockTransport fake for the two discovery endpoints."""

    def __init__(self, *, status: int = 200) -> None:
        self.status = status
        self.requests: list[httpx.Request] = []
        # Successive accountSummaries pages; the default is the single-page
        # fixture. Each entry is served in order.
        self.ga4_pages: list[dict] | None = None

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handler)

    def _handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.url.host == "oauth2.googleapis.com":
            # The token endpoint stays healthy regardless of ``status`` —
            # the discovery-failure tests are about the LISTING call.
            return httpx.Response(
                200,
                json={
                    "access_token": _REFRESHED_ACCESS,
                    "refresh_token": _FAKE_REFRESH,
                    "expires_in": 3600,
                    "token_type": "Bearer",
                },
            )
        if self.status != 200:
            return httpx.Response(self.status, json={"error": {"message": "boom"}})
        if request.url.host == "www.googleapis.com":
            return httpx.Response(200, json=_fixture("gsc_sites_response.json"))
        if request.url.host == "analyticsadmin.googleapis.com":
            if self.ga4_pages is None:
                return httpx.Response(
                    200, json=_fixture("ga4_account_summaries_response.json")
                )
            served = sum(
                1
                for r in self.requests[:-1]
                if r.url.host == "analyticsadmin.googleapis.com"
            )
            return httpx.Response(200, json=self.ga4_pages[served])
        return httpx.Response(404, json={"error": {"message": "unexpected"}})


@pytest.fixture
def _fake_google(monkeypatch: pytest.MonkeyPatch) -> _FakeGoogle:
    fake = _FakeGoogle()
    monkeypatch.setattr(
        gsc_connector,
        "build_gsc_client",
        lambda *, transport=None: gsc_connector.GscClient(transport=fake.transport),
    )
    monkeypatch.setattr(
        ga4_connector,
        "build_ga4_client",
        lambda *, transport=None: ga4_connector.Ga4Client(transport=fake.transport),
    )
    monkeypatch.setattr(
        integration_oauth,
        "build_oauth_client",
        lambda transport_kind, *, transport=None: (
            integration_oauth.IntegrationOAuthClient(
                transport_kind,
                transport=fake.transport,
            )
        ),
    )
    return fake


@pytest.mark.asyncio
async def test_lists_gsc_sites_excluding_unverified(
    client: httpx.AsyncClient, db_session, _fake_google: _FakeGoogle
) -> None:
    await _register(client, "prop-gsc@example.com")
    workspace_id = await _workspace_id(db_session)
    gsc, _ga4 = await _seed(db_session, workspace_id=workspace_id)

    resp = await client.get(f"{_BASE}/{gsc.id}/properties")

    assert resp.status_code == 200
    assert resp.json() == [
        {"property_ref": "sc-domain:example.com", "label": "sc-domain:example.com"},
        {
            "property_ref": "https://www.example.com/",
            "label": "https://www.example.com/",
        },
    ]


@pytest.mark.asyncio
async def test_lists_ga4_properties_as_bare_numeric_ids(
    client: httpx.AsyncClient, db_session, _fake_google: _FakeGoogle
) -> None:
    """Refs are the CANONICAL bare id, and unusable entries are skipped.

    The Admin API returns ``properties/123`` resource names; storing that
    spelling would split owner identity against the bare ids the rest of the
    system uses. A summary without a numeric id cannot be selected safely,
    so it is dropped rather than guessed into a ref.
    """
    await _register(client, "prop-ga4@example.com")
    workspace_id = await _workspace_id(db_session)
    _gsc, ga4 = await _seed(db_session, workspace_id=workspace_id)

    resp = await client.get(f"{_BASE}/{ga4.id}/properties")

    assert resp.status_code == 200
    body = resp.json()
    assert [row["property_ref"] for row in body] == [
        "123456789",
        "987654321",
        "555000111",
    ]
    # The account name disambiguates non-unique GA4 display names; a property
    # with no display name falls back to its id.
    assert body[0]["label"] == "Acme Web (Acme Group)"
    assert body[2]["label"] == "555000111 (Side Project)"


@pytest.mark.asyncio
async def test_ga4_listing_follows_next_page_token(
    client: httpx.AsyncClient, db_session, _fake_google: _FakeGoogle
) -> None:
    """Discovery pages ``accountSummaries`` to completion.

    An agency grant reads more accounts than one page carries. A truncated
    list is indistinguishable from "that is all you have" — the missing
    properties would simply never appear in the picker.
    """
    _fake_google.ga4_pages = [
        {
            "accountSummaries": [
                {
                    "displayName": "Page One",
                    "propertySummaries": [
                        {"property": "properties/111", "displayName": "First"}
                    ],
                }
            ],
            "nextPageToken": "tok-2",
        },
        {
            "accountSummaries": [
                {
                    "displayName": "Page Two",
                    "propertySummaries": [
                        {"property": "properties/222", "displayName": "Second"}
                    ],
                }
            ]
        },
    ]
    await _register(client, "prop-ga4-paged@example.com")
    workspace_id = await _workspace_id(db_session)
    _gsc, ga4 = await _seed(db_session, workspace_id=workspace_id)

    resp = await client.get(f"{_BASE}/{ga4.id}/properties")

    assert resp.status_code == 200
    assert [row["property_ref"] for row in resp.json()] == ["111", "222"]
    # The second request carried the token the first page returned.
    admin = [
        r
        for r in _fake_google.requests
        if r.url.host == "analyticsadmin.googleapis.com"
    ]
    assert len(admin) == 2
    assert admin[1].url.params["pageToken"] == "tok-2"


@pytest.mark.asyncio
async def test_provider_failure_is_502_not_an_empty_list(
    client: httpx.AsyncClient, db_session, _fake_google: _FakeGoogle
) -> None:
    """A broken upstream must never render as "you own no properties"."""
    _fake_google.status = 500
    await _register(client, "prop-boom@example.com")
    workspace_id = await _workspace_id(db_session)
    gsc, _ga4 = await _seed(db_session, workspace_id=workspace_id)

    resp = await client.get(f"{_BASE}/{gsc.id}/properties")

    assert resp.status_code == 502
    error = resp.json()["error"]
    assert error["code"] == "provider_api_error"
    # A 5xx from the provider is a transient blip — worth a client retry.
    assert error["retryable"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 403])
async def test_revoked_grant_is_reported_as_non_retryable(
    client: httpx.AsyncClient,
    db_session,
    _fake_google: _FakeGoogle,
    status_code: int,
) -> None:
    """A rejected grant is terminal until the user reconnects.

    The connector classifies 401/403 as ``grant_auth_failed`` + not
    retryable; the envelope must carry THAT rather than classifying by the
    502 status, or the client re-hammers a call that cannot start
    succeeding on its own.
    """
    _fake_google.status = status_code
    await _register(client, f"prop-revoked-{status_code}@example.com")
    workspace_id = await _workspace_id(db_session)
    gsc, _ga4 = await _seed(db_session, workspace_id=workspace_id)

    resp = await client.get(f"{_BASE}/{gsc.id}/properties")

    assert resp.status_code == 502
    error = resp.json()["error"]
    assert error["code"] == "grant_auth_failed"
    assert error["retryable"] is False


@pytest.mark.asyncio
async def test_near_expiry_grant_refreshes_before_listing(
    client: httpx.AsyncClient, db_session, _fake_google: _FakeGoogle
) -> None:
    """An access token inside the refresh skew is rotated, not failed on.

    Google access tokens live about an hour, so a grant connected earlier
    in the day reaches the picker expired. Without the request-path refresh
    the listing would fail ``grant_auth_failed`` on a perfectly healthy
    grant, and the user would be told to reconnect for nothing.
    """
    await _register(client, "prop-refresh@example.com")
    workspace_id = await _workspace_id(db_session)
    gsc, _ga4 = await _seed(db_session, workspace_id=workspace_id)
    grant = (await db_session.execute(select(IntegrationOAuthGrant))).scalar_one()
    grant.token_expires_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()

    resp = await client.get(f"{_BASE}/{gsc.id}/properties")

    assert resp.status_code == 200
    assert len(resp.json()) == 2
    # The rotation persisted: a fresh expiry and the refreshed access token
    # the fake token endpoint issued.
    await db_session.refresh(grant)
    assert grant.token_expires_at is not None
    assert grant.token_expires_at > datetime.now(UTC)
    assert decrypt_secret(grant.access_token_encrypted) == _REFRESHED_ACCESS
    # The listing rode the REFRESHED credential, not the stale one.
    listing = [r for r in _fake_google.requests if r.url.host == "www.googleapis.com"]
    assert listing[-1].headers["Authorization"] == f"Bearer {_REFRESHED_ACCESS}"


@pytest.mark.asyncio
async def test_unsupported_provider_is_422(
    client: httpx.AsyncClient, db_session, _fake_google: _FakeGoogle
) -> None:
    """Bing exposes no property listing — an explicit token, not [] or 500."""
    await _register(client, "prop-bing@example.com")
    workspace_id = await _workspace_id(db_session)
    (bing,) = await _seed(
        db_session,
        workspace_id=workspace_id,
        providers=("bing",),
        transport="microsoft_oauth",
    )

    resp = await client.get(f"{_BASE}/{bing.id}/properties")

    assert resp.status_code == 422
    assert resp.json()["detail"] == "property_discovery_unsupported"
    # Same canonical envelope as the endpoint's 502: one machine-usable
    # ``error.code`` for every failure of this route, not a generic
    # ``http_error`` for some of them.
    error = resp.json()["error"]
    assert error["code"] == "property_discovery_unsupported"
    assert error["retryable"] is False


@pytest.mark.asyncio
async def test_properties_are_workspace_scoped(
    client: httpx.AsyncClient, db_session, _fake_google: _FakeGoogle
) -> None:
    """A connection in another workspace is a 404, never a property list."""
    await _register(client, "prop-scope@example.com")
    other = Workspace(name="other-ws")
    db_session.add(other)
    await db_session.commit()
    (foreign,) = await _seed(db_session, workspace_id=other.id, providers=("gsc",))

    resp = await client.get(f"{_BASE}/{foreign.id}/properties")

    assert resp.status_code == 404
    # No provider call was made for a connection the caller cannot see.
    assert _fake_google.requests == []


@pytest.mark.asyncio
async def test_selecting_a_property_points_the_connection_at_it(
    client: httpx.AsyncClient, db_session, _fake_google: _FakeGoogle
) -> None:
    """Creating a mapping sets ``account_ref`` — the sync's fetch target.

    Regression guard for the gap that made connected Google grants sync
    nothing: mappings existed but nothing ever populated ``account_ref``, so
    the worker interpolated an EMPTY property into the provider URL
    (``/sites//searchAnalytics/query``) and the run died on the provider's
    400 as a generic ``provider_api_error``.
    """
    await _register(client, "prop-select@example.com")
    workspace_id = await _workspace_id(db_session)
    gsc, _ga4 = await _seed(db_session, workspace_id=workspace_id)
    project = await _seed_project(db_session, workspace_id=workspace_id)

    resp = await client.post(
        f"{_BASE}/{gsc.id}/mappings",
        json={
            "provider": "gsc",
            "property_ref": "sc-domain:example.com",
            "project_id": str(project.id),
        },
    )

    assert resp.status_code == 201
    assert resp.json()["property_ref"] == "sc-domain:example.com"
    await db_session.refresh(gsc)
    assert gsc.account_ref == "sc-domain:example.com"


@pytest.mark.asyncio
async def test_project_website_counts_as_owned_without_owned_domain_rows(
    client: httpx.AsyncClient, db_session, _fake_google: _FakeGoogle
) -> None:
    """A project's own site is selectable before discovery populates domains.

    Regression guard: ownership was read from ``OwnedDomain`` rows alone,
    which onboarding discovery fills in. A project created without them had
    an EMPTY ownership set, so every GSC property — including the site the
    project exists for — was rejected ``mapping_property_not_owned`` and no
    property could be selected at all.
    """
    await _register(client, "prop-website-owned@example.com")
    workspace_id = await _workspace_id(db_session)
    gsc, _ga4 = await _seed(db_session, workspace_id=workspace_id)
    project = Project(
        workspace_id=workspace_id, name="Example", website_url="https://example.com"
    )
    db_session.add(project)
    await db_session.commit()
    # No OwnedDomain rows are seeded — that is the point of this case.

    resp = await client.post(
        f"{_BASE}/{gsc.id}/mappings",
        json={
            "provider": "gsc",
            "property_ref": "sc-domain:example.com",
            "project_id": str(project.id),
        },
    )

    assert resp.status_code == 201
    await db_session.refresh(gsc)
    assert gsc.account_ref == "sc-domain:example.com"


@pytest.mark.asyncio
async def test_ga4_selection_stores_the_canonical_bare_id(
    client: httpx.AsyncClient, db_session, _fake_google: _FakeGoogle
) -> None:
    """A ``properties/``-prefixed ref canonicalizes onto account_ref too."""
    await _register(client, "prop-ga4-select@example.com")
    workspace_id = await _workspace_id(db_session)
    _gsc, ga4 = await _seed(db_session, workspace_id=workspace_id)
    project = await _seed_project(db_session, workspace_id=workspace_id)

    resp = await client.post(
        f"{_BASE}/{ga4.id}/mappings",
        json={
            "provider": "ga4",
            "property_ref": "properties/123456789",
            "project_id": str(project.id),
        },
    )

    assert resp.status_code == 201
    await db_session.refresh(ga4)
    assert ga4.account_ref == "123456789"
