"""Serialized, provider-safe access-token resolution for integration runs."""

from __future__ import annotations

from datetime import timedelta

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.connectors.integrations import oauth as integration_oauth
from app.core.config.integrations_contracts import ERROR_GRANT_AUTH_FAILED
from app.core.config.integrations_settings import integration_settings
from app.core.config.integrations_transport import INTEGRATION_OAUTH_REFRESHABLE
from app.core.security import decrypt_secret, encrypt_secret
from app.models.integrations import IntegrationOAuthGrant
from app.workers.integration.paging import RunContext


async def fresh_access_token(
    ctx: RunContext,
    *,
    session_factory: async_sessionmaker[AsyncSession],
    transport: httpx.AsyncBaseTransport | None,
    now,
) -> str:
    """Read or serialize one grant refresh before provider data I/O.

    The queue lease has already been committed. Refresh holds the grant row
    lock deliberately so concurrent runs sharing a grant make one exchange,
    then commits before any subsequent provider data request.
    """
    refreshable = INTEGRATION_OAUTH_REFRESHABLE.get(ctx.transport, True)
    async with session_factory() as session:
        grant = await session.get(
            IntegrationOAuthGrant, ctx.grant_id, with_for_update=True
        )
        if grant is None:
            await session.commit()
            raise integration_oauth.IntegrationOAuthError(
                "grant row is missing", error_code=ERROR_GRANT_AUTH_FAILED
            )
        if not refreshable:
            access_token = decrypt_secret(grant.access_token_encrypted)
            await session.commit()
            return access_token
        current_time = now()
        skew = timedelta(seconds=integration_settings.token_refresh_skew_seconds)
        near_expiry = (
            grant.token_expires_at is None
            or grant.token_expires_at <= current_time + skew
        )
        if not near_expiry:
            access_token = decrypt_secret(grant.access_token_encrypted)
            await session.commit()
            return access_token
        if not grant.refresh_token_encrypted:
            await session.commit()
            raise integration_oauth.IntegrationOAuthError(
                "grant has no refresh token", error_code=ERROR_GRANT_AUTH_FAILED
            )
        refresh_token = decrypt_secret(grant.refresh_token_encrypted)
        client = integration_oauth.build_oauth_client(
            ctx.transport, transport=transport
        )
        try:
            bundle = await client.refresh(refresh_token=refresh_token)
        except BaseException:
            await session.rollback()
            raise
        grant.access_token_encrypted = encrypt_secret(bundle.access_token)
        if bundle.refresh_token:
            grant.refresh_token_encrypted = encrypt_secret(bundle.refresh_token)
        grant.token_expires_at = (
            current_time + timedelta(seconds=bundle.expires_in)
            if bundle.expires_in is not None
            else None
        )
        if bundle.granted_scopes:
            grant.granted_scopes = list(bundle.granted_scopes)
        await session.commit()
        return bundle.access_token
