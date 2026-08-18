"""Shared policy for first-party authentication and OAuth cookies."""

from __future__ import annotations

from fastapi import Response

from app.core.config import settings
from app.core.config.integrations_transport import (
    INTEGRATION_OAUTH_TRANSACTION_COOKIE,
    INTEGRATION_OAUTH_TRANSACTION_COOKIE_PATH,
)
from app.core.config.oauth import oauth_settings

_INSECURE_ENVS = {"", "development", "dev", "local", "test", "testing"}


def browser_cookie_secure() -> bool:
    return str(settings.app_env or "").strip().lower() not in _INSECURE_ENVS


def set_integration_oauth_cookie(response: Response, nonce: str) -> None:
    response.set_cookie(
        INTEGRATION_OAUTH_TRANSACTION_COOKIE,
        nonce,
        httponly=True,
        samesite="lax",
        secure=browser_cookie_secure(),
        path=INTEGRATION_OAUTH_TRANSACTION_COOKIE_PATH,
        max_age=oauth_settings.state_ttl_seconds,
    )


def clear_integration_oauth_cookie(response: Response) -> None:
    response.delete_cookie(
        INTEGRATION_OAUTH_TRANSACTION_COOKIE,
        path=INTEGRATION_OAUTH_TRANSACTION_COOKIE_PATH,
        httponly=True,
        samesite="lax",
        secure=browser_cookie_secure(),
    )
