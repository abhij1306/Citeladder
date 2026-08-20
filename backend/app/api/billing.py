"""The v8 commercial billing surface.

Routes, in the frozen order of the work order:

1. ``GET  /billing/catalog``        public preview catalog (no auth);
2. ``GET  /billing/entitlement``    authenticated account read;
3. ``GET  /billing/usage``          authenticated account read;
4. ``POST /billing/subscriptions``  the ONE base purchase route (202 pending);
5. ``DELETE /billing/subscription`` schedule base cancellation;
6. ``POST /billing/addons``         add-on activation;
7. ``POST /billing/topups``         top-up purchase;
8. ``DELETE /billing/addons/{key}`` schedule add-on cancellation;
9. ``POST /billing/webhooks/razorpay`` signed ingress, 204 with no body.

The v6 ``/billing/me``, ``/billing/profile``, ``/billing/checkout``,
``/billing/cancel``, and ``/billing/manage`` routes are DELETED without
aliases, as is ``GET /workspaces/{id}/entitlements``.

Invariant 5: every mutation and every account read authorizes through the
BILLING OWNER (``BillingAccount.owner_user_id``) via ``owned_account``; the
public catalog is the single deliberate exception because it reads no account,
workspace, connection, or probe. Invariant 6: no route accepts or returns an
amount, a currency, a region, a provider reference, or an external provider id
— the browser submits only a catalog key, a quantity, a credential mode, and an
ISO country, and the SERVER-resolved quote drives every provider argument.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Annotated

from fastapi import (
    APIRouter,
    Depends,
    Header,
    Query,
    Request,
    Response,
    status,
)
from fastapi import Path as PathParam
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user, get_db
from app.connectors.billing.base import (
    BillingProvider,
    BillingProviderError,
    HostedPayment,
    HostedSubscription,
)
from app.connectors.billing.factory import get_billing_provider
from app.core.config.billing_contracts import (
    ACTIVATION_PENDING,
    CREDENTIAL_MODE_BYOK,
    LIVE_SUBSCRIPTION_STATUSES,
    OPERATION_ADDON_ACTIVATE,
    OPERATION_SUBSCRIPTION_CREATE,
    OPERATION_TOPUP_PURCHASE,
    REASON_ADDON_EXISTS,
    REASON_ADDON_PENDING,
    REASON_SUBSCRIPTION_EXISTS,
    REASON_SUBSCRIPTION_PENDING,
)
from app.core.config.billing_settings import (
    billing_settings,
)
from app.core.http_errors import raise_api_error
from app.domain.billing.catalog import public_catalog
from app.domain.billing.idempotency import (
    IdempotencyConflictError,
    ProviderCall,
    TrialUnavailableError,
    execute_intent,
    provider_metadata,
    reject_deferred_trial,
    replay_intent,
    validate_idempotency_key,
)
from app.domain.billing.reads import account_entitlement, account_usage
from app.domain.billing.schemas import (
    ActivationResponse,
    AddonActivateRequest,
    BillingCatalogResponse,
    BillingEntitlementResponse,
    BillingUsageResponse,
    SubscriptionChangeResponse,
    SubscriptionCreateRequest,
    TopupPurchaseRequest,
)
from app.domain.billing.service import (
    BillingConflictError,
    ResolvedIntent,
    current_addon_subscription,
    current_base_subscription,
    live_base_subscription,
    owned_account,
    pending_addon_activation,
    pending_base_activation,
    persist_billing_country,
    resolve_addon_intent,
    resolve_base_intent,
    resolve_topup_intent,
    schedule_addon_cancellation,
    schedule_base_cancellation,
)
from app.domain.billing.webhooks import (
    InvalidWebhookError,
    process_razorpay_webhook,
    verify_razorpay_signature,
)
from app.models.billing import BillingAccount, PendingActivation
from app.models.user import User

router = APIRouter(tags=["billing"])


def _idempotency_key(
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> str:
    """Require a well-formed ``Idempotency-Key`` on every commercial mutation.

    A missing or malformed key REJECTS with 400: without it a browser retry
    could double-charge.
    """
    try:
        return validate_idempotency_key(idempotency_key)
    except ValueError as exc:
        raise_api_error(400, str(exc), cause=exc)


IdempotencyKey = Annotated[str, Depends(_idempotency_key)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Session = Annotated[AsyncSession, Depends(get_db)]


@contextmanager
def _safe_commercial_errors() -> Iterator[None]:
    """Map domain refusals onto safe HTTP statuses (never a provider message)."""
    try:
        yield
    except (
        TrialUnavailableError,
        IdempotencyConflictError,
        BillingConflictError,
    ) as exc:
        raise_api_error(409, str(exc), cause=exc)
    except BillingProviderError as exc:
        raise_api_error(502, exc.code, cause=exc)


def _activation_status_code(activation: ActivationResponse) -> int:
    """202 while an external hosted checkout is still pending, else 200."""
    if activation.status == ACTIVATION_PENDING:
        return status.HTTP_202_ACCEPTED
    return status.HTTP_200_OK


async def _replayed_activation(
    session: AsyncSession,
    *,
    account: BillingAccount,
    operation: str,
    catalog_key: str,
    quantity: int,
    credential_mode: str,
    idempotency_key: str,
    response: Response,
) -> ActivationResponse | None:
    """Step 4 BEFORE step 5: the stored response for an already-seen key.

    Every commercial POST runs this first so a retry of an already-settled
    purchase replays byte-equivalently instead of tripping the route's own
    "already live" state guard; a reused key with a DIFFERENT canonical
    request raises the 409 inside ``replay_intent``. Returning None means the
    key is fresh and the route proceeds to its state check.
    """
    replayed = await replay_intent(
        session,
        account=account,
        operation=operation,
        catalog_key=catalog_key,
        quantity=quantity,
        credential_mode=credential_mode,
        idempotency_key=idempotency_key,
    )
    if replayed is None:
        return None
    response.status_code = _activation_status_code(replayed.response)
    return replayed.response


async def _run_intent(
    session: AsyncSession,
    *,
    account: BillingAccount,
    operation: str,
    intent: ResolvedIntent,
    idempotency_key: str,
    provider_call: ProviderCall,
    response: Response,
) -> ActivationResponse:
    """Commit the intent, call the provider, and project the safe response."""
    result = await execute_intent(
        session,
        account=account,
        operation=operation,
        intent=intent,
        idempotency_key=idempotency_key,
        provider_call=provider_call,
        status_code=status.HTTP_202_ACCEPTED,
    )
    response.status_code = _activation_status_code(result.response)
    return result.response


@router.get("/billing/catalog", response_model=BillingCatalogResponse)
async def get_catalog(
    country: Annotated[str | None, Query(max_length=2)] = None,
) -> BillingCatalogResponse:
    """The PUBLIC commercial catalog (invariant 5 exception by design).

    It reads no workspace data, no provider connection, and no probe, so it
    needs no ``require_workspace_member`` boundary — everything workspace- or
    account-scoped stays authenticated. ``country`` is a PREVIEW hint only:
    when it is omitted the response reports a null country and the
    config-owned international preview region, and a purchase must still submit
    its own ISO country.
    """
    return public_catalog(country)


@router.get("/billing/entitlement", response_model=BillingEntitlementResponse)
async def get_entitlement(
    user: CurrentUser,
    session: Session,
) -> BillingEntitlementResponse:
    """The authenticated account entitlement read; commits nothing."""
    account = await owned_account(session, user)
    return await account_entitlement(session, account=account, at=datetime.now(UTC))


@router.get("/billing/usage", response_model=BillingUsageResponse)
async def get_usage(user: CurrentUser, session: Session) -> BillingUsageResponse:
    """The authenticated account usage read; commits nothing.

    Balances come from the immutable consumable ledger and every expiry is the
    MOVING effective expiry, not a grant's stored fixed date.
    """
    account = await owned_account(session, user)
    return await account_usage(session, account=account, at=datetime.now(UTC))


@router.post(
    "/billing/subscriptions",
    response_model=ActivationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_subscription(
    payload: SubscriptionCreateRequest,
    user: CurrentUser,
    session: Session,
    idempotency_key: IdempotencyKey,
    response: Response,
) -> ActivationResponse:
    """The ONE base-purchase route.

    ``trial_requested=true`` refuses with ``409 trial_unavailable`` BEFORE any
    quote, pending row, provider call, or grant write. The submitted ISO
    country is re-resolved and LOCKED on the account here: with
    ``/billing/profile`` deleted this is the single writer of the persisted
    billing country.
    """
    provider = get_billing_provider()
    with _safe_commercial_errors():
        reject_deferred_trial(payload.trial_requested)
        account = await owned_account(session, user)
        replayed = await _replayed_activation(
            session,
            account=account,
            operation=OPERATION_SUBSCRIPTION_CREATE,
            catalog_key=payload.catalog_key,
            quantity=1,
            credential_mode=payload.credential_mode,
            idempotency_key=idempotency_key,
            response=response,
        )
        if replayed is not None:
            return replayed
        await _reject_existing_base(session, account)
        intent = resolve_base_intent(
            catalog_key=payload.catalog_key,
            credential_mode=payload.credential_mode,
            country_code=payload.country_code,
            at=datetime.now(UTC),
        )
        persist_billing_country(account, payload.country_code)
        return await _run_intent(
            session,
            account=account,
            operation=OPERATION_SUBSCRIPTION_CREATE,
            intent=intent,
            idempotency_key=idempotency_key,
            provider_call=_base_provider_call(provider, intent),
            response=response,
        )


@router.post(
    "/billing/addons",
    response_model=ActivationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_addon(
    payload: AddonActivateRequest,
    user: CurrentUser,
    session: Session,
    idempotency_key: IdempotencyKey,
    response: Response,
) -> ActivationResponse:
    """Activate one add-on. A coming-soon add-on refuses with
    ``provider_unavailable`` before any provider I/O or grant issuance.
    """
    provider = get_billing_provider()
    with _safe_commercial_errors():
        account = await owned_account(session, user)
        replayed = await _replayed_activation(
            session,
            account=account,
            operation=OPERATION_ADDON_ACTIVATE,
            catalog_key=payload.catalog_key,
            quantity=payload.quantity,
            credential_mode=CREDENTIAL_MODE_BYOK,
            idempotency_key=idempotency_key,
            response=response,
        )
        if replayed is not None:
            return replayed
        await _reject_existing_addon(session, account, payload.catalog_key)
        intent = resolve_addon_intent(
            catalog_key=payload.catalog_key,
            quantity=payload.quantity,
            country_code=_purchase_country(account),
            at=datetime.now(UTC),
        )
        return await _run_intent(
            session,
            account=account,
            operation=OPERATION_ADDON_ACTIVATE,
            intent=intent,
            idempotency_key=idempotency_key,
            provider_call=_addon_provider_call(provider, intent),
            response=response,
        )


@router.post(
    "/billing/topups",
    response_model=ActivationResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def post_topup(
    payload: TopupPurchaseRequest,
    user: CurrentUser,
    session: Session,
    idempotency_key: IdempotencyKey,
    response: Response,
) -> ActivationResponse:
    """Purchase one top-up pack.

    A top-up funds nothing without a readable live base subscription, so the
    purchase is refused here — before any provider I/O.
    """
    provider = get_billing_provider()
    with _safe_commercial_errors():
        account = await owned_account(session, user)
        replayed = await _replayed_activation(
            session,
            account=account,
            operation=OPERATION_TOPUP_PURCHASE,
            catalog_key=payload.catalog_key,
            quantity=payload.quantity,
            credential_mode=CREDENTIAL_MODE_BYOK,
            idempotency_key=idempotency_key,
            response=response,
        )
        if replayed is not None:
            return replayed
        await _require_live_base(session, account)
        intent = resolve_topup_intent(
            catalog_key=payload.catalog_key,
            quantity=payload.quantity,
            country_code=_purchase_country(account),
            at=datetime.now(UTC),
        )
        return await _run_intent(
            session,
            account=account,
            operation=OPERATION_TOPUP_PURCHASE,
            intent=intent,
            idempotency_key=idempotency_key,
            provider_call=_topup_provider_call(provider, intent),
            response=response,
        )


@router.delete("/billing/subscription", response_model=SubscriptionChangeResponse)
async def delete_subscription(
    user: CurrentUser,
    session: Session,
    idempotency_key: IdempotencyKey,
) -> SubscriptionChangeResponse:
    """Schedule the current base subscription's PERIOD-END cancellation.

    Deliberately NOT an ``ActivationResponse``: it carries no
    pending/activated/failed/abandoned vocabulary. Current grant rows are never
    touched — the issued period ends naturally and no next bundle is issued.
    The operation is naturally idempotent (a second call reports
    ``already_scheduled``), and the mandatory key keeps the contract uniform
    across every commercial mutation.
    """
    del idempotency_key
    provider = get_billing_provider()
    with _safe_commercial_errors():
        account = await owned_account(session, user)
        catalog_key, change_status, effective_at = await schedule_base_cancellation(
            session, provider, account_id=account.id
        )
        return SubscriptionChangeResponse(
            catalog_key=catalog_key, status=change_status, effective_at=effective_at
        )


@router.delete("/billing/addons/{key}", response_model=SubscriptionChangeResponse)
async def delete_addon(
    user: CurrentUser,
    session: Session,
    idempotency_key: IdempotencyKey,
    key: Annotated[str, PathParam(max_length=64)],
) -> SubscriptionChangeResponse:
    """Schedule one add-on's PERIOD-END cancellation (grants untouched)."""
    del idempotency_key
    provider = get_billing_provider()
    with _safe_commercial_errors():
        account = await owned_account(session, user)
        change_status, effective_at = await schedule_addon_cancellation(
            session, provider, account_id=account.id, catalog_key=key
        )
        return SubscriptionChangeResponse(
            catalog_key=key, status=change_status, effective_at=effective_at
        )


