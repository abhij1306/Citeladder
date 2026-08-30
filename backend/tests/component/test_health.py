"""Component test: the app imports cleanly and /health returns 200."""

from __future__ import annotations

import httpx
import pytest
from fastapi.middleware.cors import CORSMiddleware
from httpx import ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import main
from app.main import app


@pytest.mark.asyncio
async def test_health_returns_200() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_returns_200_when_the_database_answers(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Readiness is a real dependency check, not a second liveness route."""
    monkeypatch.setattr(main, "SessionLocal", session_factory)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready"}


@pytest.mark.asyncio
async def test_ready_returns_503_when_the_database_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A dead database must take the instance out of rotation.

    This is the gap ``/health`` alone left: the process is up and answering
    HTTP, so liveness stays 200 while nothing it needs is reachable.
    """

    class _DeadSession:
        async def __aenter__(self):
            raise OSError("connection refused")

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(main, "SessionLocal", lambda: _DeadSession())

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        ready = await client.get("/ready")
        alive = await client.get("/health")

    assert ready.status_code == 503
    assert ready.json() == {"status": "unavailable", "database": "down"}
    # Liveness deliberately still passes — restarting this process fixes
    # nothing when the database is what is down.
    assert alive.status_code == 200
    assert alive.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_health_echoes_request_id_header() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.get("/health", headers={"X-Request-ID": "abc123"})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "abc123"


@pytest.mark.asyncio
async def test_cors_is_outermost_and_handles_preflight_before_api_middleware() -> None:
    assert app.user_middleware[0].cls is CORSMiddleware

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.options(
            "/api/v1/provider-catalog",
            headers={
                "Origin": "http://127.0.0.1:3000",
                "Access-Control-Request-Method": "GET",
            },
        )
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"


@pytest.mark.asyncio
async def test_api_responses_and_errors_are_authoritatively_no_store() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        public_response = await client.get("/api/v1/provider-catalog")
        error_response = await client.get("/api/v1/workspaces")
    for response in (public_response, error_response):
        assert response.headers["cache-control"] == "private, no-store, max-age=0"
        assert response.headers["pragma"] == "no-cache"


@pytest.mark.asyncio
async def test_declared_oversized_api_body_is_rejected_before_parsing() -> None:
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/auth/login",
            content=b"{}",
            headers={"Content-Length": str(3 * 1024 * 1024)},
        )
    assert response.status_code == 413
    assert response.headers["cache-control"] == "private, no-store, max-age=0"


@pytest.mark.asyncio
async def test_chunked_oversized_api_body_is_stopped_while_streaming() -> None:
    async def chunks():
        for _ in range(33):
            yield b"x" * (64 * 1024)

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as client:
        response = await client.post(
            "/api/v1/auth/login",
            content=chunks(),
            headers={"Content-Type": "application/json"},
        )
    assert response.status_code == 413


def test_health_route_and_router_stubs_registered() -> None:
    # /health is registered, and all mounted routers are included so B2-B6
    # fill them in place. B4 adds the provider-catalog router alongside the six
    # original stubs (7); B6 adds the executions router (8); the Site Health
    # router adds the ninth (9); the Content router adds the tenth (10); the
    # brand-discoveries router adds the eleventh (11); the OAuth router adds
    # the twelfth (12); the integrations router adds the thirteenth (13); the
    # AI Referrals router adds the fourteenth (14); the Traffic router adds
    # the fifteenth (15); Opportunities adds the sixteenth; Billing adds the
    # seventeenth and Commerce adds the eighteenth; audit schedules add the
    # nineteenth. Growth Agent brings the mounted-router set to twenty-one.
    from app.main import _ROUTERS

    paths = {getattr(route, "path", None) for route in app.routes}
    assert "/health" in paths
    assert "/ready" in paths
    assert len(_ROUTERS) == 21
