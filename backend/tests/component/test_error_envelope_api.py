"""Component tests for the unified API error envelope (WS-A A1).

Exercises the live HTTP boundary: the four migrated routers (site_health,
opportunities, products, commerce) raise ``ApiException``; legacy raw
``HTTPException`` raises (unmigrated routers + Starlette routing errors) go
through the compatibility shim; request validation and unhandled exceptions
hit the two global handlers. Every non-2xx response carries the canonical
``{detail, error: {code, message, request_id, retryable, details?}}`` payload
while the legacy ``detail`` shape (string or coded dict) is preserved.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
from fastapi import FastAPI
from httpx import ASGITransport
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import app.api.opportunities as opportunity_routes
from app.core.config import settings
from app.core.telemetry import (
    generate_correlation_id,
    reset_correlation_id,
    set_correlation_id,
)
from app.domain.opportunities.service import (
    OpportunityGuidanceIdempotencyConflictError,
    OpportunityGuidanceUnavailableError,
)
from app.main import app
from app.models.site_health import SiteHealthProfile
from app.models.user import User
from app.models.workspace import WorkspaceMember
from tests.component.opportunity_helpers import _seed_scenario
from tests.component.site_health_helpers import seed_monitored_urls_allowance

pytestmark = pytest.mark.asyncio

_EMAIL = "envelope@example.com"


async def _register(client: httpx.AsyncClient, email: str = _EMAIL) -> None:
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


async def _project(client: httpx.AsyncClient, name: str = "Envelope Co") -> dict:
    resp = await client.post(
        "/api/v1/projects",
        json={
            "name": name,
            "brand_name": name,
            "competitors": [{"name": "Rival", "aliases": [], "domains": []}],
        },
    )
    assert resp.status_code == 201
    return resp.json()


def _assert_envelope(body: dict, *, code: str, retryable: bool) -> None:
    """The canonical block is present, coherent, and correlation-identified."""
    error = body["error"]
    assert error["code"] == code
    assert error["retryable"] is retryable
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["request_id"], str) and error["request_id"]
    # ``detail`` stays the legacy human payload; the block mirrors it.
    assert body["detail"] == error["message"] or isinstance(body["detail"], dict)


# =========================================================================
# Shim: Starlette routing errors + unmigrated legacy HTTPException routers
# =========================================================================
async def test_unknown_route_404_uses_envelope(client: httpx.AsyncClient) -> None:
    resp = await client.get(f"/api/v1/no-such-route/{uuid.uuid4()}")
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "Not Found"
    _assert_envelope(body, code="not_found", retryable=False)


async def test_legacy_http_exception_router_normalized_by_shim(
    client: httpx.AsyncClient,
) -> None:
    """Unmigrated routers (auth) keep working via the compatibility shim."""
    await _register(client)
    invalid = await client.post(
        "/api/v1/auth/login",
        json={"email": _EMAIL, "password": "wrong-password"},
    )
    assert invalid.status_code == 401
    body = invalid.json()
    assert isinstance(body["detail"], str)  # legacy string detail preserved
    _assert_envelope(body, code="unauthorized", retryable=False)
    assert body["error"]["message"] == body["detail"]


# =========================================================================
# products
# =========================================================================
async def test_products_404_and_409_envelopes(client: httpx.AsyncClient) -> None:
    await _register(client, "env-products@example.com")
    project = await _project(client, "Envelope Products")

    missing = await client.get(f"/api/v1/products/{uuid.uuid4()}")
    assert missing.status_code == 404
    body = missing.json()
    assert body["detail"] == "Product not found"
    _assert_envelope(body, code="not_found", retryable=False)

    payload = {"sku": "ENV-1", "name": "Envelope Widget"}
    created = await client.post(
        f"/api/v1/projects/{project['id']}/products", json=payload
    )
    assert created.status_code == 201
    dupe = await client.post(f"/api/v1/projects/{project['id']}/products", json=payload)
    assert dupe.status_code == 409
    dupe_body = dupe.json()
    assert isinstance(dupe_body["detail"], str)
    _assert_envelope(dupe_body, code="conflict", retryable=False)
    assert dupe_body["error"]["message"] == dupe_body["detail"]


async def test_products_import_422_sanitizes_pydantic_internals(
    client: httpx.AsyncClient,
) -> None:
    """COM-5: the import 422 never leaks model names / pydantic.dev URLs."""
    await _register(client, "env-import@example.com")
    project = await _project(client, "Envelope Imports")
    resp = await client.post(
        f"/api/v1/projects/{project['id']}/products/import",
        json={"products": [{"name": "Missing the required sku"}]},
    )
    assert resp.status_code == 422
    body = resp.json()
    _assert_envelope(body, code="validation_error", retryable=False)
    assert (
        body["detail"]
        == "Invalid product import payload: products.0.sku: Field required"
    )
    errors = body["error"]["details"]["errors"]
    assert errors == [
        {
            "loc": ["products", "0", "sku"],
            "message": "Field required",
            "type": "missing",
        }
    ]
    # No Pydantic internals anywhere in the serialized response.
    assert "ProductImport" not in resp.text
    assert "errors.pydantic.dev" not in resp.text
    assert "input_value" not in resp.text


async def test_request_validation_error_envelope(client: httpx.AsyncClient) -> None:
    """FastAPI's 422 array normalizes into sanitized field-level details."""
    await _register(client, "env-validation@example.com")
    resp = await client.get(
        f"/api/v1/products/{uuid.uuid4()}/visibility/evidence",
        params={"limit": 0},
    )
    assert resp.status_code == 422
    body = resp.json()
    # ``detail`` is now a human string, not the raw validation array.
    assert isinstance(body["detail"], str)
    assert "limit" in body["detail"]
    _assert_envelope(body, code="validation_error", retryable=False)
    errors = body["error"]["details"]["errors"]
    assert errors[0]["loc"] == ["limit"]  # the "query" prefix is stripped
    for entry in errors:
        assert set(entry) <= {"loc", "message", "type"}