@router.post("/billing/webhooks/razorpay", status_code=status.HTTP_204_NO_CONTENT)
async def razorpay_webhook(
    request: Request,
    session: Session,
    signature: Annotated[str, Header(alias="X-Razorpay-Signature")],
    event_id: Annotated[str, Header(alias="X-Razorpay-Event-Id")],
) -> Response:
    """Signed webhook ingress: 204 with NO response body.

    The body-size guard and the HMAC signature check both run BEFORE any JSON
    parsing or activation, so an unsigned or oversized body never reaches the
    activation transaction and grants nothing.
    """
    body = bytearray()
    async for chunk in request.stream():
        if len(body) + len(chunk) > billing_settings.max_webhook_body_bytes:
            raise_api_error(413, "Webhook body too large")
        body.extend(chunk)
    raw_body = bytes(body)
    if not verify_razorpay_signature(raw_body, signature):
        raise_api_error(400, "Invalid webhook signature")
    try:
        await process_razorpay_webhook(session, raw_body=raw_body, event_id=event_id)
    except InvalidWebhookError as exc:
        raise_api_error(400, str(exc), cause=exc)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------------------
# Server-owned state guards and provider calls
# ---------------------------------------------------------------------------
# Every provider argument below comes from the SERVER-resolved quote/intent: a
# browser can submit only a catalog key, a quantity, a credential mode, and an
# ISO country, never an amount, a currency, or a provider reference.


