"""Integrations connect + connection-management service (workspace-scoped).

Implements docs/roadmap/integrations.md §2 (OAuth connect flow) and the §5
management surface:

- The state nonce binds the callback to its browser transaction and the
  initiating user + workspace (signed claims + persisted row), is verified for
  signature/expiry/user binding, and is consumed ATOMICALLY (``UPDATE ... SET
  consumed_at ... WHERE consumed_at IS NULL``) BEFORE the code exchange — a replayed,
  cross-user, or cross-workspace state is rejected before any token moves.
- Tokens are Fernet-encrypted (``encrypt_secret`` — invariant 2/6) and
  stored ONCE on the workspace's ``IntegrationOAuthGrant`` (find-or-create
  per transport); one Google consent attaches BOTH the GSC and GA4
  connections to the one shared grant, Bing attaches one connection to a
  Microsoft grant.
- Tokens are decrypted only here, only for an exchange/probe/revoke call,
  and never enter a DTO, a log line, or an event payload (invariant 6).
- No DB transaction is held open across a provider call: the state
  consumption and the connection delete commit BEFORE the exchange/revoke
  network I/O (invariant 8).
"""

from __future__ import annotations

import secrets
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.integrations import bing as bing_connector
from app.connectors.integrations import oauth as integration_oauth
from app.connectors.integrations import shopify as shopify_connector
from app.connectors.integrations.oauth import OAuthTokenBundle
from app.core.config.integrations_clients import (
    INTEGRATION_CLIENT_BUILDERS,
    INTEGRATION_PROPERTY_DISCOVERY_PROVIDERS,
)
from app.core.config.integrations_contracts import (
    ERROR_PROVIDER_API,
    EVENT_INTEGRATION_CONNECTED,
    EVENT_INTEGRATION_DISCONNECTED,
    EVENT_INTEGRATION_REVOKE_FAILED,
    EVENT_INTEGRATION_REVOKED,
    EVENT_INTEGRATION_TESTED,
    GRANT_STATUS_CONNECTED,
    GRANT_STATUS_PENDING_REVOCATION,
    GRANT_STATUS_REVOKED,
)
from app.core.config.integrations_transport import (
    INTEGRATION_OAUTH_AUTHORIZE_URLS,
    INTEGRATION_OAUTH_REVOKE_URLS,
    INTEGRATION_OAUTH_SCOPES,
    INTEGRATION_PROVIDER_TRANSPORT,
    INTEGRATION_TRANSPORT_GOOGLE,
    INTEGRATION_TRANSPORT_SHOPIFY,
    shopify_oauth_authorize_url,
)
from app.core.config.oauth import oauth_settings
from app.core.config.provider_catalog import TEST_STATUS_FAILED, TEST_STATUS_OK
from app.core.security import (
    create_oauth_state,
    decrypt_secret,
    encrypt_secret,
)
from app.domain.integrations.errors import (
    IntegrationConnectionNotFoundError,
    IntegrationExchangeError,
    IntegrationNotConfiguredError,
    IntegrationOAuthStart,
    PropertyDiscoveryUnsupportedError,
)
from app.domain.integrations.schemas import (
    IntegrationConnectionResponse,
    IntegrationPropertyResponse,
    IntegrationTestResponse,
)
from app.domain.integrations.state import (
    consume_state,
    prepare_connect_callback,
    validate_shopify_state_match,
)
from app.domain.integrations.tokens import fresh_access_token
from app.models.integrations import (
    IntegrationConnection,
    IntegrationEvent,
    IntegrationOAuthGrant,
    IntegrationOAuthState,
)


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _providers_for_transport(transport: str) -> list[str]:
    """Logical providers riding one transport grant (config-owned map)."""
    return sorted(
        provider
        for provider, mapped in INTEGRATION_PROVIDER_TRANSPORT.items()
        if mapped == transport
    )


# --- OAuth connect flow (spec §2) -------------------------------------------


