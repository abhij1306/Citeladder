"""Component tests for the v8 commercial WRITE path.

Covered here: the idempotent POST routes (subscriptions/add-ons/top-ups), the
trial-first refusal, the pending-before-provider commit boundary, the shared
activation transaction driven by the signed webhook, the webhook/reconciliation
replay + race (exactly one subscription row, one grant bundle, one lifecycle
increment), the bounded reconciliation sweep transitions, the moving effective
expiry on usage reads, and the deleted legacy routes returning 404.

The provider is ALWAYS a fake — no live-key test.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api import billing as billing_api
from app.connectors.billing.base import (
    BillingProviderError,
    HostedPayment,
    HostedSubscription,
    ProviderPayment,
    ProviderSubscription,
)
from app.core.config.billing import (
    ACTIVATION_AUTHORITY_RECONCILIATION,
    ACTIVATION_AUTHORITY_WEBHOOK,
    OPERATION_SUBSCRIPTION_CREATE,
    REASON_ADDON_PENDING,
    REASON_SUBSCRIPTION_PENDING,
    billing_settings,
)
from app.domain.billing import idempotency as idempotency_module
from app.domain.billing.activations import activate_pending
from app.domain.billing.idempotency import IntentResult, execute_intent
from app.domain.billing.reconciliation import reconcile_pending_activations
from app.domain.billing.service import BillingConflictError, resolve_base_intent
from app.models.billing import (
    AccountGrant,
    BillingAccount,
    BillingSubscription,
    BillingWebhookEvent,
    IdempotencyRecord,
    PendingActivation,
)
from tests.component.auth_helpers import register_and_login as _register
from tests.component.log_capture import capture_log_messages

_SECRET = "commercial-webhook-secret"
_PLAN_REF = "plan_test_private"
_TOPUP_REF = "plink_test_private"
_TOPUP_KEY = "topup_benchmark_credits"


# --- helpers -----------------------------------------------------------------
def _sign(raw: bytes) -> str:
    return hmac.new(_SECRET.encode(), raw, hashlib.sha256).hexdigest()


async def _post_webhook(
    client: httpx.AsyncClient, raw: bytes, *, event_id: str
) -> httpx.Response:
    return await client.post(
        "/api/v1/billing/webhooks/razorpay",
        content=raw,
        headers={
            "X-Razorpay-Signature": _sign(raw),
            "X-Razorpay-Event-Id": event_id,
            "Content-Type": "application/json",
        },
    )


def _enable_checkout(monkeypatch: pytest.MonkeyPatch, refs: dict[str, str]) -> None:
    monkeypatch.setattr(billing_settings, "checkout_enabled", True)
    monkeypatch.setattr(billing_settings, "razorpay_live_ready", True)
    monkeypatch.setattr(billing_settings, "razorpay_international_ready", True)
    monkeypatch.setattr(billing_settings, "provider_price_refs", refs)
    monkeypatch.setattr(billing_settings, "razorpay_webhook_secret", SecretStr(_SECRET))


def _subscription_activation_payload(
    *,
    external_id: str,
    intent_id: str,
    account_ref: str,
    updated_at: int,
    current_start: int,
    current_end: int,
    price_ref: str = _PLAN_REF,
) -> bytes:
    entity = {
        "id": external_id,
        "status": "active",
        "updated_at": updated_at,
        "current_start": current_start,
        "current_end": current_end,
        "plan_id": price_ref,
        "notes": {
            "citeladder_intent_id": intent_id,
            "citeladder_account_ref": account_ref,
        },
    }
    return json.dumps(
        {
            "event": "subscription.activated",
            "created_at": updated_at,
            "payload": {"subscription": {"entity": entity}},
        },
        separators=(",", ":"),
    ).encode()


def _payment_payload(
    *,
    external_id: str,
    amount: int,
    paid_at: int,
    intent_id: str = "",
    account_ref: str = "",
    currency: str = "USD",
) -> bytes:
    entity: dict[str, object] = {
        "id": external_id,
        "status": "captured",
        "amount": amount,
        "currency": currency,
        "created_at": paid_at,
        "notes": {
            "citeladder_intent_id": intent_id,
            "citeladder_account_ref": account_ref,
        },
    }
    return json.dumps(
        {
            "event": "payment.captured",
            "created_at": paid_at,
            "payload": {"payment": {"entity": entity}},
        },
        separators=(",", ":"),
    ).encode()


class _FakeProvider:
    """A recording provider double. Asserts the pending row is COMMITTED before
    any provider call (invariant: the intent boundary precedes network I/O).
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        subscription_id: str = "sub_fake",
        payment_id: str = "pay_fake",
    ) -> None:
        self._factory = session_factory
        self.subscription_id = subscription_id
        self.payment_id = payment_id
        self.base_calls: list[dict[str, object]] = []
        self.addon_calls: list[dict[str, object]] = []
        self.payment_calls: list[dict[str, object]] = []

    async def _assert_pending_committed(self, intent_id: str) -> None:
        async with self._factory() as session:
            pending = await session.get(PendingActivation, uuid.UUID(intent_id))
            assert pending is not None, "pending must commit before provider I/O"
            assert pending.status == "pending"

    async def create_base_subscription(
        self, *, price_ref, intent_id, account_ref, trial_days, metadata
    ) -> HostedSubscription:
        await self._assert_pending_committed(intent_id)
        self.base_calls.append({"price_ref": price_ref, "trial_days": trial_days})
        return HostedSubscription(
            external_subscription_id=self.subscription_id,
            checkout_url=f"https://rzp.io/i/{self.subscription_id}",
            status="created",
            price_ref=price_ref,
        )

    async def create_addon_subscription(
        self, *, price_ref, quantity, intent_id, account_ref, metadata
    ) -> HostedSubscription:
        await self._assert_pending_committed(intent_id)
        self.addon_calls.append({"price_ref": price_ref, "quantity": quantity})
        return HostedSubscription(
            external_subscription_id=self.subscription_id,
            checkout_url=f"https://rzp.io/i/{self.subscription_id}",
            status="created",
            price_ref=price_ref,
        )

    async def create_one_time_payment(
        self, *, amount_minor, currency, intent_id, account_ref, metadata
    ) -> HostedPayment:
        await self._assert_pending_committed(intent_id)
        self.payment_calls.append({"amount_minor": amount_minor, "currency": currency})
        return HostedPayment(
            external_payment_id=self.payment_id,
            checkout_url=f"https://rzp.io/i/{self.payment_id}",
            status="payment_pending",
            amount_minor=amount_minor,
            currency=currency,
        )


