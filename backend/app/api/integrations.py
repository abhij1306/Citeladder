# Integrations router: OAuth connect (real 302 flow) + connection management
# (docs/roadmap/integrations.md section 5; invariant 5 + 6 + 12).
#
# Flat surface under /api/v1/integrations; the active workspace comes from
# ``require_active_workspace`` EXCEPT at the OAuth callback, where the
# workspace and user come only from the verified, consumed, nonce-bound OAuth
# transaction (spec section 2). The connect endpoints are full-page
# 302 navigations through the same-origin proxy (never fetch/XHR) — including
# the RETURN leg: the registered redirect URI is anchored on the app origin
# (``integration_oauth_redirect_uri``), so the provider's post-consent
# navigation carries the scoped transaction cookie the callback authenticates
# with. No endpoint ever returns a token — the DTOs carry no token fields
# (invariant 6).
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Query, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.browser_cookies import (
    clear_integration_oauth_cookie,
    set_integration_oauth_cookie,
)
from app.api.deps import (
    WorkspaceContext,
    get_db,
    require_active_workspace,
)
from app.connectors.integrations import IntegrationApiError
from app.core.config.abuse import abuse_settings
from app.core.config.integrations_contracts import (
    ERROR_MAPPING_ACTIVE_OWNER_CONFLICT,
    ERROR_MAPPING_PROPERTY_NOT_OWNED,
    ERROR_MAPPING_PROVIDER_MISMATCH,
    ERROR_OAUTH_EXCHANGE_FAILED,
    ERROR_OAUTH_NOT_CONFIGURED,
    ERROR_OAUTH_SHOP_INVALID,
    ERROR_OAUTH_STATE_INVALID,
    ERROR_PROPERTY_DISCOVERY_UNSUPPORTED,
    ERROR_SYNC_ACTIVE_WINDOW_CONFLICT,
    ERROR_SYNC_WINDOW_INVALID,
    SYNC_KIND_ON_DEMAND,
)
from app.core.config.integrations_transport import (
    INTEGRATION_OAUTH_TRANSACTION_COOKIE,
    INTEGRATION_PROVIDER_SHOPIFY,
    INTEGRATION_PROVIDERS,
    integration_oauth_landing_url,
    integration_oauth_redirect_uri,
    normalize_shopify_shop_domain,
)
from app.core.errors import ApiException
from app.core.http_errors import raise_api_error, raise_not_found
from app.domain.abuse.service import UsageLimitExceededError, enforce_and_commit
from app.domain.integrations.errors import (
    IntegrationConnectionNotFoundError,
    IntegrationExchangeError,
    IntegrationNotConfiguredError,
    IntegrationStateError,
    PropertyDiscoveryUnsupportedError,
)
from app.domain.integrations.mappings import (
    MappingActiveOwnerConflictError,
    MappingNotFoundError,
    MappingPropertyNotOwnedError,
    MappingProviderMismatchError,
    create_mapping,
    disable_mapping,
    list_mappings,
)
from app.domain.integrations.schemas import (
    IntegrationConnectionResponse,
    IntegrationPropertyMappingCreate,
    IntegrationPropertyMappingResponse,
    IntegrationPropertyResponse,
    IntegrationSyncEnqueueResponse,
    IntegrationSyncRunResponse,
    IntegrationTestResponse,
    SyncWindowRequest,
)
from app.domain.integrations.service import (
    complete_connect,
    delete_connection,
    list_available_properties,
    list_connections,
    run_connection_test,
    start_connect,
)
from app.domain.integrations.sync import (
    ActiveWindowConflictError,
    SyncRunNotFoundError,
    SyncWindowInvalidError,
    enqueue_sync_run,
    get_sync_run,
    list_sync_runs,
)
from app.domain.projects.service import ProjectNotFoundError

router = APIRouter(prefix="/integrations", tags=["integrations"])

_WorkspaceDep = Annotated[WorkspaceContext, Depends(require_active_workspace)]
_SessionDep = Annotated[AsyncSession, Depends(get_db)]

