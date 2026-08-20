# Auth router: register / login / logout / me.
#
# The JWT session is delivered in a **secure HttpOnly cookie** so browser JS
# can never read it. Cookie policy (documented choice):
#   - HttpOnly: yes — the token is inaccessible to JS (XSS hardening).
#   - SameSite=Lax: the browser reaches the backend same-origin via the
#     Next.js rewrites() proxy (gotcha 2), so the cookie is first-party and
#     Lax is sufficient; no cross-site POST flow needs None.
#   - Secure: enabled outside local dev so the cookie only rides HTTPS. Local
#     http dev keeps it off so the cookie is usable without TLS.
#   - Path=/: sent to the whole same-origin API surface.
from __future__ import annotations

import ipaddress
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.browser_cookies import (
    browser_cookie_secure,
    clear_integration_oauth_cookie,
)
from app.api.deps import get_current_user, get_db
from app.core.config import settings, trusted_proxy_networks
from app.core.config.abuse import abuse_settings
from app.core.http_errors import raise_api_error
from app.domain.abuse.service import UsageLimitExceededError, enforce_and_commit
from app.domain.auth.schemas import (
    AuthResponse,
    Credentials,
    RegistrationResponse,
    SessionUser,
)
from app.domain.auth.service import authenticate_user, register_user
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])
logger = logging.getLogger("app.auth")


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        settings.session_cookie_name,
        token,
        httponly=True,
        samesite="lax",
        secure=browser_cookie_secure(),
        path="/",
        max_age=int(settings.jwt_expire_hours * 3600),
    )


async def _enforce_limit(
    session: AsyncSession,
    *,
    subject_kind: str,
    subject: str,
    operation: str,
    limit: int,
    window: int,
) -> None:
    try:
        await enforce_and_commit(
            session,
            subject_kind=subject_kind,
            subject=subject,
            operation=operation,
            limit=limit,
            window_seconds=window,
        )
    except UsageLimitExceededError as exc:
        raise_api_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many requests",
            headers={"Retry-After": str(exc.retry_after_seconds)},
            cause=exc,
        )


def _trusted_client_identity(request: Request) -> str:
    """Recover the first untrusted hop only when the direct peer is trusted."""
    peer = request.client.host if request.client is not None else "unavailable"
    try:
        peer_ip = ipaddress.ip_address(peer)
        trusted = trusted_proxy_networks(settings.trusted_proxy_cidrs)
    except ValueError:
        return peer
    if not trusted or not any(peer_ip in network for network in trusted):
        return peer

    forwarded = request.headers.get("x-forwarded-for")
    if not forwarded:
        return peer
    for value in reversed(forwarded.split(",")):
        try:
            candidate = ipaddress.ip_address(value.strip())
        except ValueError:
            return peer
        if not any(candidate in network for network in trusted):
            return candidate.compressed
    return peer


@router.post(
    "/register",
    response_model=RegistrationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def register(
    payload: Credentials,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> RegistrationResponse:
    await _enforce_limit(
        session,
        subject_kind="client",
        subject=_trusted_client_identity(request),
        operation="auth.register.client",
        limit=abuse_settings.register_client_limit,
        window=abuse_settings.register_window_seconds,
    )
    await register_user(session, payload.email, payload.password)
    return RegistrationResponse(
        message="If the address is eligible, the account is ready. Sign in to continue."
    )


@router.post("/login", response_model=AuthResponse)
async def login(
    payload: Credentials,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_db)],
) -> AuthResponse:
    await _enforce_limit(
        session,
        subject_kind="client",
        subject=_trusted_client_identity(request),
        operation="auth.login.client",
        limit=abuse_settings.login_client_limit,
        window=abuse_settings.login_window_seconds,
    )
    authenticated = await authenticate_user(session, payload.email, payload.password)
    if authenticated is None:
        # Account/email counters are failure-only. Successful credentials must
        # not be blocked because an attacker deliberately exhausted a victim's
        # identifier budget.
        await _enforce_limit(
            session,
            subject_kind="email",
            subject=payload.email,
            operation="auth.login.email_failure",
            limit=abuse_settings.login_email_limit,
            window=abuse_settings.login_window_seconds,
        )
        raise_api_error(status.HTTP_401_UNAUTHORIZED, "Invalid credentials")
    token, user = authenticated
    clear_integration_oauth_cookie(response)
    _set_session_cookie(response, token)
    logger.info("auth.login_success", extra={"user_id": str(user.id)})
    return AuthResponse(user=SessionUser.model_validate(user))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    response: Response,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    user.session_version += 1
    await session.commit()
    response.delete_cookie(settings.session_cookie_name, path="/")
    clear_integration_oauth_cookie(response)
    response.status_code = status.HTTP_204_NO_CONTENT
    return response


@router.get("/me", response_model=AuthResponse)
async def me(user: Annotated[User, Depends(get_current_user)]) -> AuthResponse:
    return AuthResponse(user=SessionUser.model_validate(user))