async def _account(db_session: AsyncSession) -> BillingAccount:
    return (await db_session.scalars(select(BillingAccount))).one()


async def _account_version(db_session: AsyncSession) -> int:
    return (await _account(db_session)).entitlement_lifecycle_version


async def _seed_live_base(
    db_session: AsyncSession, account: BillingAccount, *, period_days: int = 30
) -> BillingSubscription:
    now = datetime.now(UTC)
    subscription = BillingSubscription(
        billing_account_id=account.id,
        external_subscription_id="sub_live_base",
        external_price_id=_PLAN_REF,
        catalog_key="tier_1",
        currency="USD",
        status="active",
        is_current=True,
        current_period_start=now,
        current_period_end=now + timedelta(days=period_days),
    )
    db_session.add(subscription)
    await db_session.commit()
    return subscription


def _quote_dict(*, catalog_key: str, total_minor: int) -> dict[str, object]:
    now = datetime.now(UTC)
    return {
        "quote_id": "q" * 64,
        "catalog_revision": billing_settings.catalog_version,
        "catalog_key": catalog_key,
        "credential_mode": "byok",
        "country_code": "US",
        "region": "international",
        "base_price": {"currency": "USD", "amount_minor": total_minor},
        "credit_price": None,
        "tax": {"currency": "USD", "amount_minor": 0},
        "total_price": {"currency": "USD", "amount_minor": total_minor},
        "expires_at": (now + timedelta(hours=1)).isoformat(),
    }


async def _seed_pending(
    db_session: AsyncSession,
    account: BillingAccount,
    *,
    kind: str = "topup",
    catalog_key: str = _TOPUP_KEY,
    quantity: int = 1,
    total_minor: int = 1_000,
    external_reference: str | None = "pay_seeded",
    created_at: datetime | None = None,
) -> PendingActivation:
    now = datetime.now(UTC)
    pending = PendingActivation(
        billing_account_id=account.id,
        activation_kind=kind,
        catalog_key=catalog_key,
        quantity=quantity,
        catalog_revision=billing_settings.catalog_version,
        credential_mode="byok",
        status="pending",
        external_reference=external_reference,
        external_price_id=_TOPUP_REF,
        quote=_quote_dict(catalog_key=catalog_key, total_minor=total_minor),
        idempotency_key=f"seeded-{uuid.uuid4().hex[:16]}",
        request_fingerprint=uuid.uuid4().hex * 2,
        expires_at=now + timedelta(hours=1),
        created_at=created_at or now,
    )
    db_session.add(pending)
    await db_session.commit()
    return pending


# --- POST /billing/subscriptions ---------------------------------------------
@pytest.mark.asyncio
async def test_base_purchase_is_202_pending_and_grants_nothing(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})
    provider = _FakeProvider(session_factory)
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "buyer@example.com")

    response = await client.post(
        "/api/v1/billing/subscriptions",
        json={
            "catalog_key": "tier_1",
            "credential_mode": "byok",
            "country_code": "us",
        },
        headers={"Idempotency-Key": "purchase-key-0001"},
    )
    assert response.status_code == 202
    body = response.json()
    assert body["kind"] == "base"
    assert body["catalog_key"] == "tier_1"
    assert body["status"] == "pending"
    assert body["checkout_url"] == "https://rzp.io/i/sub_fake"
    assert body["failure_code"] is None
    # The SERVER quote controls the charge and agrees with catalog pricing.
    quote = body["quote"]
    assert quote["catalog_key"] == "tier_1"
    assert quote["catalog_revision"] == billing_settings.catalog_version
    assert quote["credential_mode"] == "byok"
    assert quote["country_code"] == "US"
    assert quote["region"] == "international"
    assert quote["base_price"] == {"currency": "USD", "amount_minor": 9_900}
    assert quote["credit_price"] is None
    assert quote["total_price"] == {"currency": "USD", "amount_minor": 9_900}
    # The private provider ref reaches only the provider call, never the body.
    assert _PLAN_REF not in response.text
    assert provider.base_calls == [{"price_ref": _PLAN_REF, "trial_days": None}]

    # The intent path NEVER writes a grant, and the submitted ISO country is
    # locked on the account server-side (single writer now profile is gone).
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 0
    account = await _account(db_session)
    assert account.billing_country == "US"
    assert account.country_verification == "declared"


@pytest.mark.asyncio
async def test_base_purchase_rejects_a_deferred_trial_before_any_write(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})
    provider = _FakeProvider(session_factory)
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "trial@example.com")

    response = await client.post(
        "/api/v1/billing/subscriptions",
        json={
            "catalog_key": "tier_1",
            "credential_mode": "byok",
            "country_code": "US",
            "trial_requested": True,
        },
        headers={"Idempotency-Key": "trial-key-00001"},
    )
    assert response.status_code == 409
    assert "trial_unavailable" in response.text
    # BEFORE any quote/pending/provider/grant write.
    assert provider.base_calls == []
    assert await db_session.scalar(select(func.count(PendingActivation.id))) == 0
    assert await db_session.scalar(select(func.count(IdempotencyRecord.id))) == 0
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 0