_RES_PROVIDER = "Integration provider"
_RES_CONNECTION = "Integration connection"
_RES_SYNC_RUN = "Integration sync run"
_RES_MAPPING = "Integration property mapping"
_RES_PROJECT = "Project"


def _require_known_provider(provider: str) -> None:
    """404 when ``provider`` is not a cataloged integration provider."""
    if provider not in INTEGRATION_PROVIDERS:
        raise_not_found(_RES_PROVIDER)


async def _enforce_discovery_limit(
    session: AsyncSession, *, ctx: WorkspaceContext, connection_id: uuid.UUID
) -> None:
    """Meter property discovery per (workspace, connection) — 429 when spent.

    Keyed on the connection rather than the caller: the quota being
    protected is the PROVIDER's, which is shared by everyone in the
    workspace, so two members reopening the same picker draw on one budget.
    """
    try:
        await enforce_and_commit(
            session,
            subject_kind="workspace",
            subject=f"{ctx.workspace_id}:{connection_id}",
            operation="integrations.properties",
            limit=abuse_settings.property_discovery_limit,
            window_seconds=abuse_settings.property_discovery_window_seconds,
        )
    except UsageLimitExceededError as exc:
        raise_api_error(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many property lookups",
            headers={"Retry-After": str(exc.retry_after_seconds)},
            cause=exc,
        )


def _landing_redirect(params: dict[str, str]) -> RedirectResponse:
    """302 back to Settings → Integrations with the result query (contract C2).

    The target is absolute (frontend origin) rather than a bare path: this
    handler also answers a callback delivered straight to the backend origin
    (a stale redirect URI registered with the provider), where a relative
    ``/settings`` would resolve against the backend and 404.
    """
    return RedirectResponse(
        integration_oauth_landing_url(params), status_code=status.HTTP_302_FOUND
    )


def _oauth_callback_redirect(params: dict[str, str]) -> RedirectResponse:
    response = _landing_redirect(params)
    clear_integration_oauth_cookie(response)
    return response


@router.get("/oauth/{provider}/start", status_code=status.HTTP_302_FOUND)
async def integration_oauth_start(
    provider: str,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    shop: Annotated[str, Query()] = "",
) -> RedirectResponse:
    """Begin the OAuth connect flow: 302 to the provider consent screen.

    ``shop`` is REQUIRED for Shopify (the per-shop OAuth target) and
    rejected for every other provider — both misuse forms are a 422, never
    a guessed redirect target.
    """
    _require_known_provider(provider)
    provider_account_ref = ""
    if provider == INTEGRATION_PROVIDER_SHOPIFY:
        if not shop.strip():
            raise_api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "A valid Shopify shop domain is required",
                code=ERROR_OAUTH_SHOP_INVALID,
                detail=ERROR_OAUTH_SHOP_INVALID,
            )
        try:
            provider_account_ref = normalize_shopify_shop_domain(shop)
        except ValueError as exc:
            raise_api_error(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                "A valid Shopify shop domain is required",
                code=ERROR_OAUTH_SHOP_INVALID,
                detail=ERROR_OAUTH_SHOP_INVALID,
                cause=exc,
            )
    elif shop.strip():
        raise_api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The shop parameter is only valid for Shopify",
            code=ERROR_OAUTH_SHOP_INVALID,
            detail=ERROR_OAUTH_SHOP_INVALID,
        )
    try:
        oauth_start = await start_connect(
            session,
            workspace_id=ctx.workspace_id,
            user_id=ctx.user.id,
            provider=provider,
            redirect_uri=integration_oauth_redirect_uri(provider),
            provider_account_ref=provider_account_ref,
        )
    except IntegrationNotConfiguredError as exc:
        raise_api_error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The integration provider is not configured",
            code=ERROR_OAUTH_NOT_CONFIGURED,
            detail=ERROR_OAUTH_NOT_CONFIGURED,
            cause=exc,
        )
    response = RedirectResponse(
        oauth_start.authorize_url, status_code=status.HTTP_302_FOUND
    )
    set_integration_oauth_cookie(response, oauth_start.session_nonce)
    return response