# =========================================================================
# site_health
# =========================================================================
async def test_site_health_coded_422_envelope(client: httpx.AsyncClient) -> None:
    """Coded plan errors keep their legacy dict detail + canonical block."""
    await _register(client, "env-site@example.com")
    project = await _project(client, "Envelope Site")
    # A project without a website_url fails planning with a coded 422.
    resp = await client.post("/api/v1/site-crawls", json={"project_id": project["id"]})
    assert resp.status_code == 422
    body = resp.json()
    assert body["detail"]["code"] == "invalid_root"  # legacy dict preserved
    assert body["detail"]["message"] == body["error"]["message"]
    _assert_envelope(body, code="invalid_root", retryable=False)


async def test_site_health_stale_selection_version_409_envelope(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The 409 stale_selection_version shape survives the envelope (WS-A A1)."""
    email = "env-stale@example.com"
    await _register(client, email)
    project = await _project(client, "Envelope Stale")

    async with session_factory() as session:
        user = await session.scalar(select(User).where(User.email == email))
        assert user is not None
        member = await session.scalar(
            select(WorkspaceMember).where(WorkspaceMember.user_id == user.id)
        )
        assert member is not None
        # A positive monitored-URL allowance + a profile row so the version
        # check is reached.
        await seed_monitored_urls_allowance(
            session, workspace_id=member.workspace_id, monitored_urls=50
        )
        session.add(
            SiteHealthProfile(
                workspace_id=member.workspace_id, project_id=uuid.UUID(project["id"])
            )
        )
        await session.commit()

    resp = await client.put(
        f"/api/v1/projects/{project['id']}/monitored-urls",
        json={"site_url_ids": [], "expected_selection_version": 99},
    )
    assert resp.status_code == 409
    body = resp.json()
    # Legacy coded dict keeps its exact value and type...
    assert body["detail"]["code"] == "stale_selection_version"
    assert body["detail"]["current_selection_version"] == 0
    assert body["detail"]["message"] == body["error"]["message"]
    # ...and mirrored into the canonical block + details.
    _assert_envelope(body, code="stale_selection_version", retryable=False)
    assert body["error"]["details"] == {"current_selection_version": 0}


# =========================================================================
# opportunities
# =========================================================================
async def test_opportunities_404_envelope(client: httpx.AsyncClient) -> None:
    await _register(client, "env-opp@example.com")
    resp = await client.get(f"/api/v1/opportunities/{uuid.uuid4()}")
    assert resp.status_code == 404
    body = resp.json()
    assert body["detail"] == "Opportunity not found"
    _assert_envelope(body, code="not_found", retryable=False)


async def test_opportunities_superseded_409_envelope(
    client: httpx.AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Coded 409 opportunity_superseded keeps its exact legacy shape."""
    await _register(client)
    async with session_factory() as session:
        scn = await _seed_scenario(session, email=_EMAIL)
    headers = {"X-Workspace-Id": str(scn.workspace_id)}
    recompute = await client.post(
        f"/api/v1/projects/{scn.project_id}/opportunities/recompute",
        headers=headers,
    )
    assert recompute.status_code == 200
    listed = await client.get(
        f"/api/v1/projects/{scn.project_id}/opportunities?rule_id=thin_content",
        headers=headers,
    )
    item = listed.json()["items"][0]

    # A second recompute supersedes the first snapshot's rows.
    recompute = await client.post(
        f"/api/v1/projects/{scn.project_id}/opportunities/recompute",
        headers=headers,
    )
    assert recompute.status_code == 200
    conflict = await client.patch(
        f"/api/v1/opportunities/{item['id']}",
        headers=headers,
        json={"status": "resolved"},
    )
    assert conflict.status_code == 409
    body = conflict.json()
    assert body["detail"]["code"] == "opportunity_superseded"
    assert body["detail"]["message"] == body["error"]["message"]
    _assert_envelope(body, code="opportunity_superseded", retryable=False)


async def test_opportunity_guidance_error_envelopes(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    await _register(client, "env-guidance@example.com")
    opportunity_id = uuid.uuid4()

    async def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OpportunityGuidanceUnavailableError("Guidance is unavailable")

    monkeypatch.setattr(opportunity_routes.service, "create_guidance", unavailable)
    unavailable_response = await client.post(
        f"/api/v1/opportunities/{opportunity_id}/guidance"
    )
    assert unavailable_response.status_code == 403
    _assert_envelope(
        unavailable_response.json(),
        code="opportunity_guidance_unavailable",
        retryable=False,
    )

    async def conflict(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OpportunityGuidanceIdempotencyConflictError("Key was already used")

    monkeypatch.setattr(opportunity_routes.service, "create_guidance", conflict)
    conflict_response = await client.post(
        f"/api/v1/opportunities/{opportunity_id}/guidance"
    )
    assert conflict_response.status_code == 409
    _assert_envelope(
        conflict_response.json(),
        code="opportunity_guidance_idempotency_conflict",
        retryable=False,
    )


# =========================================================================
# commerce
# =========================================================================
async def test_commerce_attribution_422_envelope(client: httpx.AsyncClient) -> None:
    await _register(client, "env-commerce@example.com")
    project = await _project(client, "Envelope Commerce")
    resp = await client.get(
        f"/api/v1/projects/{project['id']}/commerce/attribution",
        params={"granularity": "hour"},
    )
    assert resp.status_code == 422
    body = resp.json()
    assert isinstance(body["detail"], str)
    _assert_envelope(body, code="validation_error", retryable=False)
    assert body["error"]["message"] == body["detail"]


# =========================================================================
# Global handler: unhandled exceptions become a sanitized 500 envelope
# =========================================================================
async def test_unhandled_exception_returns_internal_error_envelope() -> None:
    marker = "boom-internal-marker"

    async def _boom() -> None:
        raise RuntimeError(marker)

    # A LOCAL app carrying the shared app's registered handlers, rather than
    # adding a throwaway route to the shared router and stripping it in a
    # `finally`: that mutation is visible to every other test while it is in
    # place, and a crash between the add and the cleanup leaks the route for
    # the rest of the session.
    test_app = FastAPI()
    test_app.add_api_route(
        "/__test-unhandled-envelope", _boom, methods=["GET"], include_in_schema=False
    )
    for exc_class_or_status, handler in app.exception_handlers.items():
        test_app.add_exception_handler(exc_class_or_status, handler)

    # The shared app's correlation middleware is a closure inside
    # ``create_app`` (not importable), so mint the id the same way here — the
    # handler reads ``request.state.correlation_id``, and the A6 support path
    # this test asserts depends on that id being present.
    @test_app.middleware("http")
    async def _correlation(request, call_next):
        correlation_id = generate_correlation_id()
        request.state.correlation_id = correlation_id
        token = set_correlation_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)
        response.headers[settings.request_id_header] = correlation_id
        return response

    # ServerErrorMiddleware re-raises after responding; don't re-raise here.
    transport = ASGITransport(app=test_app, raise_app_exceptions=False)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as raw_client:
        resp = await raw_client.get("/__test-unhandled-envelope")

    assert resp.status_code == 500
    body = resp.json()
    _assert_envelope(body, code="internal_error", retryable=True)
    assert body["error"]["message"] == "An unexpected error occurred"
    # No stack trace / internals in the body.
    assert marker not in resp.text
    assert "RuntimeError" not in resp.text
    assert "Traceback" not in resp.text
    # The request id correlates with backend logs (A6 support path).
    assert resp.headers[settings.request_id_header] == body["error"]["request_id"]