def _purchase_country(account: BillingAccount) -> str:
    """The ISO country an add-on/top-up is priced for.

    Only the base purchase carries a country, so it is the single writer of the
    persisted account country; every later purchase re-resolves the region from
    that locked value server-side.
    """
    return account.billing_country


async def _reject_live_base(session: AsyncSession, account: BillingAccount) -> None:
    """Refuse a second base purchase while one is LIVE."""
    subscription = await current_base_subscription(session, account.id)
    if subscription is not None and subscription.status in LIVE_SUBSCRIPTION_STATUSES:
        raise BillingConflictError(REASON_SUBSCRIPTION_EXISTS)


async def _reject_unsettled_base(
    session: AsyncSession, account: BillingAccount
) -> None:
    """Refuse a base purchase while an earlier intent is still SETTLING.

    A committed ``pending`` base holds the one-base slot exactly as a live
    subscription does — otherwise two different-key intents both reach the
    provider. The partial unique index stays the final TOCTOU guard inside
    the intent commit.
    """
    if await pending_base_activation(session, account.id) is not None:
        raise BillingConflictError(REASON_SUBSCRIPTION_PENDING)


async def _reject_existing_base(session: AsyncSession, account: BillingAccount) -> None:
    """Refuse a second base purchase while one is live OR still settling."""
    await _reject_live_base(session, account)
    await _reject_unsettled_base(session, account)