async def start_connect(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    user_id: uuid.UUID,
    provider: str,
    redirect_uri: str,
    provider_account_ref: str = "",
) -> IntegrationOAuthStart:
    """Mint + persist the OAuth state row and build the provider authorize URL.

    The state JWT carries the workspace/user/jti binding claims and a random
    nonce returned for the short-lived transaction cookie; the persisted row
    enables atomic one-time consumption at the callback.
    ``provider_account_ref`` is the per-account OAuth target (Shopify: the
    canonical shop host, validated by the caller): it is persisted on the
    state row AND signed into the state JWT so the callback can require an
    exact three-way match (claim, persisted value, provider-returned shop).
    """
    transport = INTEGRATION_PROVIDER_TRANSPORT[provider]
    if not integration_oauth.oauth_client_configured(transport):
        raise IntegrationNotConfiguredError(provider)
    jti = secrets.token_urlsafe(24)
    state_token, session_nonce = create_oauth_state(
        provider,
        workspace_id=str(workspace_id),
        user_id=str(user_id),
        jti=jti,
        provider_account_ref=provider_account_ref or None,
    )
    session.add(
        IntegrationOAuthState(
            jti=jti,
            workspace_id=workspace_id,
            user_id=user_id,
            provider=provider,
            provider_account_ref=provider_account_ref,
            expires_at=_utcnow() + timedelta(seconds=oauth_settings.state_ttl_seconds),
        )
    )
    await session.commit()
    client_id, _client_secret = integration_oauth.oauth_client_credentials(transport)
    if transport == INTEGRATION_TRANSPORT_SHOPIFY:
        # Shopify's per-shop authorize endpoint: no ``response_type`` and no
        # offline/consent extras — the custom-app grant IS the offline token.
        # Scopes join with COMMAS (Shopify's form), never spaces.
        params = {
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": ",".join(INTEGRATION_OAUTH_SCOPES[transport]),
            "state": state_token,
        }
        authorize_url = shopify_oauth_authorize_url(provider_account_ref)
        return IntegrationOAuthStart(
            authorize_url=f"{authorize_url}?{urlencode(params)}",
            session_nonce=session_nonce,
        )
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(INTEGRATION_OAUTH_SCOPES[transport]),
        "state": state_token,
    }
    if transport == INTEGRATION_TRANSPORT_GOOGLE:
        # Google issues a refresh token only for an offline, consent-forced
        # authorization request.
        params["access_type"] = "offline"
        params["prompt"] = "consent"
    return IntegrationOAuthStart(
        authorize_url=(
            f"{INTEGRATION_OAUTH_AUTHORIZE_URLS[transport]}?{urlencode(params)}"
        ),
        session_nonce=session_nonce,
    )


async def _find_or_create_grant(
    session: AsyncSession, *, workspace_id: uuid.UUID, transport: str
) -> IntegrationOAuthGrant:
    """One grant per (workspace, transport) — the find-or-create contract."""
    result = await session.execute(
        select(IntegrationOAuthGrant)
        .where(
            IntegrationOAuthGrant.workspace_id == workspace_id,
            IntegrationOAuthGrant.transport == transport,
        )
        .with_for_update()
    )
    grant = result.scalar_one_or_none()
    if grant is not None:
        return grant
    grant = IntegrationOAuthGrant(
        workspace_id=workspace_id,
        transport=transport,
        status=GRANT_STATUS_CONNECTED,
    )
    session.add(grant)
    try:
        await session.flush()
    except IntegrityError:
        # A concurrent connect created the (workspace, transport) grant
        # first; this transaction holds only the insert, so a rollback is
        # safe and the winner's row is re-read.
        await session.rollback()
        result = await session.execute(
            select(IntegrationOAuthGrant).where(
                IntegrationOAuthGrant.workspace_id == workspace_id,
                IntegrationOAuthGrant.transport == transport,
            )
        )
        grant = result.scalar_one()
    return grant