@pytest.mark.asyncio
async def test_mutation_rejects_missing_malformed_key_and_browser_smuggling(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})
    await _register(client, "guards@example.com")
    payload = {
        "catalog_key": "tier_1",
        "credential_mode": "byok",
        "country_code": "US",
    }
    # Missing key.
    missing = await client.post("/api/v1/billing/subscriptions", json=payload)
    assert missing.status_code == 400
    assert "idempotency_key_required" in missing.text
    # Malformed (too short / whitespace).
    for bad in ("short", "has whitespace"):
        response = await client.post(
            "/api/v1/billing/subscriptions",
            json=payload,
            headers={"Idempotency-Key": bad},
        )
        assert response.status_code == 400
    # A browser cannot submit an amount/currency/provider reference.
    smuggled = await client.post(
        "/api/v1/billing/subscriptions",
        json={**payload, "amount_minor": 1, "currency": "EUR"},
        headers={"Idempotency-Key": "smuggle-key-001"},
    )
    assert smuggled.status_code == 422
    # country_code is REQUIRED on the base purchase.
    no_country = await client.post(
        "/api/v1/billing/subscriptions",
        json={"catalog_key": "tier_1", "credential_mode": "byok"},
        headers={"Idempotency-Key": "country-key-001"},
    )
    assert no_country.status_code == 422


@pytest.mark.asyncio
async def test_idempotency_replays_same_body_and_rejects_a_different_one(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})
    provider = _FakeProvider(session_factory)
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "replay@example.com")
    payload = {
        "catalog_key": "tier_1",
        "credential_mode": "byok",
        "country_code": "US",
    }
    headers = {"Idempotency-Key": "replay-key-0001"}
    first = await client.post(
        "/api/v1/billing/subscriptions", json=payload, headers=headers
    )
    assert first.status_code == 202
    # Same key + same body: byte-equivalent replay, no second provider call.
    replay = await client.post(
        "/api/v1/billing/subscriptions", json=payload, headers=headers
    )
    assert replay.status_code == 202
    assert replay.content == first.content
    assert len(provider.base_calls) == 1
    # Same key + DIFFERENT body: 409, even though the purchase is now live.
    conflict = await client.post(
        "/api/v1/billing/subscriptions",
        json={**payload, "catalog_key": "tier_2"},
        headers=headers,
    )
    assert conflict.status_code == 409
    assert "idempotency_key_reused" in conflict.text
    assert len(provider.base_calls) == 1
    assert await db_session.scalar(select(func.count(PendingActivation.id))) == 1


@pytest.mark.asyncio
async def test_uncertain_provider_error_returns_202_pending_then_replays(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A RETRYABLE provider error is an uncertain outcome: the intent was
    committed before the call, so the route returns a clean 202-pending (not
    a 500) and a same-key retry replays it without a second provider call.
    """
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})

    class _UncertainProvider(_FakeProvider):
        async def create_base_subscription(
            self, *, price_ref, intent_id, account_ref, trial_days, metadata
        ) -> HostedSubscription:
            await self._assert_pending_committed(intent_id)
            self.base_calls.append({"price_ref": price_ref, "trial_days": trial_days})
            raise BillingProviderError("provider_unavailable", retryable=True)

    provider = _UncertainProvider(session_factory)
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "uncertain@example.com")
    payload = {
        "catalog_key": "tier_1",
        "credential_mode": "byok",
        "country_code": "US",
    }
    headers = {"Idempotency-Key": "uncertain-key-01"}

    response = await client.post(
        "/api/v1/billing/subscriptions", json=payload, headers=headers
    )
    assert response.status_code == 202
    body = response.json()
    assert body["kind"] == "base"
    assert body["status"] == "pending"
    # No hosted reference was ever persisted: nothing safe to show yet.
    assert body["checkout_url"] is None
    assert body["failure_code"] is None

    # The uncertain outcome leaves the committed rows pending for
    # reconciliation (never failed, never a grant).
    pending = (await db_session.scalars(select(PendingActivation))).one()
    assert pending.status == "pending"
    record = (await db_session.scalars(select(IdempotencyRecord))).one()
    assert record.state == "started"
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 0

    # A same-key retry replays the pending projection — no second call.
    replay = await client.post(
        "/api/v1/billing/subscriptions", json=payload, headers=headers
    )
    assert replay.status_code == 202
    assert replay.json() == body
    assert len(provider.base_calls) == 1


@pytest.mark.asyncio
async def test_concurrent_same_key_requests_never_500_or_double_call(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two concurrent same-Idempotency-Key checkouts: one winner, one replayed
    response — never a 500 and never a second provider call.
    """
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})
    provider = _FakeProvider(session_factory)
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "race-api@example.com")
    payload = {
        "catalog_key": "tier_1",
        "credential_mode": "byok",
        "country_code": "US",
    }
    headers = {"Idempotency-Key": "race-key-api-0001"}

    async def _post() -> httpx.Response:
        return await client.post(
            "/api/v1/billing/subscriptions", json=payload, headers=headers
        )

    first, second = await asyncio.gather(_post(), _post())
    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["activation_id"] == second.json()["activation_id"]
    assert len(provider.base_calls) == 1
    assert await db_session.scalar(select(func.count(PendingActivation.id))) == 1
    assert await db_session.scalar(select(func.count(IdempotencyRecord.id))) == 1


