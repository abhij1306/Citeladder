"""Idempotent commercial intent: fingerprint, pending commit, provider call.

The exact sequence for every commercial POST (work order, Task 3):

1. authorize billing ownership (the caller resolves the owned account);
2. reject a deferred trial request FIRST — before any quote, pending row,
   provider call, or grant write;
3. canonicalize ``{operation, account_id, catalog_revision, catalog_key,
   quantity, credential_mode}`` and hash it;
4. lock/read the ``IdempotencyRecord``: replay the same fingerprint, REJECT a
   different fingerprint with 409;
5. validate catalog availability, quantity, current subscription/add-on state,
   and the SERVER-SIDE quote;
6. insert ``IdempotencyRecord(started)`` + ``PendingActivation(pending)`` and
   COMMIT;
7. call the provider AFTER the commit (invariant 8: never hold a transaction
   across network I/O);
8. persist only safe hosted-reference/checkout fields and complete the stored
   response;
9. on an UNCERTAIN provider error leave the row pending for reconciliation; on
   an AUTHORITATIVE failure mark it failed.

This path NEVER writes a grant: grants are issued only by the shared
activation transaction, driven by the provider's own authoritative record.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.billing.base import (
    BillingProviderError,
    HostedPayment,
    HostedSubscription,
    ProviderMetadata,
)
from app.core.config.billing_contracts import (
    ACTIVATION_FAILED,
    ACTIVATION_PENDING,
    IDEMPOTENCY_COMPLETED,
    IDEMPOTENCY_KEY_MAX_LENGTH,
    IDEMPOTENCY_KEY_MIN_LENGTH,
    IDEMPOTENCY_STARTED,
    PROVIDER_RAZORPAY,
    REASON_ADDON_PENDING,
    REASON_IDEMPOTENCY_KEY_REQUIRED,
    REASON_IDEMPOTENCY_KEY_REUSED,
    REASON_SUBSCRIPTION_PENDING,
    REASON_TRIAL_REQUESTED_UNAVAILABLE,
)
from app.core.config.billing_settings import (
    billing_settings,
)
from app.domain.billing.schemas import ActivationResponse
from app.domain.billing.service import BillingConflictError, ResolvedIntent
from app.models.billing import BillingAccount, IdempotencyRecord, PendingActivation

# A hosted result is either a subscription or a one-time payment.
HostedResult = HostedSubscription | HostedPayment
ProviderCall = Callable[[PendingActivation], Awaitable[HostedResult]]


class IdempotencyConflictError(ValueError):
    """The same key was reused with a DIFFERENT canonical request (409)."""


class TrialUnavailableError(ValueError):
    """A deferred trial was requested (409, before any write)."""


@dataclass(frozen=True, slots=True)
class IntentResult:
    """The safe activation response plus whether it was a stored replay."""

    response: ActivationResponse
    replayed: bool


def validate_idempotency_key(raw: str | None) -> str:
    """Require a bounded, well-formed ``Idempotency-Key`` header.

    A missing or malformed key REJECTS: without it a retry could double-charge.
    """
    key = (raw or "").strip()
    if not (
        IDEMPOTENCY_KEY_MIN_LENGTH <= len(key) <= IDEMPOTENCY_KEY_MAX_LENGTH
    ) or any(character.isspace() for character in key):
        raise ValueError(REASON_IDEMPOTENCY_KEY_REQUIRED)
    return key


def reject_deferred_trial(trial_requested: bool) -> None:
    """Refuse a deferred trial request BEFORE any quote/pending/provider write."""
    if trial_requested:
        raise TrialUnavailableError(REASON_TRIAL_REQUESTED_UNAVAILABLE)


def request_fingerprint(
    *,
    operation: str,
    account_id: uuid.UUID,
    catalog_revision: str,
    catalog_key: str,
    quantity: int,
    credential_mode: str,
) -> str:
    """SHA-256 over the canonical server-side request identity.

    Only server-owned fields participate: a browser cannot smuggle an amount,
    a currency, a provider reference, or a region into the identity.
    """
    canonical = json.dumps(
        {
            "operation": operation,
            "account_id": str(account_id),
            "catalog_revision": catalog_revision,
            "catalog_key": catalog_key,
            "quantity": quantity,
            "credential_mode": credential_mode,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(canonical).hexdigest()


async def _locked_record(
    session: AsyncSession, *, account_id: uuid.UUID, idempotency_key: str
) -> IdempotencyRecord | None:
    return await session.scalar(
        select(IdempotencyRecord)
        .where(
            IdempotencyRecord.billing_account_id == account_id,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
        .with_for_update()
    )


def _replay(record: IdempotencyRecord, fingerprint: str) -> ActivationResponse | None:
    """Byte-equivalent replay for the same fingerprint; 409 for a different one."""
    if record.request_fingerprint != fingerprint:
        raise IdempotencyConflictError(REASON_IDEMPOTENCY_KEY_REUSED)
    if record.response_body is None:
        return None
    return ActivationResponse.model_validate(record.response_body)


def _pending_response(pending: PendingActivation) -> ActivationResponse:
    """Project a pending row into its safe response (no provider ids)."""
    if pending.quote is None:  # pragma: no cover - always stored at insert
        raise RuntimeError("pending activation has no stored quote")
    return ActivationResponse(
        activation_id=pending.id,
        kind=pending.activation_kind,
        catalog_key=pending.catalog_key,
        quantity=pending.quantity,
        status=pending.status,
        quote=pending.quote,
        checkout_url=(
            pending.checkout_url if pending.status == ACTIVATION_PENDING else None
        ),
        expires_at=pending.expires_at,
        failure_code=pending.failure_code,
    )


async def _insert_intent(
    session: AsyncSession,
    *,
    account: BillingAccount,
    operation: str,
    intent: ResolvedIntent,
    idempotency_key: str,
    fingerprint: str,
    now: datetime,
) -> PendingActivation:
    """Insert the started record + pending row and COMMIT before provider I/O."""
    expires_at = now + timedelta(minutes=billing_settings.quote_validity_minutes)
    pending = PendingActivation(
        billing_account_id=account.id,
        activation_kind=intent.kind,
        catalog_key=intent.catalog_key,
        quantity=intent.quantity,
        catalog_revision=intent.quote.catalog_revision,
        credential_mode=intent.credential_mode,
        status=ACTIVATION_PENDING,
        provider=PROVIDER_RAZORPAY,
        external_price_id=intent.price_ref,
        quote=intent.quote.model_dump(mode="json"),
        country_code=intent.country_code,
        region=intent.region,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        expires_at=expires_at,
    )
    session.add(pending)
    session.add(
        IdempotencyRecord(
            billing_account_id=account.id,
            idempotency_key=idempotency_key,
            operation=operation,
            request_fingerprint=fingerprint,
            state=IDEMPOTENCY_STARTED,
            expires_at=expires_at,
        )
    )
    await session.commit()
    await session.refresh(pending)
    return pending


def provider_metadata(pending: PendingActivation) -> ProviderMetadata:
    """Only opaque server ids reach the provider (invariant 6)."""
    return ProviderMetadata(
        intent_id=str(pending.id),
        account_ref=str(pending.billing_account_id),
        catalog_revision=pending.catalog_revision,
    )


async def _complete(
    session: AsyncSession,
    *,
    account_id: uuid.UUID,
    idempotency_key: str,
    pending: PendingActivation,
    status_code: int,
) -> ActivationResponse:
    response = _pending_response(pending)
    record = await _locked_record(
        session, account_id=account_id, idempotency_key=idempotency_key
    )
    if record is not None:
        record.state = IDEMPOTENCY_COMPLETED
        record.response_status = status_code
        record.response_body = response.model_dump(mode="json")
    await session.commit()
    return response


def _apply_hosted_result(pending: PendingActivation, result: HostedResult) -> None:
    """Persist ONLY the safe hosted reference and checkout URL."""
    if isinstance(result, HostedSubscription):
        pending.external_reference = result.external_subscription_id
    else:
        pending.external_reference = result.external_payment_id
    pending.checkout_url = result.checkout_url


async def replay_intent(
    session: AsyncSession,
    *,
    account: BillingAccount,
    operation: str,
    catalog_key: str,
    quantity: int,
    credential_mode: str,
    idempotency_key: str,
) -> IntentResult | None:
    """Step 4 BEFORE step 5's state validation: replay or reject a reused key.

    The work order fixes this order deliberately. A retry of an already-settled
    purchase must replay its stored response byte-equivalently rather than
    tripping the "already active" state check, and a reused key with a
    DIFFERENT canonical request must 409 before any catalog/state work.

    Only server-owned fields form the fingerprint, so it is computable from the
    raw request without resolving a quote first.
    """
    fingerprint = request_fingerprint(
        operation=operation,
        account_id=account.id,
        catalog_revision=billing_settings.catalog_version,
        catalog_key=catalog_key,
        quantity=quantity,
        credential_mode=credential_mode,
    )
    record = await _locked_record(
        session, account_id=account.id, idempotency_key=idempotency_key
    )
    if record is None:
        return None
    replayed = _replay(record, fingerprint)
    if replayed is not None:
        return IntentResult(response=replayed, replayed=True)
    pending = await session.scalar(
        select(PendingActivation).where(
            PendingActivation.billing_account_id == account.id,
            PendingActivation.idempotency_key == idempotency_key,
        )
    )
    if pending is None:
        return None
    # A started-but-incomplete intent: report the COMMITTED pending state
    # rather than calling the provider a second time.
    return IntentResult(response=_pending_response(pending), replayed=True)


# The one-pending-slot partial unique indexes (PendingActivation.__table_args__
# and migrations/versions/0001_initial.py) mapped onto the SAME safe 409 code
# the pre-insert guard returns. A violation of one means a DIFFERENT-key
# intent already holds the unsettled slot — never replay it as a same-key win.
_PENDING_SLOT_REASONS: dict[str, str] = {
    "uq_pending_activation_one_pending_base": REASON_SUBSCRIPTION_PENDING,
    "uq_pending_activation_one_pending_addon": REASON_ADDON_PENDING,
}


def _violated_constraint_name(exc: IntegrityError) -> str | None:
    """The constraint a failed commit tripped, unwrapping driver adapters.

    SQLAlchemy's asyncpg dialect re-raises a fresh ``IntegrityError`` FROM the
    driver error, so the name lives somewhere on the ``__cause__`` chain
    (``constraint_name`` on asyncpg, ``diag.constraint_name`` on psycopg).
    """
    current: BaseException | None = exc.orig
    while current is not None:
        name = getattr(current, "constraint_name", None)  # asyncpg
        if name is None:
            diag = getattr(current, "diag", None)  # psycopg
            name = getattr(diag, "constraint_name", None) if diag is not None else None
        if name is not None:
            return name
        current = current.__cause__
    return None


async def _replay_insert_race_winner(
    session: AsyncSession,
    *,
    account: BillingAccount,
    operation: str,
    intent: ResolvedIntent,
    idempotency_key: str,
) -> IntentResult:
    """Replay the winner of a same-Idempotency-Key insert race.

    Two concurrent requests with the same fresh key both miss the FOR UPDATE
    read, both insert, and the loser's commit trips the account-key unique.
    That violation PROVES the winner's record is committed (Postgres reports
    it only after the winner commits), so replaying returns the winner's
    stored response: the SAME fingerprint replays, a DIFFERENT one still
    raises the 409 conflict — and the provider is never called twice.

    ``rollback()`` expires every persistent object regardless of
    ``expire_on_commit=False``, so the account must be re-loaded before any
    attribute (``account.id`` inside ``replay_intent``) is read again.
    """
    await session.rollback()
    await session.refresh(account)
    replayed = await replay_intent(
        session,
        account=account,
        operation=operation,
        catalog_key=intent.catalog_key,
        quantity=intent.quantity,
        credential_mode=intent.credential_mode,
        idempotency_key=idempotency_key,
    )
    if replayed is None:  # pragma: no cover - the winner committed first
        raise RuntimeError("insert-race loser found no winning idempotency record")
    return replayed


async def _recover_insert_race(
    session: AsyncSession,
    *,
    violation: IntegrityError,
    account: BillingAccount,
    operation: str,
    intent: ResolvedIntent,
    idempotency_key: str,
) -> IntentResult:
    """Map an intent-insert unique violation onto the right recovery.

    Two distinct losers reach this path:

    - SAME key: the (account, key) unique tripped, so replay the winner's
      committed intent (the provider is never called twice).
    - DIFFERENT key, same slot: a one-pending partial unique tripped, so an
      earlier intent is still settling — refuse with the SAME 409 code the
      pre-insert guard returns (never a 500, never a second provider call).

    The loser's transaction is dead either way: ``rollback()`` before any
    further read (it expires every persistent object regardless of
    ``expire_on_commit=False``).
    """
    reason = _PENDING_SLOT_REASONS.get(_violated_constraint_name(violation) or "")
    if reason is not None:
        await session.rollback()
        raise BillingConflictError(reason)
    return await _replay_insert_race_winner(
        session,
        account=account,
        operation=operation,
        intent=intent,
        idempotency_key=idempotency_key,
    )


async def _run_new_intent(
    session: AsyncSession,
    *,
    account: BillingAccount,
    operation: str,
    intent: ResolvedIntent,
    idempotency_key: str,
    fingerprint: str,
    provider_call: ProviderCall,
    status_code: int,
    at: datetime,
) -> IntentResult:
    """Steps 6-9 for a fresh key: commit the intent, call, settle."""
    try:
        pending = await _insert_intent(
            session,
            account=account,
            operation=operation,
            intent=intent,
            idempotency_key=idempotency_key,
            fingerprint=fingerprint,
            now=at,
        )
    except IntegrityError as exc:
        return await _recover_insert_race(
            session,
            violation=exc,
            account=account,
            operation=operation,
            intent=intent,
            idempotency_key=idempotency_key,
        )
    try:
        result = await provider_call(pending)
    except BillingProviderError as exc:
        if exc.retryable:
            # UNCERTAIN outcome: leave the row pending for reconciliation.
            # Nothing is uncommitted here — the intent committed BEFORE the
            # provider call (invariant 8) — so there is nothing to roll back.
            # A rollback would only EXPIRE ``pending`` (rollback ignores
            # ``expire_on_commit=False``) and break the projection below.
            return IntentResult(response=_pending_response(pending), replayed=False)
        pending.status = ACTIVATION_FAILED
        pending.failed_at = at
        pending.failure_code = exc.code
        return IntentResult(
            response=await _complete(
                session,
                account_id=account.id,
                idempotency_key=idempotency_key,
                pending=pending,
                status_code=status_code,
            ),
            replayed=False,
        )
    _apply_hosted_result(pending, result)
    return IntentResult(
        response=await _complete(
            session,
            account_id=account.id,
            idempotency_key=idempotency_key,
            pending=pending,
            status_code=status_code,
        ),
        replayed=False,
    )


async def execute_intent(
    session: AsyncSession,
    *,
    account: BillingAccount,
    operation: str,
    intent: ResolvedIntent,
    idempotency_key: str,
    provider_call: ProviderCall,
    status_code: int,
    now: datetime | None = None,
) -> IntentResult:
    """Run the full idempotent intent sequence for one commercial POST.

    Steps 3-9. The caller owns steps 1-2 (ownership + trial rejection) and
    step 5's catalog/state validation via ``intent``.
    """
    at = now or datetime.now(UTC)
    fingerprint = request_fingerprint(
        operation=operation,
        account_id=account.id,
        catalog_revision=intent.quote.catalog_revision,
        catalog_key=intent.catalog_key,
        quantity=intent.quantity,
        credential_mode=intent.credential_mode,
    )
    replayed = await replay_intent(
        session,
        account=account,
        operation=operation,
        catalog_key=intent.catalog_key,
        quantity=intent.quantity,
        credential_mode=intent.credential_mode,
        idempotency_key=idempotency_key,
    )
    if replayed is not None:
        return replayed
    return await _run_new_intent(
        session,
        account=account,
        operation=operation,
        intent=intent,
        idempotency_key=idempotency_key,
        fingerprint=fingerprint,
        provider_call=provider_call,
        status_code=status_code,
        at=at,
    )


__all__ = [
    "IdempotencyConflictError",
    "IntentResult",
    "TrialUnavailableError",
    "execute_intent",
    "provider_metadata",
    "reject_deferred_trial",
    "replay_intent",
    "request_fingerprint",
    "validate_idempotency_key",
]
