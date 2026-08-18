"""Grant access-token resolution for the REQUEST path (spec §2).

A stored Google access token lives about an hour, so any interactive call
that touches a provider — the connection test, the property picker — must
be able to refresh before it reaches the API, or a grant connected
yesterday fails with ``grant_auth_failed`` even though it is perfectly
healthy.

Relationship to the sync worker: ``IntegrationWorker._fresh_access_token``
implements the same near-expiry protocol for the BACKGROUND path. The two
are deliberately separate rather than one shared function because their
concurrency contracts differ — the worker owns its own session factory and
holds the grant row lock across the exchange to serialize refreshes between
worker PROCESSES sharing one grant, whereas this helper runs inside a
request's existing session and unit of work. The near-expiry rule itself
(``token_refresh_skew_seconds`` + ``INTEGRATION_OAUTH_REFRESHABLE``) is
config-owned and read by both (invariant 1), so the policy has one owner
even though the transaction mechanics do not.

Tokens are decrypted here and returned to the immediate caller only; they
never enter a DTO, a log line, or an event payload (invariant 6).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.integrations import oauth as integration_oauth
from app.core.config.integrations_contracts import (
    ERROR_GRANT_AUTH_FAILED,
)
from app.core.config.integrations_settings import (
    integration_settings,
)
from app.core.config.integrations_transport import (
    INTEGRATION_OAUTH_REFRESHABLE,
)
from app.core.security import decrypt_secret, encrypt_secret
from app.models.integrations import IntegrationOAuthGrant


async def fresh_access_token(
    session: AsyncSession,
    *,
    grant: IntegrationOAuthGrant,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str:
    """Return a usable access token, refreshing it when near expiry.

    The grant row is re-read ``FOR UPDATE`` and the expiry re-checked
    inside that lock, so two concurrent requests on one grant perform at
    most one remote refresh. A NON-refreshable transport (Shopify's
    offline Admin API token — it never expires and carries no refresh
    token) returns the stored token directly; a ``None`` expiry is not
    near-expiry for those.

    Raises ``IntegrationOAuthError`` when the grant cannot yield a usable
    token (missing row, no refresh token, or a failed exchange) — callers
    map that to their own surface rather than falling back to a stale one.
    """
    refreshable = INTEGRATION_OAUTH_REFRESHABLE.get(grant.transport, True)
    if not refreshable:
        return decrypt_secret(grant.access_token_encrypted)

    # Re-read under a row lock so the expiry check and the rotation are
    # atomic against a concurrent request on the same grant.
    locked = await session.get(IntegrationOAuthGrant, grant.id, with_for_update=True)
    if locked is None:
        raise integration_oauth.IntegrationOAuthError(
            "grant row is missing",
            error_code=ERROR_GRANT_AUTH_FAILED,
        )
    now = datetime.now(UTC)
    skew = timedelta(seconds=integration_settings.token_refresh_skew_seconds)
    if locked.token_expires_at is not None and locked.token_expires_at > now + skew:
        return decrypt_secret(locked.access_token_encrypted)
    if not locked.refresh_token_encrypted:
        raise integration_oauth.IntegrationOAuthError(
            "grant has no refresh token",
            error_code=ERROR_GRANT_AUTH_FAILED,
        )
    refresh_token = decrypt_secret(locked.refresh_token_encrypted)
    client = integration_oauth.build_oauth_client(locked.transport, transport=transport)
    try:
        bundle = await client.refresh(refresh_token=refresh_token)
    except BaseException:
        # Never hold the grant row lock across a failed exchange — the
        # request would propagate the error with the row still locked and
        # the transaction open, blocking every other caller on this grant.
        await session.rollback()
        raise
    _store_rotated_bundle(locked, bundle, now=now)
    await session.commit()
    return bundle.access_token


def _store_rotated_bundle(
    grant: IntegrationOAuthGrant,
    bundle: integration_oauth.OAuthTokenBundle,
    *,
    now: datetime,
) -> None:
    """Persist a refreshed bundle onto the locked grant (encrypted).

    Each field is written only when the provider actually returned it: a
    refresh response may omit the refresh token (the existing one stays
    valid) and the scope list (the grant keeps its recorded scopes), so
    overwriting unconditionally would erase working credentials.
    """
    grant.access_token_encrypted = encrypt_secret(bundle.access_token)
    if bundle.refresh_token:
        grant.refresh_token_encrypted = encrypt_secret(bundle.refresh_token)
    grant.token_expires_at = (
        now + timedelta(seconds=bundle.expires_in)
        if bundle.expires_in is not None
        else None
    )
    if bundle.granted_scopes:
        grant.granted_scopes = list(bundle.granted_scopes)