async def _reject_live_addon(
    session: AsyncSession, account: BillingAccount, catalog_key: str
) -> None:
    """Refuse a duplicate add-on while one is LIVE (quantity changes are a
    separate, later operation).
    """
    subscription = await current_addon_subscription(session, account.id, catalog_key)
    if subscription is not None and subscription.status in LIVE_SUBSCRIPTION_STATUSES:
        raise BillingConflictError(REASON_ADDON_EXISTS)


async def _reject_unsettled_addon(
    session: AsyncSession, account: BillingAccount, catalog_key: str
) -> None:
    """Refuse an add-on intent while an earlier one for the SAME (account,
    catalog_key) is still settling; other add-on keys and top-ups are
    unaffected.
    """
    if await pending_addon_activation(session, account.id, catalog_key) is not None:
        raise BillingConflictError(REASON_ADDON_PENDING)


async def _reject_existing_addon(
    session: AsyncSession, account: BillingAccount, catalog_key: str
) -> None:
    """Refuse a duplicate add-on while one is live OR still settling."""
    await _reject_live_addon(session, account, catalog_key)
    await _reject_unsettled_addon(session, account, catalog_key)


async def _require_live_base(session: AsyncSession, account: BillingAccount) -> None:
    """A top-up requires a readable LIVE base subscription (checked twice: here
    before provider I/O, and again inside the activation transaction).
    """
    await live_base_subscription(session, account.id)