async def _attach_connections(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    grant: IntegrationOAuthGrant,
    transport: str,
    provider_account_ref: str = "",
) -> list[IntegrationConnection]:
    """Attach the transport's logical connections to the grant (idempotent).

    One Google consent yields exactly one ``gsc`` + one ``ga4`` row on the
    shared grant; Bing yields one ``bing`` row on a Microsoft grant; a
    Shopify consent yields one ``shopify`` row whose ``account_ref`` is the
    canonical shop host the token was issued for. ``provider_account_ref``
    is empty for the single-tenant transports, which never set an
    account_ref here.
    """
    attached: list[IntegrationConnection] = []
    for provider in _providers_for_transport(transport):
        result = await session.execute(
            select(IntegrationConnection).where(
                IntegrationConnection.grant_id == grant.id,
                IntegrationConnection.provider == provider,
            )
        )
        connection = result.scalar_one_or_none()
        if connection is None:
            connection = IntegrationConnection(
                workspace_id=workspace_id,
                grant_id=grant.id,
                provider=provider,
            )
            session.add(connection)
            await session.flush()
        if provider_account_ref:
            # Bind the connection to the exact per-account target (Shopify:
            # the canonical shop); a re-connect to another shop re-points
            # the single transport connection with its fresh token.
            connection.account_ref = provider_account_ref
        attached.append(connection)
    return attached


async def _exchange_connect_code(
    *,
    transport: str,
    provider_account_ref: str,
    code: str,
    redirect_uri: str,
) -> OAuthTokenBundle:
    client = integration_oauth.build_oauth_client(
        transport, provider_account_ref=provider_account_ref
    )
    try:
        return await client.exchange_code(code=code, redirect_uri=redirect_uri)
    except integration_oauth.IntegrationOAuthError as exc:
        raise IntegrationExchangeError(str(exc)) from exc


async def _persist_connected_grant(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    transport: str,
    provider: str,
    provider_account_ref: str,
    bundle: OAuthTokenBundle,
) -> None:
    grant = await _find_or_create_grant(
        session, workspace_id=workspace_id, transport=transport
    )
    # encrypt_secret both tokens (invariant 6) — stored once, on the grant.
    grant.access_token_encrypted = encrypt_secret(bundle.access_token)
    if bundle.refresh_token:
        grant.refresh_token_encrypted = encrypt_secret(bundle.refresh_token)
    grant.token_expires_at = (
        _utcnow() + timedelta(seconds=bundle.expires_in)
        if bundle.expires_in is not None
        else None
    )
    if bundle.granted_scopes:
        grant.granted_scopes = list(bundle.granted_scopes)
    grant.status = GRANT_STATUS_CONNECTED
    attached = await _attach_connections(
        session,
        workspace_id=workspace_id,
        grant=grant,
        transport=transport,
        provider_account_ref=provider_account_ref,
    )
    session.add(
        IntegrationEvent(
            workspace_id=workspace_id,
            grant_id=grant.id,
            event_type=EVENT_INTEGRATION_CONNECTED,
            message=f"Integration connected via {transport}",
            payload={
                "provider": provider,
                "transport": transport,
                "providers": [connection.provider for connection in attached],
                "connection_ids": [str(connection.id) for connection in attached],
            },
        )
    )