@router.get("/oauth/{provider}/callback", status_code=status.HTTP_302_FOUND)
async def integration_oauth_callback(
    provider: str,
    request: Request,
    session: _SessionDep,
    transaction_nonce: Annotated[
        str | None, Cookie(alias=INTEGRATION_OAUTH_TRANSACTION_COOKIE)
    ] = None,
    code: Annotated[str, Query()] = "",
    state: Annotated[str, Query()] = "",
    error: Annotated[str, Query()] = "",
) -> RedirectResponse:
    """Handle the provider redirect: verify + consume state, exchange, persist.

    Always 302s back to Settings → Integrations (contract C2) — success and
    failure alike — because the browser is mid full-page navigation.
    """
    _require_known_provider(provider)
    if error:
        # The provider reported a consent/authorization failure.
        return _oauth_callback_redirect({"error": ERROR_OAUTH_EXCHANGE_FAILED})
    if not code or not state:
        return _oauth_callback_redirect({"error": ERROR_OAUTH_STATE_INVALID})
    try:
        await complete_connect(
            session,
            provider=provider,
            code=code,
            state=state,
            session_nonce=transaction_nonce or "",
            redirect_uri=integration_oauth_redirect_uri(provider),
            # The full query map for the Shopify callback HMAC verification
            # (ignored by the single-tenant transports).
            callback_params={key: value for key, value in request.query_params.items()},
        )
    except IntegrationStateError:
        return _oauth_callback_redirect({"error": ERROR_OAUTH_STATE_INVALID})
    except IntegrationNotConfiguredError:
        return _oauth_callback_redirect({"error": ERROR_OAUTH_NOT_CONFIGURED})
    except IntegrationExchangeError:
        return _oauth_callback_redirect({"error": ERROR_OAUTH_EXCHANGE_FAILED})
    return _oauth_callback_redirect({"connected": provider})


@router.get("", response_model=list[IntegrationConnectionResponse])
async def list_integrations_endpoint(
    ctx: _WorkspaceDep, session: _SessionDep
) -> list[IntegrationConnectionResponse]:
    """List this workspace's connections joined to grant status + scopes."""
    return await list_connections(session, workspace_id=ctx.workspace_id)