@pytest.mark.asyncio
async def test_insert_race_loser_replays_the_winner(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Force both same-key intents past the replay check BEFORE either insert
    commits: the loser's commit trips the account-key unique, and it must
    replay the winner's committed intent instead of 500ing on IntegrityError.
    """
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})
    await _register(client, "race-domain@example.com")
    account_id = (await _account(db_session)).id
    intent = resolve_base_intent(
        catalog_key="tier_1",
        credential_mode="byok",
        country_code="US",
        at=datetime.now(UTC),
    )

    barrier = asyncio.Barrier(2)
    real_insert = idempotency_module._insert_intent

    async def _gated_insert(session: AsyncSession, **kwargs: object):
        # Both intents arrive here only AFTER both replay checks missed.
        await barrier.wait()
        return await real_insert(session, **kwargs)

    monkeypatch.setattr(idempotency_module, "_insert_intent", _gated_insert)

    calls = 0

    async def _provider_call(pending: PendingActivation) -> HostedSubscription:
        nonlocal calls
        calls += 1
        return HostedSubscription(
            external_subscription_id="sub_race",
            checkout_url="https://rzp.io/i/sub_race",
            status="created",
            price_ref=_PLAN_REF,
        )

    async def _run(session: AsyncSession) -> IntentResult:
        account = await session.get(BillingAccount, account_id)
        assert account is not None
        return await execute_intent(
            session,
            account=account,
            operation=OPERATION_SUBSCRIPTION_CREATE,
            intent=intent,
            idempotency_key="race-key-domain-1",
            provider_call=_provider_call,
            status_code=202,
        )

    async with (
        session_factory() as first_session,
        session_factory() as second_session,
    ):
        first, second = await asyncio.gather(_run(first_session), _run(second_session))

    # Exactly one winner ran the provider call; the loser replayed it.
    assert {first.replayed, second.replayed} == {False, True}
    assert calls == 1
    assert first.response.activation_id == second.response.activation_id
    assert first.response.status == second.response.status == "pending"
    assert first.response.quote == second.response.quote
    async with session_factory() as session:
        assert await session.scalar(select(func.count(PendingActivation.id))) == 1
        assert await session.scalar(select(func.count(IdempotencyRecord.id))) == 1


@pytest.mark.asyncio
async def test_insert_race_different_keys_loser_conflicts(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two concurrent DIFFERENT-key base intents both pass the replay check and
    the pre-insert guard: the one-pending-base partial unique makes exactly one
    winner, and the loser's commit maps to the SAME 409 code the guard returns
    — never a 500 and never a second provider call.
    """
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})
    await _register(client, "race-slot@example.com")
    account_id = (await _account(db_session)).id
    intent = resolve_base_intent(
        catalog_key="tier_1",
        credential_mode="byok",
        country_code="US",
        at=datetime.now(UTC),
    )

    barrier = asyncio.Barrier(2)
    real_insert = idempotency_module._insert_intent

    async def _gated_insert(session: AsyncSession, **kwargs: object):
        # Both intents arrive here only AFTER both replay checks missed.
        await barrier.wait()
        return await real_insert(session, **kwargs)

    monkeypatch.setattr(idempotency_module, "_insert_intent", _gated_insert)

    calls = 0

    async def _provider_call(pending: PendingActivation) -> HostedSubscription:
        nonlocal calls
        calls += 1
        return HostedSubscription(
            external_subscription_id="sub_slot_race",
            checkout_url="https://rzp.io/i/sub_slot_race",
            status="created",
            price_ref=_PLAN_REF,
        )

    async def _run(session: AsyncSession, key: str) -> IntentResult:
        account = await session.get(BillingAccount, account_id)
        assert account is not None
        return await execute_intent(
            session,
            account=account,
            operation=OPERATION_SUBSCRIPTION_CREATE,
            intent=intent,
            idempotency_key=key,
            provider_call=_provider_call,
            status_code=202,
        )

    async with (
        session_factory() as first_session,
        session_factory() as second_session,
    ):
        results = await asyncio.gather(
            _run(first_session, "slot-race-key-1"),
            _run(second_session, "slot-race-key-2"),
            return_exceptions=True,
        )

    winners = [result for result in results if isinstance(result, IntentResult)]
    losers = [result for result in results if isinstance(result, BillingConflictError)]
    assert len(winners) == 1
    assert len(losers) == 1
    assert str(losers[0]) == REASON_SUBSCRIPTION_PENDING
    assert calls == 1
    assert winners[0].response.status == "pending"
    async with session_factory() as session:
        assert await session.scalar(select(func.count(PendingActivation.id))) == 1
        assert await session.scalar(select(func.count(IdempotencyRecord.id))) == 1


@pytest.mark.asyncio
async def test_concurrent_different_key_base_posts_one_winner_one_conflict(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API level: two concurrent different-key base purchases — exactly one 202
    and one 409 ``subscription_pending``, one provider call, one pending row.
    """
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})
    provider = _FakeProvider(session_factory)
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "race-slot-api@example.com")
    payload = {
        "catalog_key": "tier_1",
        "credential_mode": "byok",
        "country_code": "US",
    }

    async def _post(key: str) -> httpx.Response:
        return await client.post(
            "/api/v1/billing/subscriptions",
            json=payload,
            headers={"Idempotency-Key": key},
        )

    first, second = await asyncio.gather(
        _post("slot-api-key-1"), _post("slot-api-key-2")
    )
    responses = sorted((first, second), key=lambda response: response.status_code)
    assert [response.status_code for response in responses] == [202, 409]
    assert responses[1].json()["detail"] == REASON_SUBSCRIPTION_PENDING
    assert len(provider.base_calls) == 1
    assert await db_session.scalar(select(func.count(PendingActivation.id))) == 1
    assert await db_session.scalar(select(func.count(IdempotencyRecord.id))) == 1


@pytest.mark.asyncio
async def test_same_key_replay_while_pending_still_replays(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression: the unsettled-slot guard runs AFTER the replay check, so a
    same-Idempotency-Key retry of a still-pending purchase replays the original
    response instead of 409ing on its own pending row.
    """
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})
    provider = _FakeProvider(session_factory)
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "replay-pending@example.com")
    payload = {
        "catalog_key": "tier_1",
        "credential_mode": "byok",
        "country_code": "US",
    }
    headers = {"Idempotency-Key": "replay-pending-1"}

    first = await client.post(
        "/api/v1/billing/subscriptions", json=payload, headers=headers
    )
    assert first.status_code == 202
    assert first.json()["status"] == "pending"

    replay = await client.post(
        "/api/v1/billing/subscriptions", json=payload, headers=headers
    )
    assert replay.status_code == 202
    assert replay.json() == first.json()
    assert len(provider.base_calls) == 1
    assert await db_session.scalar(select(func.count(PendingActivation.id))) == 1