async def complete_connect(
    session: AsyncSession,
    *,
    provider: str,
    code: str,
    state: str,
    session_nonce: str,
    redirect_uri: str,
    callback_params: Mapping[str, str] | None = None,
) -> None:
    """Verify + consume the state, exchange the code, persist the grant.

    The workspace comes ONLY from the verified, consumed state (never from
    client input — invariant 5). The consumption commits before the code
    exchange so no transaction is held open across the provider call.

    Shopify callbacks additionally require, BEFORE the exchange: (1) the
    callback HMAC-SHA256 verified against the full query parameter map
    (``callback_params``); (2) an EXACT three-way shop match across the
    signed state claim, the persisted state value, and the callback's
    ``shop`` parameter. Both reject as state errors — nothing is
    exchanged for an unauthenticated or mis-bound callback.
    """
    transport, claims, signed_account_ref = prepare_connect_callback(
        provider=provider,
        state=state,
        session_nonce=session_nonce,
        callback_params=callback_params,
    )
    workspace_id, persisted_account_ref = await consume_state(
        session, claims=claims, provider=provider
    )
    if transport == INTEGRATION_TRANSPORT_SHOPIFY:
        validate_shopify_state_match(
            signed_account_ref=signed_account_ref,
            persisted_account_ref=persisted_account_ref,
            callback_params=callback_params,
        )
    await session.commit()
    bundle = await _exchange_connect_code(
        transport=transport,
        provider_account_ref=persisted_account_ref,
        code=code,
        redirect_uri=redirect_uri,
    )
    await _persist_connected_grant(
        session,
        workspace_id=workspace_id,
        transport=transport,
        provider=provider,
        provider_account_ref=persisted_account_ref,
        bundle=bundle,
    )
    await session.commit()


# --- Connection management (spec §5) ----------------------------------------