def _base_provider_call(
    provider: BillingProvider, intent: ResolvedIntent
) -> ProviderCall:
    """Create the hosted base subscription from the SERVER-resolved price ref.

    Trial checkout is deferred, so ``trial_days`` is always None here.
    """

    async def call(pending: PendingActivation) -> HostedSubscription:
        return await provider.create_base_subscription(
            price_ref=intent.price_ref,
            intent_id=str(pending.id),
            account_ref=str(pending.billing_account_id),
            trial_days=None,
            metadata=provider_metadata(pending),
        )

    return call


def _addon_provider_call(
    provider: BillingProvider, intent: ResolvedIntent
) -> ProviderCall:
    async def call(pending: PendingActivation) -> HostedSubscription:
        return await provider.create_addon_subscription(
            price_ref=intent.price_ref,
            quantity=pending.quantity,
            intent_id=str(pending.id),
            account_ref=str(pending.billing_account_id),
            metadata=provider_metadata(pending),
        )

    return call


def _topup_provider_call(
    provider: BillingProvider, intent: ResolvedIntent
) -> ProviderCall:
    """Charge exactly the server-resolved total (base + credit + tax)."""
    total = intent.quote.total_price

    async def call(pending: PendingActivation) -> HostedPayment:
        return await provider.create_one_time_payment(
            amount_minor=total.amount_minor,
            currency=total.currency,
            intent_id=str(pending.id),
            account_ref=str(pending.billing_account_id),
            metadata=provider_metadata(pending),
        )

    return call