@router.post(
    "/{connection_id}/test",
    response_model=IntegrationTestResponse,
)
async def test_integration_endpoint(
    connection_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> IntegrationTestResponse:
    """Cheap authenticated probe of the connection's grant (never the token)."""
    try:
        return await run_connection_test(
            session, workspace_id=ctx.workspace_id, connection_id=connection_id
        )
    except IntegrationConnectionNotFoundError as exc:
        raise_not_found(_RES_CONNECTION, cause=exc)


@router.get(
    "/{connection_id}/properties",
    response_model=list[IntegrationPropertyResponse],
)
async def list_properties_endpoint(
    connection_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> list[IntegrationPropertyResponse]:
    """List the provider properties this connection's grant can read.

    The picker's source of truth: the user chooses a site/property the
    provider confirms they own instead of typing a ref. 422 for a provider
    with no discoverable property list; 502 when the provider call itself
    fails, so a broken upstream is never rendered as "you own nothing".

    Every call spends provider API quota, so it is metered per
    (workspace, connection) — a reopened or stuck picker cannot drain the
    workspace's Google quota.
    """
    await _enforce_discovery_limit(session, ctx=ctx, connection_id=connection_id)
    try:
        return await list_available_properties(
            session, workspace_id=ctx.workspace_id, connection_id=connection_id
        )
    except IntegrationConnectionNotFoundError as exc:
        raise_not_found(_RES_CONNECTION, cause=exc)
    except PropertyDiscoveryUnsupportedError as exc:
        # Same canonical envelope as the 502 below: the caller reads one
        # machine-usable ``error.code`` for every failure of this endpoint.
        raise ApiException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            ERROR_PROPERTY_DISCOVERY_UNSUPPORTED,
            f"{exc} exposes no discoverable property list",
            retryable=False,
            detail=ERROR_PROPERTY_DISCOVERY_UNSUPPORTED,
        ) from exc
    except IntegrationApiError as exc:
        # The connector already classified the failure, so carry ITS
        # retryability into the envelope instead of letting the status
        # decide. A 502 is retryable by default, but a revoked or expired
        # grant (``grant_auth_failed``) is terminal until the user
        # reconnects — leaving it to classify by status makes the client
        # re-hammer a call that cannot start succeeding on its own.
        raise ApiException(
            status.HTTP_502_BAD_GATEWAY,
            exc.error_code,
            str(exc)[:512],
            retryable=exc.retryable,
        ) from exc


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_integration_endpoint(
    connection_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> None:
    """Disconnect a connection (last one on a grant also revokes the grant)."""
    try:
        await delete_connection(
            session, workspace_id=ctx.workspace_id, connection_id=connection_id
        )
    except IntegrationConnectionNotFoundError as exc:
        raise_not_found(_RES_CONNECTION, cause=exc)


# --- Sync runs (spec §5: enqueue 202 / history + detail projections) ----------


@router.post(
    "/{connection_id}/sync",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=IntegrationSyncEnqueueResponse,
)
async def enqueue_sync_endpoint(
    connection_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
    payload: SyncWindowRequest | None = None,
) -> IntegrationSyncEnqueueResponse:
    """Enqueue an on-demand sync run (202 + the run identity, contract C3).

    No body → the config default trailing window; an explicit window body is
    validated and clamped to the backfill budget. A run for the same window
    that is still active is a 409 (spec §5); a completed window re-syncs
    with a bumped ``resync_seq``.
    """
    try:
        run = await enqueue_sync_run(
            session,
            workspace_id=ctx.workspace_id,
            connection_id=connection_id,
            sync_kind=SYNC_KIND_ON_DEMAND,
            window_start=payload.window_start if payload else None,
            window_end=payload.window_end if payload else None,
        )
    except IntegrationConnectionNotFoundError as exc:
        raise_not_found(_RES_CONNECTION, cause=exc)
    except SyncWindowInvalidError as exc:
        raise_api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The requested sync window is invalid",
            code=ERROR_SYNC_WINDOW_INVALID,
            detail=ERROR_SYNC_WINDOW_INVALID,
            cause=exc,
        )
    except ActiveWindowConflictError as exc:
        # Same detail shape as the project-level sync fan-out 409
        # (api/traffic.py) — one dict contract per error token; here the
        # conflict means nothing was enqueued by this call.
        raise_api_error(
            status.HTTP_409_CONFLICT,
            "A sync window is already active for this connection",
            code=ERROR_SYNC_ACTIVE_WINDOW_CONFLICT,
            # ``detail`` keeps the exact legacy body: clients read ``error``
            # plus ``enqueued_connection_ids`` to learn which connections DID
            # enqueue before the clash. ``details`` mirrors it in the envelope.
            details={
                "error": ERROR_SYNC_ACTIVE_WINDOW_CONFLICT,
                "enqueued_connection_ids": [],
            },
            detail={
                "error": ERROR_SYNC_ACTIVE_WINDOW_CONFLICT,
                "enqueued_connection_ids": [],
            },
            cause=exc,
        )
    return IntegrationSyncEnqueueResponse(
        sync_run_id=run.id, connection_id=run.connection_id, status=run.status
    )


@router.get(
    "/{connection_id}/syncs",
    response_model=list[IntegrationSyncRunResponse],
)
async def list_syncs_endpoint(
    connection_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> list[IntegrationSyncRunResponse]:
    """Sync-run history for the connection (projection only, invariant 7)."""
    try:
        return await list_sync_runs(
            session, workspace_id=ctx.workspace_id, connection_id=connection_id
        )
    except IntegrationConnectionNotFoundError as exc:
        raise_not_found(_RES_CONNECTION, cause=exc)


@router.get(
    "/{connection_id}/syncs/{sync_run_id}",
    response_model=IntegrationSyncRunResponse,
)
async def get_sync_endpoint(
    connection_id: uuid.UUID,
    sync_run_id: uuid.UUID,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> IntegrationSyncRunResponse:
    """One sync run's detail projection (the poll target after a 202)."""
    try:
        return await get_sync_run(
            session,
            workspace_id=ctx.workspace_id,
            connection_id=connection_id,
            sync_run_id=sync_run_id,
        )
    except IntegrationConnectionNotFoundError as exc:
        raise_not_found(_RES_CONNECTION, cause=exc)
    except SyncRunNotFoundError as exc:
        raise_not_found(_RES_SYNC_RUN, cause=exc)


# --- Property mappings (spec §3: the property→project bridge) -----------------


@router.get(
    "/{connection_id}/mappings",
    response_model=list[IntegrationPropertyMappingResponse],
)
async def list_mappings_endpoint(
    connection_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> list[IntegrationPropertyMappingResponse]:
    """List the connection's property mappings (any status)."""
    try:
        return await list_mappings(
            session, workspace_id=ctx.workspace_id, connection_id=connection_id
        )
    except IntegrationConnectionNotFoundError as exc:
        raise_not_found(_RES_CONNECTION, cause=exc)


@router.post(
    "/{connection_id}/mappings",
    status_code=status.HTTP_201_CREATED,
    response_model=IntegrationPropertyMappingResponse,
)
async def create_mapping_endpoint(
    connection_id: uuid.UUID,
    payload: IntegrationPropertyMappingCreate,
    ctx: _WorkspaceDep,
    session: _SessionDep,
) -> IntegrationPropertyMappingResponse:
    """Create one ACTIVE property→project mapping (write-time validated).

    404 for a cross-workspace connection/project (invariant 5); 422 when the
    provider mismatches the connection or the property does not resolve to
    one of the project's owned domains; 409 when the
    ``(workspace, provider, property_ref)`` slot already has an active owner.
    """
    try:
        return await create_mapping(
            session,
            workspace_id=ctx.workspace_id,
            connection_id=connection_id,
            provider=payload.provider,
            property_ref=payload.property_ref,
            project_id=payload.project_id,
        )
    except IntegrationConnectionNotFoundError as exc:
        raise_not_found(_RES_CONNECTION, cause=exc)
    except ProjectNotFoundError as exc:
        raise_not_found(_RES_PROJECT, cause=exc)
    except MappingProviderMismatchError as exc:
        raise_api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The mapping provider does not match the connection provider",
            code=ERROR_MAPPING_PROVIDER_MISMATCH,
            detail=ERROR_MAPPING_PROVIDER_MISMATCH,
            cause=exc,
        )
    except MappingPropertyNotOwnedError as exc:
        raise_api_error(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "The property does not belong to the selected project",
            code=ERROR_MAPPING_PROPERTY_NOT_OWNED,
            detail=ERROR_MAPPING_PROPERTY_NOT_OWNED,
            cause=exc,
        )
    except MappingActiveOwnerConflictError as exc:
        raise_api_error(
            status.HTTP_409_CONFLICT,
            "An active mapping already owns this property",
            code=ERROR_MAPPING_ACTIVE_OWNER_CONFLICT,
            detail=ERROR_MAPPING_ACTIVE_OWNER_CONFLICT,
            cause=exc,
        )


@router.delete("/mappings/{mapping_id}", status_code=status.HTTP_204_NO_CONTENT)
async def disable_mapping_endpoint(
    mapping_id: uuid.UUID, ctx: _WorkspaceDep, session: _SessionDep
) -> None:
    """Disable a mapping (a status flip, never a row delete)."""
    try:
        await disable_mapping(
            session, workspace_id=ctx.workspace_id, mapping_id=mapping_id
        )
    except MappingNotFoundError as exc:
        raise_not_found(_RES_MAPPING, cause=exc)
