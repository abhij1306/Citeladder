# FastAPI application factory, middleware, lifespan, and router registration.
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.agent import router as agent_router
from app.api.analytics import router as analytics_router
from app.api.audit_schedules import router as audit_schedules_router
from app.api.audits import router as audits_router
from app.api.auth import router as auth_router
from app.api.billing import router as billing_router
from app.api.brand_discoveries import router as brand_discoveries_router
from app.api.commerce import router as commerce_router
from app.api.content import router as content_router
from app.api.demand import router as demand_router
from app.api.executions import router as executions_router
from app.api.integrations import router as integrations_router
from app.api.oauth import router as oauth_router
from app.api.opportunities import router as opportunities_router
from app.api.products import router as products_router
from app.api.projects import router as projects_router
from app.api.prompts import router as prompts_router
from app.api.provider_connections import (
    catalog_router as provider_catalog_router,
)
from app.api.provider_connections import router as provider_connections_router
from app.api.site_health import router as site_health_router
from app.api.traffic import router as traffic_router
from app.api.workspaces import router as workspaces_router
from app.connectors.answer_engines.http_client import aclose_shared_clients
from app.connectors.billing.http_client import aclose_shared_billing_clients
from app.core.config import get_frontend_origins, settings
from app.core.config.api import API_V1_PREFIX
from app.core.database import dispose_engine
from app.core.errors import (
    ApiException,
    api_exception_handler,
    http_exception_shim_handler,
    request_validation_error_handler,
    unhandled_exception_handler,
)
from app.core.http_security import ApiNoStoreMiddleware, RequestBodyLimitMiddleware
from app.core.telemetry import (
    configure_logging,
    generate_correlation_id,
    instrument_fastapi,
    reset_correlation_id,
    set_correlation_id,
)

logger = logging.getLogger("app")


def _sanitize_correlation_id(value: str) -> str:
    """Reject a client-supplied correlation id that is unsafe to echo back.

    The id is reflected into a response header, so any control character
    (notably CR/LF) could split the response (header injection). Accept only a
    bounded run of unreserved token characters; anything else is treated as
    absent so a fresh server-generated id is used instead.
    """
    candidate = value.strip()
    if 0 < len(candidate) <= 128 and all(c.isalnum() or c in "-_." for c in candidate):
        return candidate
    return ""


# Explicit router stubs registered now so B2–B6 fill them in place. Each router
# owns its own paths; the prefix keeps the whole surface under /api/v1.
_ROUTERS = (
    auth_router,
    agent_router,
    billing_router,
    oauth_router,
    workspaces_router,
    projects_router,
    brand_discoveries_router,
    prompts_router,
    products_router,
    provider_connections_router,
    provider_catalog_router,
    audits_router,
    audit_schedules_router,
    executions_router,
    site_health_router,
    content_router,
    demand_router,
    integrations_router,
    analytics_router,
    traffic_router,
    opportunities_router,
    commerce_router,
)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    configure_logging()
    logger.info("citeladder backend starting", extra={"app_env": settings.app_env})
    try:
        yield
    finally:
        # The provider connectivity probe (/provider-connections/{id}/test) runs
        # in this process, so the web app owns a pooled answer-engine client too.
        await aclose_shared_clients()
        await aclose_shared_billing_clients()
        await dispose_engine()


def create_app() -> FastAPI:
    """Application factory: build and configure the FastAPI app."""
    configure_logging()
    app = FastAPI(title=settings.app_name, lifespan=lifespan)

    # Unified error envelope (WS-A A1): one canonical payload for every
    # non-2xx response — migrated ApiException routers, legacy HTTPException
    # raises (compat shim, incl. Starlette routing 404/405), request
    # validation failures, and unhandled 500s alike.
    # ``add_exception_handler`` types its handler as taking the BASE
    # ``Exception``, so a handler narrowed to the type it is registered for is
    # rejected even though Starlette only ever dispatches that type to it. The
    # ignores are on the registration (Starlette's typing gap), keeping the
    # handlers themselves precisely typed — see errors.py.
    app.add_exception_handler(ApiException, api_exception_handler)  # type: ignore[arg-type]
    app.add_exception_handler(
        StarletteHTTPException,
        http_exception_shim_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(
        RequestValidationError,
        request_validation_error_handler,  # type: ignore[arg-type]
    )
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # Applied at ASGI level so limits cover multipart parsing and cache headers
    # cover JSON, downloads, validation errors, and unhandled API errors alike.
    app.add_middleware(RequestBodyLimitMiddleware)
    app.add_middleware(ApiNoStoreMiddleware)

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next) -> Response:
        header_name = settings.request_id_header
        supplied = request.headers.get(header_name) or ""
        correlation_id = _sanitize_correlation_id(supplied) or generate_correlation_id()
        request.state.correlation_id = correlation_id
        token = set_correlation_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)
        response.headers[header_name] = correlation_id
        return response

    # Add CORS last: Starlette wraps middleware in reverse registration order,
    # so preflight requests bypass the body-limit and response-cache layers.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_frontend_origins(),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    for router in _ROUTERS:
        app.include_router(router, prefix=API_V1_PREFIX)

    instrument_fastapi(app)
    return app


app = create_app()