async def get_connection(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> IntegrationConnection:
    result = await session.execute(
        select(IntegrationConnection).where(
            IntegrationConnection.id == connection_id,
            IntegrationConnection.workspace_id == workspace_id,
        )
    )
    connection = result.scalar_one_or_none()
    if connection is None:
        raise IntegrationConnectionNotFoundError(str(connection_id))
    return connection


async def _get_grant(
    session: AsyncSession, *, workspace_id: uuid.UUID, grant_id: uuid.UUID
) -> IntegrationOAuthGrant:
    result = await session.execute(
        select(IntegrationOAuthGrant).where(
            IntegrationOAuthGrant.id == grant_id,
            IntegrationOAuthGrant.workspace_id == workspace_id,
        )
    )
    grant = result.scalar_one_or_none()
    if grant is None:
        # A connection's grant must exist in the same workspace (composite
        # FK); reaching here means corrupted state.
        raise IntegrationConnectionNotFoundError(str(grant_id))
    return grant


async def list_connections(
    session: AsyncSession, *, workspace_id: uuid.UUID
) -> list[IntegrationConnectionResponse]:
    """Connections joined to their grant's status + scopes — tokens absent."""
    result = await session.execute(
        select(IntegrationConnection, IntegrationOAuthGrant)
        .join(
            IntegrationOAuthGrant,
            IntegrationConnection.grant_id == IntegrationOAuthGrant.id,
        )
        .where(IntegrationConnection.workspace_id == workspace_id)
        .order_by(
            IntegrationConnection.created_at.asc(), IntegrationConnection.id.asc()
        )
    )
    return [
        IntegrationConnectionResponse(
            id=connection.id,
            workspace_id=connection.workspace_id,
            grant_id=connection.grant_id,
            provider=connection.provider,
            label=connection.label,
            account_ref=connection.account_ref,
            grant_status=grant.status,
            granted_scopes=list(grant.granted_scopes or []),
            last_synced_at=connection.last_synced_at,
            created_at=connection.created_at,
            updated_at=connection.updated_at,
        )
        for connection, grant in result.all()
    ]


async def run_connection_test(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> IntegrationTestResponse:
    """Probe the provider with the grant's decrypted token (decrypt-in-place).

    Mirrors ``domain/providers/service.py::run_connection_test``: the token
    is decrypted only here, used for one cheap authenticated call, and never
    logged or persisted anywhere but the encrypted grant columns. The outcome
    is recorded as an append-only ``IntegrationEvent``.
    """
    connection = await get_connection(
        session, workspace_id=workspace_id, connection_id=connection_id
    )
    grant = await _get_grant(
        session, workspace_id=workspace_id, grant_id=connection.grant_id
    )

    status = TEST_STATUS_OK
    error_code = ""
    detail = "Connection succeeded"
    try:
        access_token = decrypt_secret(grant.access_token_encrypted)
        if grant.transport == INTEGRATION_TRANSPORT_GOOGLE:
            client = integration_oauth.build_oauth_client(grant.transport)
            await client.probe_access_token(access_token=access_token)
        elif grant.transport == INTEGRATION_TRANSPORT_SHOPIFY:
            # The provider-specific GraphQL probe (``shop { id }``) against
            # the connection's canonical shop — the Google probe is not
            # reused. The grant is untouched: a probe is not a rotation.
            shopify_client = shopify_connector.build_shopify_client()
            await shopify_client.probe_access_token(
                access_token=access_token, property_ref=connection.account_ref
            )
        else:
            # Real cheap authenticated probe against the pinned Bing host
            # (I12, replacing the refresh round-trip placeholder): the
            # ``GetSites`` verified-site list validates the Microsoft
            # grant's access token. The grant is untouched — a probe is
            # not a credential rotation.
            bing_client = bing_connector.build_bing_client()
            await bing_client.probe_access_token(access_token=access_token)
    except (
        integration_oauth.IntegrationOAuthError,
        bing_connector.BingApiError,
        shopify_connector.ShopifyApiError,
    ) as exc:
        status = TEST_STATUS_FAILED
        error_code = exc.error_code
        detail = str(exc)[:1024]
    except Exception as exc:  # noqa: BLE001 - any decrypt/transport fault fails the probe
        status = TEST_STATUS_FAILED
        error_code = ERROR_PROVIDER_API
        detail = f"Unexpected error: {type(exc).__name__}"

    tested_at = _utcnow()
    session.add(
        IntegrationEvent(
            workspace_id=workspace_id,
            connection_id=connection.id,
            grant_id=grant.id,
            event_type=EVENT_INTEGRATION_TESTED,
            message=f"Connection test {status}",
            payload={
                "provider": connection.provider,
                "status": status,
                "error_code": error_code,
            },
        )
    )
    await session.commit()
    return IntegrationTestResponse(
        connection_id=connection.id,
        status=status,
        error_code=error_code,
        detail=detail,
        tested_at=tested_at,
    )


async def list_available_properties(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> list[IntegrationPropertyResponse]:
    """List the provider properties this connection's grant can read.

    Backs the property picker: the user selects a site/property that Google
    confirms they own, so ``account_ref`` is never typed or guessed. The
    token is refreshed when near expiry (a grant connected an hour ago must
    not make the picker fail) and is used for exactly one read-only listing
    call — never logged or returned (invariant 6).

    Only the providers whose property is DISCOVERABLE are supported: a
    Shopify connection's property is the shop it was authorized for, which
    the connect flow already pinned onto ``account_ref``, and Bing exposes
    no property listing in this pass. Both raise
    ``PropertyDiscoveryUnsupportedError`` rather than returning an empty
    list, which would read as "you own nothing".
    """
    connection = await get_connection(
        session, workspace_id=workspace_id, connection_id=connection_id
    )
    if connection.provider not in INTEGRATION_PROPERTY_DISCOVERY_PROVIDERS:
        raise PropertyDiscoveryUnsupportedError(connection.provider)
    grant = await _get_grant(
        session, workspace_id=workspace_id, grant_id=connection.grant_id
    )
    access_token = await fresh_access_token(session, grant=grant)
    # The same config-owned dispatch the sync worker resolves its data
    # client through (invariant 1) — discovery is one more call on it.
    client = INTEGRATION_CLIENT_BUILDERS[connection.provider]()
    properties = await client.list_properties(access_token=access_token)
    return [
        IntegrationPropertyResponse(property_ref=prop.property_ref, label=prop.label)
        for prop in properties
    ]


async def delete_connection(
    session: AsyncSession,
    *,
    workspace_id: uuid.UUID,
    connection_id: uuid.UUID,
) -> None:
    """Remove a connection; revoke the grant only when it was the LAST one.

    Spec §5: credentials live on the shared grant, so provider revocation is
    grant-scoped and fires only when the last connection on the grant is
    removed. Local disconnect and remote revocation are separated (the
    connection delete commits before any provider call, invariant 8) so a
    failed remote revoke can never orphan a live remote grant:

    - remote-revoke SUCCESS → grant ``revoked`` + encrypted tokens dropped;
    - remote-revoke FAILURE → tokens RETAINED + grant ``pending_revocation``
      (a background retry or a later manual DELETE can finish the job);
    - Microsoft has no revocation endpoint (config URL is ``""``) →
      documented local-only path: no remote call, grant ``revoked``, tokens
      dropped.

    An ``IntegrationEvent`` is appended for every outcome.
    """
    connection = await get_connection(
        session, workspace_id=workspace_id, connection_id=connection_id
    )
    grant = await _get_grant(
        session, workspace_id=workspace_id, grant_id=connection.grant_id
    )
    siblings = await session.execute(
        select(func.count(IntegrationConnection.id)).where(
            IntegrationConnection.grant_id == grant.id,
            IntegrationConnection.id != connection.id,
        )
    )
    is_last = siblings.scalar_one() == 0
    provider = connection.provider
    await session.delete(connection)
    if not is_last:
        # Other connections still use the shared grant: its tokens are
        # retained and nothing is revoked remotely.
        session.add(
            IntegrationEvent(
                workspace_id=workspace_id,
                grant_id=grant.id,
                event_type=EVENT_INTEGRATION_DISCONNECTED,
                message=(f"Connection {provider} disconnected; shared grant retained"),
                payload={
                    "provider": provider,
                    "connection_id": str(connection_id),
                    "grant_retained": True,
                },
            )
        )
        await session.commit()
        return
    # Commit the local disconnect BEFORE the remote revoke call so no
    # transaction is held open across provider I/O (invariant 8).
    await session.commit()

    revoke_url = INTEGRATION_OAUTH_REVOKE_URLS[grant.transport]
    remote_ok = True
    remote_error_code = ""
    if revoke_url:
        client = integration_oauth.build_oauth_client(grant.transport)
        try:
            # The refresh token is the long-lived credential — revoking it
            # revokes the whole grant at the provider.
            token = decrypt_secret(
                grant.refresh_token_encrypted or grant.access_token_encrypted
            )
            await client.revoke(token=token)
        except integration_oauth.IntegrationOAuthError as exc:
            remote_ok = False
            remote_error_code = exc.error_code
        except Exception:  # noqa: BLE001 - any decrypt/transport fault = failed revoke
            remote_ok = False
            remote_error_code = ERROR_PROVIDER_API

    if remote_ok:
        grant.status = GRANT_STATUS_REVOKED
        grant.access_token_encrypted = ""
        grant.refresh_token_encrypted = ""
        grant.token_expires_at = None
        event_type = EVENT_INTEGRATION_REVOKED
        message = (
            "Grant revoked at provider"
            if revoke_url
            else "Grant revoked locally (transport has no remote revoke endpoint)"
        )
        payload = {
            "provider": provider,
            "transport": grant.transport,
            "connection_id": str(connection_id),
            "remote_revoke": bool(revoke_url),
        }
    else:
        # Tokens are deliberately retained so a later retry can complete the
        # remote revocation before the credentials are destroyed (spec §5).
        grant.status = GRANT_STATUS_PENDING_REVOCATION
        event_type = EVENT_INTEGRATION_REVOKE_FAILED
        message = "Remote revoke failed; tokens retained pending retry"
        payload = {
            "provider": provider,
            "transport": grant.transport,
            "connection_id": str(connection_id),
            "error_code": remote_error_code,
        }
    session.add(
        IntegrationEvent(
            workspace_id=workspace_id,
            grant_id=grant.id,
            event_type=event_type,
            message=message,
            payload=payload,
        )
    )
    await session.commit()