@pytest.mark.asyncio
async def test_failed_pending_frees_the_base_slot(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal transition OUT of pending frees the one-base slot: an
    unsettled pending blocks a second different-key purchase with 409, and
    after it settles to failed a new different-key intent succeeds.
    """
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})
    provider = _FakeProvider(session_factory)
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "slot-lifecycle@example.com")
    payload = {
        "catalog_key": "tier_1",
        "credential_mode": "byok",
        "country_code": "US",
    }

    first = await client.post(
        "/api/v1/billing/subscriptions",
        json=payload,
        headers={"Idempotency-Key": "slot-key-0001"},
    )
    assert first.status_code == 202

    blocked = await client.post(
        "/api/v1/billing/subscriptions",
        json=payload,
        headers={"Idempotency-Key": "slot-key-0002"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == REASON_SUBSCRIPTION_PENDING
    assert len(provider.base_calls) == 1

    # Reconciliation-style terminal settle (abandoned follows the same path).
    pending = (await db_session.scalars(select(PendingActivation))).one()
    pending.status = "failed"
    pending.failed_at = datetime.now(UTC)
    await db_session.commit()

    # The provider issues a FRESH hosted reference for the retry (provider
    # references stay unique across every pending row, settled or not).
    provider.subscription_id = "sub_freed"
    retry = await client.post(
        "/api/v1/billing/subscriptions",
        json=payload,
        headers={"Idempotency-Key": "slot-key-0003"},
    )
    assert retry.status_code == 202
    assert retry.json()["activation_id"] != first.json()["activation_id"]
    assert len(provider.base_calls) == 2
    assert await db_session.scalar(select(func.count(PendingActivation.id))) == 2


@pytest.mark.asyncio
async def test_pending_addon_blocks_same_key_but_not_other_addons_or_topups(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The one-pending-addon slot is scoped by (account, catalog_key): an
    unsettled add-on blocks only a second different-key intent for the SAME
    key — a different add-on key and a repeatable top-up still go through.
    """
    monkeypatch.setattr(billing_settings, "addon_extra_project_usd_minor", 1_900)
    monkeypatch.setattr(billing_settings, "addon_extra_prompts_usd_minor", 2_900)
    monkeypatch.setattr(billing_settings, "topup_benchmark_credits_usd_minor", 1_000)
    monkeypatch.setattr(billing_settings, "topup_benchmark_credits_per_pack", 25)
    _enable_checkout(
        monkeypatch,
        {
            "addon_extra_project:international:base": "plan_addon_private",
            "addon_extra_prompts:international:base": "plan_prompts_private",
            f"{_TOPUP_KEY}:international:base": _TOPUP_REF,
        },
    )
    provider = _FakeProvider(session_factory, payment_id="pay_slot")
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "addon-slot@example.com")
    account = await _account(db_session)
    await _seed_live_base(db_session, account)

    first = await client.post(
        "/api/v1/billing/addons",
        json={"catalog_key": "addon_extra_project", "quantity": 1},
        headers={"Idempotency-Key": "addon-slot-001"},
    )
    assert first.status_code == 202

    # Same (account, catalog_key), different Idempotency-Key: 409 addon_pending.
    blocked = await client.post(
        "/api/v1/billing/addons",
        json={"catalog_key": "addon_extra_project", "quantity": 1},
        headers={"Idempotency-Key": "addon-slot-002"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"] == REASON_ADDON_PENDING
    assert len(provider.addon_calls) == 1

    # A DIFFERENT add-on catalog key is not blocked (fresh hosted reference).
    provider.subscription_id = "sub_addon_b"
    other = await client.post(
        "/api/v1/billing/addons",
        json={"catalog_key": "addon_extra_prompts", "quantity": 1},
        headers={"Idempotency-Key": "addon-slot-003"},
    )
    assert other.status_code == 202
    assert len(provider.addon_calls) == 2

    # Top-ups are intentionally repeatable and never slot-blocked.
    topup = await _purchase_topup(client, quantity=1, key="addon-slot-topup")
    assert topup.status_code == 202
    assert len(provider.payment_calls) == 1
    assert await db_session.scalar(select(func.count(PendingActivation.id))) == 3


@pytest.mark.asyncio
async def test_renewal_with_a_removed_catalog_key_logs_and_issues_nothing(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plan key the LIVE catalog no longer owns must not silently issue
    nothing while the provider keeps charging: the renewal logs the safe
    catalog fields and writes no grants.
    """
    monkeypatch.setattr(billing_settings, "razorpay_webhook_secret", SecretStr(_SECRET))
    await _register(client, "renew-removed@example.com")
    account = await _account(db_session)
    subscription = await _seed_live_base(db_session, account)
    subscription.catalog_key = "tier_removed"
    await db_session.commit()

    now = datetime.now(UTC)
    raw = _subscription_activation_payload(
        external_id="sub_live_base",
        intent_id=str(uuid.uuid4()),
        account_ref=str(account.id),
        updated_at=int(now.timestamp()),
        current_start=int(now.timestamp()),
        current_end=int((now + timedelta(days=30)).timestamp()),
    )
    with capture_log_messages("app.billing") as messages:
        response = await _post_webhook(
            client, raw, event_id=f"evt_{uuid.uuid4().hex[:12]}"
        )
    assert response.status_code == 204
    assert any("no grant specs" in message for message in messages)
    # Nothing was issued for the unresolvable key.
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 0


# --- Activation via the signed webhook ---------------------------------------
@pytest.mark.asyncio
async def test_subscription_webhook_activates_once_and_a_duplicate_grants_nothing(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})
    provider = _FakeProvider(session_factory, subscription_id="sub_activate")
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "activate@example.com")
    account = await _account(db_session)

    purchase = await client.post(
        "/api/v1/billing/subscriptions",
        json={
            "catalog_key": "tier_1",
            "credential_mode": "byok",
            "country_code": "US",
        },
        headers={"Idempotency-Key": "activate-key-001"},
    )
    assert purchase.status_code == 202
    activation_id = purchase.json()["activation_id"]

    now = datetime.now(UTC)
    start = int(now.timestamp())
    raw = _subscription_activation_payload(
        external_id="sub_activate",
        intent_id=activation_id,
        account_ref=str(account.id),
        updated_at=start,
        current_start=start,
        current_end=int((now + timedelta(days=30)).timestamp()),
    )
    first = await _post_webhook(client, raw, event_id="evt_act_1")
    assert first.status_code == 204

    db_session.expire_all()
    pending = await db_session.get(PendingActivation, uuid.UUID(activation_id))
    assert pending is not None
    assert pending.status == "activated"
    assert pending.settled_by == "webhook"
    assert pending.checkout_url is None
    subscription = (await db_session.scalars(select(BillingSubscription))).one()
    assert subscription.catalog_key == "tier_1"
    assert subscription.subscription_kind == "base"
    assert subscription.status == "active"
    assert subscription.external_subscription_id == "sub_activate"
    # The REAL tier_1 catalog bundle: 8 grants, one version bump for the event
    # plus one for the bundle.
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 8
    assert await _account_version(db_session) == 2

    # The account read now reports the subscription and the issued grants.
    entitlement = await client.get("/api/v1/billing/entitlement")
    assert entitlement.status_code == 200
    view = entitlement.json()
    assert view["status"] == "resolved"
    assert view["subscription"]["catalog_key"] == "tier_1"
    assert view["subscription"]["cancel_at_period_end"] is False
    assert len(view["grants"]) == 8
    assert "funded_execution_allowed" not in view

    # A redelivery under a NEW event id never duplicates the subscription or
    # the grant bundle.
    duplicate = await _post_webhook(client, raw, event_id="evt_act_2")
    assert duplicate.status_code == 204
    db_session.expire_all()
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 8
    assert await db_session.scalar(select(func.count(BillingSubscription.id))) == 1
    assert await db_session.scalar(select(func.count(BillingWebhookEvent.id))) == 2


@pytest.mark.asyncio
async def test_webhook_reconciliation_race_settles_exactly_once(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_checkout(monkeypatch, {"tier_1:international:base": _PLAN_REF})
    provider = _FakeProvider(session_factory, subscription_id="sub_race")
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "race@example.com")
    account = await _account(db_session)

    purchase = await client.post(
        "/api/v1/billing/subscriptions",
        json={
            "catalog_key": "tier_1",
            "credential_mode": "byok",
            "country_code": "US",
        },
        headers={"Idempotency-Key": "race-key-000001"},
    )
    assert purchase.status_code == 202
    pending_id = uuid.UUID(purchase.json()["activation_id"])

    now = datetime.now(UTC)
    record = ProviderSubscription(
        external_subscription_id="sub_race",
        status="active",
        current_start=int(now.timestamp()),
        current_end=int((now + timedelta(days=30)).timestamp()),
        updated_at=int(now.timestamp()),
        cancel_at_period_end=False,
        price_ref=_PLAN_REF,
        intent_id=str(pending_id),
        account_ref=str(account.id),
    )
    webhook_result = await activate_pending(
        db_session,
        pending_id=pending_id,
        provider_record=record,
        authority=ACTIVATION_AUTHORITY_WEBHOOK,
        authority_id="evt_race",
        at=now,
    )
    assert webhook_result.already_settled is False
    version_after_first = await _account_version(db_session)

    # The forced race: the SAME authoritative record arriving from the sweep
    # returns the existing result and increments NOTHING.
    sweep_result = await activate_pending(
        db_session,
        pending_id=pending_id,
        provider_record=record,
        authority=ACTIVATION_AUTHORITY_RECONCILIATION,
        authority_id=str(pending_id),
        at=now,
    )
    assert sweep_result.already_settled is True
    db_session.expire_all()
    assert await db_session.scalar(select(func.count(BillingSubscription.id))) == 1
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 8
    assert await _account_version(db_session) == version_after_first


# --- Top-ups ------------------------------------------------------------------
@pytest.mark.asyncio
async def _purchase_topup(
    client: httpx.AsyncClient,
    *,
    quantity: int = 2,
    key: str = "topup-key-00001",
) -> httpx.Response:
    return await client.post(
        "/api/v1/billing/topups",
        json={"catalog_key": _TOPUP_KEY, "quantity": quantity},
        headers={"Idempotency-Key": key},
    )


def _enable_topup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(billing_settings, "topup_benchmark_credits_usd_minor", 1_000)
    monkeypatch.setattr(billing_settings, "topup_benchmark_credits_per_pack", 25)
    _enable_checkout(monkeypatch, {f"{_TOPUP_KEY}:international:base": _TOPUP_REF})


@pytest.mark.asyncio
async def test_topup_requires_a_live_base_subscription(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_topup(monkeypatch)
    provider = _FakeProvider(session_factory)
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "topup-no-base@example.com")

    response = await _purchase_topup(client)
    assert response.status_code == 409
    assert "base_subscription_required" in response.text
    assert provider.payment_calls == []
    assert await db_session.scalar(select(func.count(PendingActivation.id))) == 0


@pytest.mark.asyncio
async def test_topup_activates_with_fixed_expiry_and_moving_effective_expiry(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_topup(monkeypatch)
    provider = _FakeProvider(session_factory, payment_id="pay_topup")
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "topup@example.com")
    account = await _account(db_session)
    base = await _seed_live_base(db_session, account, period_days=10)
    base_period_end = base.current_period_end

    purchase = await _purchase_topup(client, quantity=2)
    assert purchase.status_code == 202
    body = purchase.json()
    assert body["kind"] == "topup"
    assert body["status"] == "pending"
    # The server quote controls the provider charge: 2 packs x 1000 minor.
    assert body["quote"]["total_price"] == {"currency": "USD", "amount_minor": 2_000}
    assert provider.payment_calls == [{"amount_minor": 2_000, "currency": "USD"}]
    # Nothing is granted in the intent path.
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 0

    paid_at = int(datetime.now(UTC).timestamp())
    raw = _payment_payload(
        external_id="pay_topup",
        amount=2_000,
        paid_at=paid_at,
        intent_id=body["activation_id"],
        account_ref=str(account.id),
    )
    webhook = await _post_webhook(client, raw, event_id="evt_topup_1")
    assert webhook.status_code == 204

    db_session.expire_all()
    pending = await db_session.get(PendingActivation, uuid.UUID(body["activation_id"]))
    assert pending is not None
    assert pending.status == "activated"
    grant = (await db_session.scalars(select(AccountGrant))).one()
    assert grant.key == "benchmark_credits"
    assert grant.value == 50  # 25 per pack x 2 packs
    assert grant.source_kind == "topup"
    # The STORED expiry is the FIXED paid_at + 30 days.
    stored_until = datetime.fromtimestamp(paid_at, tz=UTC) + timedelta(days=30)
    assert grant.valid_until == stored_until
    assert grant.valid_from == datetime.fromtimestamp(paid_at, tz=UTC)

    # The API usage read reports the MOVING effective expiry: the current
    # subscription end (10 days out) wins over the stored fixed date.
    usage = await client.get("/api/v1/billing/usage")
    assert usage.status_code == 200
    items = {item["key"]: item for item in usage.json()["items"]}
    credits = items["benchmark_credits"]
    assert credits["limit_state"] == "finite"
    assert credits["allowance"] == 50
    assert credits["consumed"] == 0
    assert credits["remaining"] == 50
    grant_row = credits["grants"][0]
    effective = datetime.fromisoformat(grant_row["effective_valid_until"])
    assert effective == base_period_end

    # A duplicate payment webhook grants nothing twice.
    duplicate = await _post_webhook(client, raw, event_id="evt_topup_2")
    assert duplicate.status_code == 204
    db_session.expire_all()
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 1


@pytest.mark.asyncio
async def test_payment_with_a_mismatched_amount_is_rejected_and_grants_nothing(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _enable_topup(monkeypatch)
    provider = _FakeProvider(session_factory, payment_id="pay_mismatch")
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "mismatch@example.com")
    account = await _account(db_session)
    await _seed_live_base(db_session, account)

    purchase = await _purchase_topup(client, quantity=1)
    assert purchase.status_code == 202
    activation_id = purchase.json()["activation_id"]

    raw = _payment_payload(
        external_id="pay_mismatch",
        amount=999,  # the stored quote says 1_000
        paid_at=int(datetime.now(UTC).timestamp()),
        intent_id=activation_id,
        account_ref=str(account.id),
    )
    response = await _post_webhook(client, raw, event_id="evt_mismatch")
    assert response.status_code == 204
    db_session.expire_all()
    event = (await db_session.scalars(select(BillingWebhookEvent))).one()
    assert event.result_code == "rejected"
    pending = await db_session.get(PendingActivation, uuid.UUID(activation_id))
    assert pending is not None
    assert pending.status == "pending"
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 0


# --- Add-ons -------------------------------------------------------------------
@pytest.mark.asyncio
async def test_addon_activation_and_period_end_cancellation(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "addon_extra_project_usd_minor", 1_900)
    _enable_checkout(
        monkeypatch, {"addon_extra_project:international:base": "plan_addon_private"}
    )
    provider = _FakeProvider(session_factory, subscription_id="sub_addon")
    monkeypatch.setattr(billing_api, "get_billing_provider", lambda: provider)
    await _register(client, "addon@example.com")

    activate = await client.post(
        "/api/v1/billing/addons",
        json={"catalog_key": "addon_extra_project", "quantity": 3},
        headers={"Idempotency-Key": "addon-key-00001"},
    )
    assert activate.status_code == 202
    body = activate.json()
    assert body["kind"] == "addon"
    assert body["quantity"] == 3
    assert body["quote"]["total_price"] == {"currency": "USD", "amount_minor": 5_700}
    assert provider.addon_calls == [{"price_ref": "plan_addon_private", "quantity": 3}]
    assert "plan_addon_private" not in activate.text

    # Deleting an unknown add-on is a safe conflict.
    missing = await client.delete(
        "/api/v1/billing/addons/addon_extra_prompts",
        headers={"Idempotency-Key": "addon-del-00001"},
    )
    assert missing.status_code == 409
    assert "no_current_subscription" in missing.text


@pytest.mark.asyncio
async def test_addon_activation_refuses_unknown_keys_and_bad_quantities(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _enable_checkout(monkeypatch, {})
    await _register(client, "addon-guards@example.com")
    unknown = await client.post(
        "/api/v1/billing/addons",
        json={"catalog_key": "nope", "quantity": 1},
        headers={"Idempotency-Key": "addon-unknown-1"},
    )
    assert unknown.status_code == 409
    assert "catalog_key_unknown" in unknown.text
    zero = await client.post(
        "/api/v1/billing/addons",
        json={"catalog_key": "addon_extra_project", "quantity": 0},
        headers={"Idempotency-Key": "addon-zero-0001"},
    )
    assert zero.status_code == 422


# --- Reconciliation sweep -------------------------------------------------------
@pytest.mark.asyncio
async def test_reconciliation_settles_fails_and_abandons_from_provider_state(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "topup_benchmark_credits_per_pack", 25)
    monkeypatch.setattr(billing_settings, "razorpay_webhook_secret", SecretStr(_SECRET))
    await _register(client, "sweep@example.com")
    account = await _account(db_session)
    await _seed_live_base(db_session, account)
    now = datetime.now(UTC)
    stale = now - timedelta(minutes=10)
    paid_at = int(now.timestamp())

    settleable = await _seed_pending(
        db_session, account, external_reference="pay_settle", created_at=stale
    )
    failing = await _seed_pending(
        db_session, account, external_reference="pay_fail", created_at=stale
    )
    abandoned = await _seed_pending(
        db_session, account, external_reference=None, created_at=stale
    )
    settleable_id, failing_id, abandoned_id = settleable.id, failing.id, abandoned.id

    class _SweepProvider:
        async def fetch_payment(self, external_payment_id: str) -> ProviderPayment:
            status = "paid" if external_payment_id == "pay_settle" else "payment_failed"
            return ProviderPayment(
                external_payment_id=external_payment_id,
                status=status,
                amount_minor=1_000,
                currency="USD",
                updated_at=paid_at,
                paid_at=paid_at if status == "paid" else None,
                intent_id=str(settleable_id),
                account_ref=str(account.id),
            )

        async def fetch_subscription(self, external_subscription_id: str):
            raise BillingProviderError("provider_unavailable", retryable=True)

    summary = await reconcile_pending_activations(
        session_factory,
        _SweepProvider(),
        now=now,
        stale_after=timedelta(seconds=60),
        abandon_after=timedelta(minutes=5),
    )
    assert summary.claimed == 3
    assert summary.activated == 1
    assert summary.failed == 1
    assert summary.abandoned == 1
    assert summary.errors == 0

    db_session.expire_all()
    settled = await db_session.get(PendingActivation, settleable_id)
    assert settled is not None
    assert settled.status == "activated"
    assert settled.settled_by == "reconciliation"
    grant = (await db_session.scalars(select(AccountGrant))).one()
    assert grant.key == "benchmark_credits"
    assert grant.value == 25
    assert grant.valid_until == (
        datetime.fromtimestamp(paid_at, tz=UTC) + timedelta(days=30)
    )
    failed = await db_session.get(PendingActivation, failing_id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.failure_code == "payment_failed"
    gone = await db_session.get(PendingActivation, abandoned_id)
    assert gone is not None
    assert gone.status == "abandoned"
    assert gone.failure_code == "activation_expired"

    # A second sweep finds nothing pending: fully idempotent.
    again = await reconcile_pending_activations(
        session_factory,
        _SweepProvider(),
        now=now,
        stale_after=timedelta(seconds=60),
        abandon_after=timedelta(minutes=5),
    )
    assert again.claimed == 0
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 1


@pytest.mark.asyncio
async def test_reconciliation_leaves_retryable_errors_pending(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await _register(client, "sweep-retry@example.com")
    account = await _account(db_session)
    stale = datetime.now(UTC) - timedelta(minutes=10)
    pending = await _seed_pending(db_session, account, created_at=stale)
    pending_id = pending.id

    class _FlakyProvider:
        async def fetch_payment(self, external_payment_id: str) -> ProviderPayment:
            raise BillingProviderError("provider_unavailable", retryable=True)

        async def fetch_subscription(self, external_subscription_id: str):
            raise BillingProviderError("provider_unavailable", retryable=True)

    summary = await reconcile_pending_activations(
        session_factory,
        _FlakyProvider(),
        now=datetime.now(UTC),
        stale_after=timedelta(seconds=60),
    )
    assert summary.still_pending == 1
    assert summary.activated == 0
    db_session.expire_all()
    row = await db_session.get(PendingActivation, pending_id)
    assert row is not None
    assert row.status == "pending"


# --- Deleted legacy routes ------------------------------------------------------
@pytest.mark.asyncio
async def test_deleted_legacy_routes_return_404(client: httpx.AsyncClient) -> None:
    await _register(client, "legacy@example.com")
    for method, path in (
        ("GET", "/api/v1/billing/me"),
        ("PATCH", "/api/v1/billing/profile"),
        ("POST", "/api/v1/billing/checkout"),
        ("POST", "/api/v1/billing/cancel"),
        ("POST", "/api/v1/billing/manage"),
        ("GET", f"/api/v1/workspaces/{uuid.uuid4()}/entitlements"),
    ):
        response = await client.request(method, path)
        assert response.status_code == 404, (method, path, response.status_code)


# --- Contract locks --------------------------------------------------------------
@pytest.mark.asyncio
async def test_openapi_locks_activation_and_deletion_vocabularies(
    client: httpx.AsyncClient,
) -> None:
    schemas = (await client.get("/openapi.json")).json()["components"]["schemas"]
    assert schemas["ActivationResponse"]["properties"]["status"]["enum"] == [
        "pending",
        "activated",
        "failed",
        "abandoned",
    ]
    assert schemas["SubscriptionChangeResponse"]["properties"]["status"]["enum"] == [
        "cancellation_scheduled",
        "already_scheduled",
    ]
    # No old vocabulary leaks into any response schema.
    assert "CancelResponse" not in schemas
    for name in ("BillingEntitlementResponse", "BillingUsageResponse"):
        assert schemas[name]["additionalProperties"] is False
