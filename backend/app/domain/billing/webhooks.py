"""Razorpay webhook authentication, dedupe, and activation dispatch.

Order of operations is security-critical: the body-size guard and the HMAC
signature check run in the API layer BEFORE any JSON-driven activation, and
``BillingWebhookEvent`` replay protection runs before any side effect. Parsing
is extended only for CONFIGURED subscription and payment events; a valid but
unmatched event is recorded safely and grants NOTHING.

``payment.captured`` activates a pending top-up only after the amount, the
currency, and the external metadata match that pending intent (the verification
lives in the shared activation transaction, which both this path and the manual
reconciliation sweep call).
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.billing.base import ProviderPayment, ProviderSubscription
from app.core.config.billing_contracts import (
    ACTIVATION_AUTHORITY_WEBHOOK,
    ACTIVATION_PENDING,
    PROVIDER_RAZORPAY,
    RAZORPAY_EVENT_TYPES,
    RAZORPAY_PAYMENT_EVENT_TYPES,
    RAZORPAY_PAYMENT_STATUS_MAP,
)
from app.core.config.billing_settings import (
    billing_settings,
)
from app.domain.billing.activations import (
    ActivationRejectedError,
    ProviderRecord,
    activate_pending,
)
from app.domain.billing.service import apply_subscription_state
from app.models.billing import (
    BillingSubscription,
    BillingWebhookEvent,
    PendingActivation,
)

_NOTE_INTENT = "citeladder_intent_id"
_NOTE_ACCOUNT = "citeladder_account_ref"

RESULT_IGNORED = "ignored"
RESULT_DUPLICATE = "duplicate"
RESULT_UNMATCHED = "unmatched"
RESULT_APPLIED = "applied"
RESULT_STALE = "stale"
RESULT_ACTIVATED = "activated"
RESULT_REJECTED = "rejected"


class InvalidWebhookError(ValueError):
    pass


def verify_razorpay_signature(raw_body: bytes, signature: str) -> bool:
    secret = billing_settings.razorpay_webhook_secret.get_secret_value()
    if not secret or not signature or len(signature) > 256:
        return False
    expected = hmac.new(secret.encode(), raw_body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature.strip())


def _parse_payload(raw_body: bytes) -> tuple[dict[str, Any], str]:
    try:
        payload = json.loads(raw_body)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise InvalidWebhookError("invalid_json") from exc
    if not isinstance(payload, dict):
        raise InvalidWebhookError("invalid_payload")
    event_type = payload.get("event")
    if not isinstance(event_type, str) or not event_type:
        raise InvalidWebhookError("invalid_event")
    return payload, event_type


def _entity(payload: dict[str, Any], name: str) -> dict[str, Any]:
    nested = payload.get("payload")
    if not isinstance(nested, dict):
        raise InvalidWebhookError("invalid_payload")
    wrapper = nested.get(name)
    if not isinstance(wrapper, dict):
        raise InvalidWebhookError("invalid_payload")
    entity = wrapper.get("entity")
    if not isinstance(entity, dict):
        raise InvalidWebhookError("invalid_payload")
    return entity


def _bounded_ref(value: object, error: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 255:
        raise InvalidWebhookError(error)
    return value


def _notes(entity: dict[str, Any]) -> dict[str, Any]:
    notes = entity.get("notes")
    return notes if isinstance(notes, dict) else {}


def parse_subscription_event(payload: dict[str, Any]) -> ProviderSubscription:
    """Translate a configured subscription event into the provider DTO."""
    entity = _entity(payload, "subscription")
    external_id = _bounded_ref(entity.get("id"), "invalid_subscription")
    status = entity.get("status")
    if not isinstance(status, str) or len(status) > 32:
        raise InvalidWebhookError("invalid_subscription")
    notes = _notes(entity)
    return ProviderSubscription(
        external_subscription_id=external_id,
        status=status,
        current_start=_bounded_int(entity.get("current_start")),
        current_end=_bounded_int(entity.get("current_end")),
        updated_at=(
            _bounded_int(entity.get("updated_at"))
            or _bounded_int(payload.get("created_at"))
            or 0
        ),
        cancel_at_period_end=_provider_bool(entity.get("cancel_at_cycle_end")),
        price_ref=_optional_str(entity.get("plan_id")),
        intent_id=_optional_str(notes.get(_NOTE_INTENT)),
        account_ref=_optional_str(notes.get(_NOTE_ACCOUNT)),
    )


def parse_payment_event(payload: dict[str, Any]) -> ProviderPayment:
    """Translate a configured payment event into the provider DTO."""
    entity = _entity(payload, "payment")
    external_id = _bounded_ref(entity.get("id"), "invalid_payment")
    status = entity.get("status")
    amount = _bounded_int(entity.get("amount"))
    currency = entity.get("currency")
    if (
        not isinstance(status, str)
        or status not in RAZORPAY_PAYMENT_STATUS_MAP
        or amount is None
        or not isinstance(currency, str)
        or len(currency) != 3
    ):
        raise InvalidWebhookError("invalid_payment")
    notes = _notes(entity)
    created_at = _bounded_int(payload.get("created_at")) or 0
    return ProviderPayment(
        external_payment_id=external_id,
        status=RAZORPAY_PAYMENT_STATUS_MAP[status],
        amount_minor=amount,
        currency=currency.upper(),
        updated_at=created_at,
        paid_at=_bounded_int(entity.get("created_at")) or created_at or None,
        intent_id=_optional_str(notes.get(_NOTE_INTENT)),
        account_ref=_optional_str(notes.get(_NOTE_ACCOUNT)),
    )


def _safe_summary(reference: str, status: str) -> dict[str, str]:
    """Only a HASHED provider reference and the safe status are persisted."""
    return {
        "reference_hash": hashlib.sha256(reference.encode()).hexdigest(),
        "status": status,
    }


async def _record_event(
    session: AsyncSession,
    *,
    raw_body: bytes,
    event_id: str,
    event_type: str,
    summary: dict[str, str],
) -> BillingWebhookEvent | None:
    """Insert the replay-protection row; None when it is a duplicate."""
    inserted_id = await session.scalar(
        pg_insert(BillingWebhookEvent)
        .values(
            provider=PROVIDER_RAZORPAY,
            external_event_id=event_id,
            event_type=event_type,
            payload_sha256=hashlib.sha256(raw_body).hexdigest(),
            safe_summary=summary,
        )
        .on_conflict_do_nothing(index_elements=["provider", "external_event_id"])
        .returning(BillingWebhookEvent.id)
    )
    if inserted_id is None:
        await session.rollback()
        return None
    event = await session.get(BillingWebhookEvent, inserted_id)
    if event is None:  # pragma: no cover
        raise RuntimeError("inserted webhook event could not be loaded")
    return event


async def _finish(
    session: AsyncSession, event: BillingWebhookEvent, result_code: str
) -> str:
    event.result_code = result_code
    event.processed_at = datetime.now(UTC)
    await session.commit()
    return result_code


async def _pending_for_reference(
    session: AsyncSession, reference: str
) -> PendingActivation | None:
    return await session.scalar(
        select(PendingActivation).where(
            PendingActivation.provider == PROVIDER_RAZORPAY,
            PendingActivation.external_reference == reference,
            PendingActivation.status == ACTIVATION_PENDING,
        )
    )


async def _activate_from_event(
    session: AsyncSession,
    *,
    event: BillingWebhookEvent,
    record: ProviderRecord,
    reference: str,
    event_id: str,
) -> str:
    """Settle the matching pending activation through the SHARED transaction."""
    pending = await _pending_for_reference(session, reference)
    if pending is None:
        return RESULT_UNMATCHED
    pending_id = pending.id
    event_row_id = event.id
    try:
        await activate_pending(
            session,
            pending_id=pending_id,
            provider_record=record,
            authority=ACTIVATION_AUTHORITY_WEBHOOK,
            authority_id=event_id,
            at=datetime.now(UTC),
        )
    except ActivationRejectedError:
        # A valid but unverifiable event grants NOTHING and is recorded safely.
        await session.rollback()
        refreshed = await session.get(BillingWebhookEvent, event_row_id)
        if refreshed is not None:
            await _finish(session, refreshed, RESULT_REJECTED)
        return RESULT_REJECTED
    refreshed = await session.get(BillingWebhookEvent, event_row_id)
    if refreshed is not None:
        await _finish(session, refreshed, RESULT_ACTIVATED)
    return RESULT_ACTIVATED


async def _process_subscription_event(
    session: AsyncSession,
    *,
    event: BillingWebhookEvent,
    record: ProviderSubscription,
    event_id: str,
) -> str:
    subscription = await session.scalar(
        select(BillingSubscription).where(
            BillingSubscription.provider == PROVIDER_RAZORPAY,
            BillingSubscription.external_subscription_id
            == record.external_subscription_id,
        )
    )
    if subscription is None:
        return await _activate_from_event(
            session,
            event=event,
            record=record,
            reference=record.external_subscription_id,
            event_id=event_id,
        )
    applied = await apply_subscription_state(
        session,
        subscription,
        provider_status=record.status,
        current_start=record.current_start,
        current_end=record.current_end,
        updated_at=record.updated_at,
        cancel_at_period_end=record.cancel_at_period_end,
    )
    return await _finish(session, event, RESULT_APPLIED if applied else RESULT_STALE)


async def process_razorpay_webhook(
    session: AsyncSession,
    *,
    raw_body: bytes,
    event_id: str,
) -> str:
    """Dedupe and dispatch ONE authenticated webhook. Signature is already
    verified by the caller; nothing here trusts a JSON-supplied amount.
    """
    if not event_id or len(event_id) > 255:
        raise InvalidWebhookError("invalid_event_id")
    payload, event_type = _parse_payload(raw_body)
    is_payment = event_type in RAZORPAY_PAYMENT_EVENT_TYPES
    if not is_payment and event_type not in RAZORPAY_EVENT_TYPES:
        return RESULT_IGNORED
    record: ProviderRecord = (
        parse_payment_event(payload)
        if is_payment
        else parse_subscription_event(payload)
    )
    reference = (
        record.external_payment_id
        if isinstance(record, ProviderPayment)
        else record.external_subscription_id
    )
    event = await _record_event(
        session,
        raw_body=raw_body,
        event_id=event_id,
        event_type=event_type,
        summary=_safe_summary(reference, record.status),
    )
    if event is None:
        return RESULT_DUPLICATE
    # COMMIT the replay-protection boundary before dispatch: a rejected
    # activation rolls back its own side effects and must never take the
    # received-event row down with it.
    await session.commit()
    if isinstance(record, ProviderPayment):
        result = await _activate_from_event(
            session,
            event=event,
            record=record,
            reference=reference,
            event_id=event_id,
        )
    else:
        result = await _process_subscription_event(
            session, event=event, record=record, event_id=event_id
        )
    if result == RESULT_UNMATCHED:
        # Valid signature, no matching row: recorded safely, grants NOTHING.
        return await _finish(session, event, RESULT_UNMATCHED)
    return result


def _bounded_int(value: object) -> int | None:
    if (
        isinstance(value, int)
        and not isinstance(value, bool)
        and 0 <= value <= 2**63 - 1
    ):
        return value
    return None


def _optional_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _provider_bool(value: object) -> bool:
    return value is True or value == 1


__all__ = [
    "InvalidWebhookError",
    "parse_payment_event",
    "parse_subscription_event",
    "process_razorpay_webhook",
    "verify_razorpay_signature",
]
