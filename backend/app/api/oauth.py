# OAuth router: provider catalog listing + authorize-URL scaffold.
#
# Scaffold only — no real provider credentials exist yet, so every provider
# ships disabled/unconfigured (flags in ``app.core.config.oauth``). The start
# endpoint is fully wired behind those flags; the callback is a deliberate
# 501 stub. Client secrets are never returned or logged (invariant 6).
from __future__ import annotations

from urllib.parse import urlencode

from fastapi import APIRouter, status

from app.core.config.oauth import (
    CODE_OAUTH_CALLBACK_NOT_IMPLEMENTED,
    CODE_OAUTH_PROVIDER_NOT_CONFIGURED,
    CODE_OAUTH_PROVIDER_UNKNOWN,
    OAUTH_AUTHORIZE_URLS,
    OAUTH_PROVIDER_LABELS,
    OAUTH_SCOPES,
    is_oauth_provider,
    oauth_provider_configured,
    oauth_settings,
)
from app.core.http_errors import raise_api_error
from app.core.security import create_oauth_state
from app.domain.auth.schemas import (
    OAuthProviderInfo,
    OAuthProvidersResponse,
    OAuthStartResponse,
)

router = APIRouter(prefix="/auth/oauth", tags=["auth"])


def _require_known_provider(provider: str) -> None:
    """404 when ``provider`` is not in the OAuth catalog."""
    if not is_oauth_provider(provider):
        raise_api_error(
            status.HTTP_404_NOT_FOUND,
            f"Unknown OAuth provider {provider!r}",
            code=CODE_OAUTH_PROVIDER_UNKNOWN,
            details={"provider": provider},
            # ``detail`` stays the exact coded dict this endpoint has always
            # returned: no ``message`` key, which its clients do not expect.
            detail={"code": CODE_OAUTH_PROVIDER_UNKNOWN, "provider": provider},
        )


def _require_configured_provider(provider: str) -> None:
    """503 when ``provider`` is known but not enabled + credentialed."""
    if not oauth_provider_configured(provider):
        raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"OAuth provider {provider!r} is not configured",
            code=CODE_OAUTH_PROVIDER_NOT_CONFIGURED,
            details={"provider": provider},
            detail={"code": CODE_OAUTH_PROVIDER_NOT_CONFIGURED, "provider": provider},
        )


@router.get("/providers", response_model=OAuthProvidersResponse)
async def list_oauth_providers() -> OAuthProvidersResponse:
    """List the OAuth provider catalog — ``configured`` flags only.

    Never exposes client ids, client secrets, or redirect URIs (invariant 6).
    """
    return OAuthProvidersResponse(
        providers=[
            OAuthProviderInfo(
                provider=provider,
                label=label,
                configured=oauth_provider_configured(provider),
            )
            for provider, label in OAUTH_PROVIDER_LABELS.items()
        ]
    )


@router.get("/{provider}/start", response_model=OAuthStartResponse)
async def oauth_start(provider: str) -> OAuthStartResponse:
    """Build the provider authorize URL with a signed, stateless state token."""
    _require_known_provider(provider)
    _require_configured_provider(provider)
    state, session_nonce = create_oauth_state(provider)
    query = urlencode(
        {
            "client_id": getattr(oauth_settings, f"{provider}_client_id"),
            "redirect_uri": getattr(oauth_settings, f"{provider}_redirect_uri"),
            "response_type": "code",
            "scope": OAUTH_SCOPES[provider],
            "state": state,
        }
    )
    authorize_url = f"{OAUTH_AUTHORIZE_URLS[provider]}?{query}"
    return OAuthStartResponse(
        authorize_url=authorize_url,
        state=state,
        session_nonce=session_nonce,
    )


@router.get("/{provider}/callback")
@router.post("/{provider}/callback")
async def oauth_callback(provider: str) -> None:
    """Deliberate 501 stub for the OAuth callback.

    The token exchange + user link lands when real provider credentials
    exist; session issuance will then reuse ``_set_session_cookie`` from
    ``app.api.auth`` (intentionally not imported yet).
    """
    _require_known_provider(provider)
    _require_configured_provider(provider)
    raise_api_error(
        status.HTTP_501_NOT_IMPLEMENTED,
        f"The OAuth callback for {provider!r} is not implemented",
        code=CODE_OAUTH_CALLBACK_NOT_IMPLEMENTED,
        details={"provider": provider},
        detail={"code": CODE_OAUTH_CALLBACK_NOT_IMPLEMENTED, "provider": provider},
    )
