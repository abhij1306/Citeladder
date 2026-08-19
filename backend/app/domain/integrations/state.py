"""OAuth connect-callback state verification and one-time consumption.

Implements the state-nonce half of docs/roadmap/integrations.md §2: the
state JWT is verified for signature/expiry/transaction-cookie binding, then
the persisted ``IntegrationOAuthState`` row is consumed ATOMICALLY
(``UPDATE ... SET consumed_at ... WHERE consumed_at IS NULL``) BEFORE any
code exchange — a replayed, cross-user, or cross-workspace state is
rejected before any token moves. Shopify additionally requires the
callback HMAC and an exact three-way shop match (signed claim, persisted
value, callback ``shop`` param) before the code exchange.

Split out of ``service.py`` purely for module size; ``complete_connect``
there is still the sole caller and orchestrates these in order.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from datetime import UTC, datetime

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.integrations import oauth as integration_oauth
from app.core.config.integrations_transport import (
    INTEGRATION_PROVIDER_TRANSPORT,
    INTEGRATION_TRANSPORT_SHOPIFY,
)
from app.core.security import TokenDecodeError, decode_oauth_state
from app.domain.integrations.errors import (
    IntegrationNotConfiguredError,
    IntegrationStateError,
)
from app.domain.workspaces.service import get_membership
from app.models.integrations import IntegrationOAuthState
from app.models.user import User


def _utcnow() -> datetime:
    return datetime.now(UTC)


def verify_state_claims(
    state: str, provider: str, session_nonce: str
) -> dict[str, str | int]:
    """Verify signature, expiry, provider, and transaction-cookie binding."""
    if not session_nonce:
        raise IntegrationStateError("OAuth transaction cookie is missing")
    try:
        claims = decode_oauth_state(state, provider, session_nonce=session_nonce)
    except TokenDecodeError as exc:
        raise IntegrationStateError("Invalid OAuth state") from exc
    jti = str(claims.get("jti") or "")
    workspace_id = str(claims.get("workspace_id") or "")
    user_id = str(claims.get("user_id") or "")
    if not jti or not workspace_id or not user_id:
        # A state minted without the integrations binding claims (e.g. the
        # auth sign-in scaffold) must never drive a connect callback.
        raise IntegrationStateError("OAuth state is missing its binding claims")
    return claims


async def consume_state(
    session: AsyncSession,
    *,
    claims: dict[str, str | int],
    provider: str,
) -> tuple[uuid.UUID, str]:
    """Atomically consume the persisted state row.

    Returns ``(workspace_id, provider_account_ref)`` — the latter is the
    persisted per-account OAuth target ("" for single-tenant transports).
    The single ``UPDATE ... WHERE consumed_at IS NULL`` is the one-time
    consumption gate: exactly one concurrent callback can win it. Binding
    mismatches found after consumption are terminal (the state stays
    consumed).
    """
    now = _utcnow()
    result = await session.execute(
        update(IntegrationOAuthState)
        .where(
            IntegrationOAuthState.jti == str(claims["jti"]),
            IntegrationOAuthState.consumed_at.is_(None),
        )
        .values(consumed_at=now)
        .returning(
            IntegrationOAuthState.workspace_id,
            IntegrationOAuthState.user_id,
            IntegrationOAuthState.provider,
            IntegrationOAuthState.provider_account_ref,
            IntegrationOAuthState.expires_at,
        )
    )
    row = result.one_or_none()
    if row is None:
        # Unknown jti or already consumed (replay) — rejected either way.
        raise IntegrationStateError("OAuth state was already consumed or is unknown")
    if (
        row.provider != provider
        or str(row.user_id) != str(claims["user_id"])
        or str(row.workspace_id) != str(claims["workspace_id"])
    ):
        raise IntegrationStateError("OAuth state binding mismatch")
    if row.expires_at <= now:
        raise IntegrationStateError("OAuth state expired")
    user = await session.get(User, row.user_id)
    if user is None or not user.is_active:
        raise IntegrationStateError("OAuth state user is inactive")
    if await get_membership(session, row.workspace_id, row.user_id) is None:
        raise IntegrationStateError("OAuth state workspace membership lost")
    return row.workspace_id, str(row.provider_account_ref or "")


def prepare_connect_callback(
    *,
    provider: str,
    state: str,
    session_nonce: str,
    callback_params: Mapping[str, str] | None,
) -> tuple[str, dict[str, str | int], str]:
    transport = INTEGRATION_PROVIDER_TRANSPORT[provider]
    claims = verify_state_claims(state, provider, session_nonce)
    if not integration_oauth.oauth_client_configured(transport):
        raise IntegrationNotConfiguredError(provider)
    signed_account_ref = str(claims.get("provider_account_ref") or "")
    if transport == INTEGRATION_TRANSPORT_SHOPIFY:
        hmac_valid = callback_params is not None and (
            integration_oauth.verify_shopify_callback_hmac(callback_params)
        )
        if not hmac_valid:
            raise IntegrationStateError("Invalid Shopify callback signature")
    return transport, claims, signed_account_ref


def validate_shopify_state_match(
    *,
    signed_account_ref: str,
    persisted_account_ref: str,
    callback_params: Mapping[str, str] | None,
) -> None:
    callback_shop = str((callback_params or {}).get("shop") or "")
    if (
        not signed_account_ref
        or signed_account_ref != persisted_account_ref
        or signed_account_ref != callback_shop
    ):
        raise IntegrationStateError("OAuth state shop mismatch")
