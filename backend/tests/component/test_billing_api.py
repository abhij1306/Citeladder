"""Component tests for the v8 billing surface: cancellation + Razorpay webhooks.

The v6 catalog/quote/checkout/workspace-entitlement routes are deleted; what
remains here is ``DELETE /billing/subscription`` and the signed webhook
ingress driving the lifecycle projector (``apply_subscription_state``): stale
rejection, the account ``entitlement_lifecycle_version`` bump per accepted
event, one idempotent period grant bundle (via the monkeypatched
``plan_period_grant_specs`` catalog seam), deterministic terminal revocations,
and the synchronous Site Health runtime re-projection. The commercial WRITE
path (subscriptions/add-ons/top-ups + activation) lives in
``test_billing_commercial.py``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import billing as billing_api
from app.connectors.billing.base import ProviderSubscription
from app.core.config.billing_settings import (
    billing_settings,
)
from app.core.config.entitlements import (
    GRANT_SOURCE_PLAN,
    KEY_MONITORED_URLS,
)
from app.models.billing import (
    AccountGrant,
    BillingAccount,
    BillingSubscription,
    BillingWebhookEvent,
    GrantRevocation,
)
from app.models.site_health.runtime import WorkspaceSiteHealthRuntime
from tests.component.auth_helpers import register_and_login as _register

_SECRET = "component-webhook-secret"


def _sign(raw: bytes) -> str:
    return hmac.new(_SECRET.encode(), raw, hashlib.sha256).hexdigest()


def _webhook_payload(
    *,
    external_id: str,
    status: str,
    updated_at: int,
    current_start: int | None = None,
    current_end: int | None = None,
    cancel_at_cycle_end: bool = False,
) -> bytes:
    entity: dict[str, object] = {
        "id": external_id,
        "status": status,
        "updated_at": updated_at,
    }
    if current_start is not None:
        entity["current_start"] = current_start
    if current_end is not None:
        entity["current_end"] = current_end
    if cancel_at_cycle_end:
        entity["cancel_at_cycle_end"] = True
    return json.dumps(
        {
            "event": f"subscription.{status if status != 'active' else 'activated'}",
            "created_at": updated_at,
            "payload": {"subscription": {"entity": entity}},
        },
        separators=(",", ":"),
    ).encode()


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


async def _seed_subscription(
    db_session: AsyncSession,
    account: BillingAccount,
    *,
    external_id: str,
    catalog_key: str = "tier_1",
    provider_state_version: int = 0,
) -> BillingSubscription:
    subscription = BillingSubscription(
        billing_account_id=account.id,
        external_subscription_id=external_id,
        external_price_id="plan_test",
        catalog_key=catalog_key,
        currency="USD",
        provider_state_version=provider_state_version,
    )
    db_session.add(subscription)
    await db_session.commit()
    return subscription


def _patch_catalog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bind the catalog seam to a one-key monitored_urls bundle."""
    monkeypatch.setattr(
        "app.domain.billing.service.plan_period_grant_specs",
        lambda catalog_key, catalog_revision: ((KEY_MONITORED_URLS, 50),),
    )


async def _account_version(db_session: AsyncSession) -> int:
    account = (await db_session.scalars(select(BillingAccount))).one()
    return account.entitlement_lifecycle_version


@pytest.mark.asyncio
async def test_webhook_rejects_invalid_signature(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/billing/webhooks/razorpay",
        content=b'{"event":"subscription.activated"}',
        headers={
            "X-Razorpay-Signature": "invalid",
            "X-Razorpay-Event-Id": "evt_invalid",
            "Content-Type": "application/json",
        },
    )
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_signed_unmatched_webhook_is_acknowledged_and_grants_nothing(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "razorpay_webhook_secret", SecretStr(_SECRET))
    raw = json.dumps(
        {
            "event": "payment.captured",
            "created_at": 1,
            "payload": {
                "payment": {
                    "entity": {
                        "id": "pay_unmatched",
                        "status": "captured",
                        "amount": 100,
                        "currency": "USD",
                        "created_at": 1,
                    }
                }
            },
        },
        separators=(",", ":"),
    ).encode()
    response = await _post_webhook(client, raw, event_id="evt_unmatched")
    assert response.status_code == 204
    # A valid but unmatched event is recorded safely and grants NOTHING.
    event = (await db_session.scalars(select(BillingWebhookEvent))).one()
    assert event.result_code == "unmatched"
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 0


@pytest.mark.asyncio
async def test_activation_issues_one_period_bundle_and_projects_runtime(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "razorpay_webhook_secret", SecretStr(_SECRET))
    _patch_catalog(monkeypatch)
    await _register(client, "billing-activate@example.com")
    account = (await db_session.scalars(select(BillingAccount))).one()
    subscription = await _seed_subscription(
        db_session, account, external_id="sub_activation"
    )
    subscription_id = subscription.id
    workspace = (await client.get("/api/v1/workspaces")).json()[0]

    now = datetime.now(UTC)
    start = int(now.timestamp())
    end = int((now + timedelta(days=30)).timestamp())
    raw = _webhook_payload(
        external_id="sub_activation",
        status="active",
        updated_at=start,
        current_start=start,
        current_end=end,
    )
    first = await _post_webhook(client, raw, event_id="evt_activation_1")
    assert first.status_code == 204

    db_session.expire_all()
    # Accepted event bump (+1) plus one logical grant bundle bump (+1).
    assert await _account_version(db_session) == 2
    grants = (await db_session.scalars(select(AccountGrant))).all()
    assert len(grants) == 1
    grant = grants[0]
    assert grant.key == KEY_MONITORED_URLS
    assert grant.value == 50
    assert grant.source_kind == GRANT_SOURCE_PLAN
    assert grant.source_ref == f"subscription:{subscription_id}"
    period_start_iso = datetime.fromtimestamp(start, tz=UTC).isoformat()
    assert grant.idempotency_key == (
        f"sub:{subscription_id}:{period_start_iso}:{billing_settings.catalog_version}"
    )
    assert grant.period_end is not None

    # The subscription projected the active state + period fields.
    db_session.expire_all()
    persisted_sub = await db_session.get(BillingSubscription, subscription_id)
    assert persisted_sub is not None
    assert persisted_sub.status == "active"
    assert persisted_sub.is_current is True

    # Synchronous Site Health re-projection: the linked workspace's runtime
    # row carries the new allowance without any lazy read.
    runtime = await db_session.scalar(
        select(WorkspaceSiteHealthRuntime).where(
            WorkspaceSiteHealthRuntime.workspace_id == uuid.UUID(workspace["id"])
        )
    )
    assert runtime is not None
    assert runtime.monitored_url_limit == 50
    assert runtime.count_disclosure is True

    # A redelivery under a NEW event id (provider retry after an ack loss)
    # re-accepts (event bump only) but never duplicates the bundle.
    retry = await _post_webhook(client, raw, event_id="evt_activation_2")
    assert retry.status_code == 204
    db_session.expire_all()
    assert await _account_version(db_session) == 3
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 1
    assert await db_session.scalar(select(func.count(BillingWebhookEvent.id))) == 2


@pytest.mark.asyncio
async def test_stale_event_is_rejected_without_a_version_bump(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "razorpay_webhook_secret", SecretStr(_SECRET))
    _patch_catalog(monkeypatch)
    await _register(client, "billing-stale@example.com")
    account = (await db_session.scalars(select(BillingAccount))).one()
    await _seed_subscription(
        db_session,
        account,
        external_id="sub_stale",
        provider_state_version=1_000,
    )

    raw = _webhook_payload(
        external_id="sub_stale",
        status="active",
        updated_at=500,  # older than the persisted provider state version
        current_start=500,
        current_end=500 + 30 * 86400,
    )
    response = await _post_webhook(client, raw, event_id="evt_stale_1")
    assert response.status_code == 204

    db_session.expire_all()
    assert await _account_version(db_session) == 0
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 0
    event = (await db_session.scalars(select(BillingWebhookEvent))).one()
    assert event.result_code == "stale"


@pytest.mark.asyncio
async def test_immediate_terminal_loss_revokes_with_deterministic_idempotency(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "razorpay_webhook_secret", SecretStr(_SECRET))
    _patch_catalog(monkeypatch)
    await _register(client, "billing-terminal@example.com")
    account = (await db_session.scalars(select(BillingAccount))).one()
    subscription = await _seed_subscription(
        db_session, account, external_id="sub_terminal"
    )
    subscription_id = subscription.id

    now = datetime.now(UTC)
    start = int(now.timestamp())
    activate = _webhook_payload(
        external_id="sub_terminal",
        status="active",
        updated_at=start,
        current_start=start,
        current_end=int((now + timedelta(days=30)).timestamp()),
    )
    response = await _post_webhook(client, activate, event_id="evt_term_act")
    assert response.status_code == 204

    # Cancelled with NO future period end: immediate terminal loss.
    cancelled_at = start + 100
    cancel = _webhook_payload(
        external_id="sub_terminal",
        status="cancelled",
        updated_at=cancelled_at,
    )
    response = await _post_webhook(client, cancel, event_id="evt_term_cxl")
    assert response.status_code == 204

    db_session.expire_all()
    # Activation (2) + terminal event bump (+1) + revocation write bump (+1).
    assert await _account_version(db_session) == 4
    persisted_sub = await db_session.get(BillingSubscription, subscription_id)
    assert persisted_sub is not None
    assert persisted_sub.status == "cancelled"
    assert persisted_sub.is_current is False
    assert persisted_sub.ended_at is not None
    revocations = (await db_session.scalars(select(GrantRevocation))).all()
    assert len(revocations) == 1
    assert revocations[0].idempotency_key == (
        f"sub:{subscription_id}:terminal:{cancelled_at}"
    )
    assert revocations[0].reason == "subscription_ended"

    # The lost allowance re-projected the workspace runtime row to zero.
    assert (
        await db_session.scalar(
            select(func.count(WorkspaceSiteHealthRuntime.id)).where(
                WorkspaceSiteHealthRuntime.monitored_url_limit == 0
            )
        )
        == 1
    )

    # A redelivered terminal webhook (same logical event, new event id) hits
    # the deterministic idempotency key: no second revocation row.
    replay = await _post_webhook(client, cancel, event_id="evt_term_cxl_2")
    assert replay.status_code == 204
    db_session.expire_all()
    assert await db_session.scalar(select(func.count(GrantRevocation.id))) == 1
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 1


@pytest.mark.asyncio
async def test_cancel_at_period_end_keeps_access_and_writes_no_revocations(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "razorpay_webhook_secret", SecretStr(_SECRET))
    _patch_catalog(monkeypatch)
    await _register(client, "billing-cape@example.com")
    account = (await db_session.scalars(select(BillingAccount))).one()
    subscription = await _seed_subscription(db_session, account, external_id="sub_cape")
    subscription_id = subscription.id

    now = datetime.now(UTC)
    start = int(now.timestamp())
    end = int((now + timedelta(days=30)).timestamp())
    activate = _webhook_payload(
        external_id="sub_cape",
        status="active",
        updated_at=start,
        current_start=start,
        current_end=end,
    )
    response = await _post_webhook(client, activate, event_id="evt_cape_act")
    assert response.status_code == 204

    # Same period, now flagged cancel-at-cycle-end: access runs to the
    # natural period end, so no revocations and no new bundle.
    cancel = _webhook_payload(
        external_id="sub_cape",
        status="cancelled",
        updated_at=start + 100,
        current_start=start,
        current_end=end,
        cancel_at_cycle_end=True,
    )
    response = await _post_webhook(client, cancel, event_id="evt_cape_cxl")
    assert response.status_code == 204

    db_session.expire_all()
    persisted_sub = await db_session.get(BillingSubscription, subscription_id)
    assert persisted_sub is not None
    assert persisted_sub.is_current is True
    assert persisted_sub.ended_at is None
    # Accepted event bump only: the bundle replayed (same period key) and
    # nothing was revoked.
    assert await _account_version(db_session) == 3
    assert await db_session.scalar(select(func.count(AccountGrant.id))) == 1
    assert await db_session.scalar(select(func.count(GrantRevocation.id))) == 0


@pytest.mark.asyncio
async def test_delete_subscription_requires_an_idempotency_key(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "billing-delete-nokey@example.com")
    response = await client.delete("/api/v1/billing/subscription")
    assert response.status_code == 400
    assert "idempotency_key_required" in response.text


@pytest.mark.asyncio
async def test_cancel_without_subscription_is_conflict(
    client: httpx.AsyncClient,
) -> None:
    await _register(client, "billing-cancel-empty@example.com")
    response = await client.delete(
        "/api/v1/billing/subscription", headers={"Idempotency-Key": "cancel-key-1"}
    )
    assert response.status_code == 409
    assert "no_current_subscription" in response.text


@pytest.mark.asyncio
async def test_cancel_marks_cancel_at_period_end(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _register(client, "billing-cancel@example.com")
    account = (await db_session.scalars(select(BillingAccount))).one()
    now = datetime.now(UTC)
    subscription = BillingSubscription(
        billing_account_id=account.id,
        external_subscription_id="sub_cancel_me",
        external_price_id="plan_test",
        catalog_key="tier_1",
        currency="USD",
        status="active",
        current_period_start=now,
        current_period_end=now + timedelta(days=30),
    )
    db_session.add(subscription)
    await db_session.commit()
    subscription_id = subscription.id

    calls: list[bool] = []

    class FakeProvider:
        async def cancel_subscription(
            self, external_subscription_id: str, *, at_cycle_end: bool
        ) -> ProviderSubscription:
            assert external_subscription_id == "sub_cancel_me"
            calls.append(at_cycle_end)
            return ProviderSubscription(
                external_subscription_id=external_subscription_id,
                status="active",
                current_start=int(now.timestamp()),
                current_end=int((now + timedelta(days=30)).timestamp()),
                updated_at=int(now.timestamp()),
                cancel_at_period_end=True,
            )

    monkeypatch.setattr(billing_api, "get_billing_provider", FakeProvider)
    response = await client.delete(
        "/api/v1/billing/subscription", headers={"Idempotency-Key": "cancel-key-2"}
    )

    assert response.status_code == 200
    body = response.json()
    # The deletion vocabulary is SubscriptionChangeResponse, deliberately NOT
    # an activation: no pending/activated/failed/abandoned tokens.
    assert body["catalog_key"] == "tier_1"
    assert body["status"] == "cancellation_scheduled"
    assert "cancel_at_period_end" not in body
    assert calls == [True]

    db_session.expire_all()
    persisted_sub = await db_session.get(BillingSubscription, subscription_id)
    assert persisted_sub is not None
    assert persisted_sub.cancel_at_period_end is True
    # Two bumps: the accepted lifecycle projection, plus the tier_1 period
    # bundle the config-owned catalog now issues on a cancel-scheduled event.
    # Cancel-at-period-end still never revokes.
    assert await _account_version(db_session) == 2
    assert await db_session.scalar(select(func.count(GrantRevocation.id))) == 0

    # Cancelling again reports already_scheduled with NO second provider call.
    again = await client.delete(
        "/api/v1/billing/subscription", headers={"Idempotency-Key": "cancel-key-3"}
    )
    assert again.status_code == 200
    assert again.json()["status"] == "already_scheduled"
    assert calls == [True]


# --- Public catalog route --------------------------------------------------
@pytest.mark.asyncio
async def test_public_catalog_needs_no_auth_and_previews_without_a_country(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/billing/catalog")
    assert response.status_code == 200
    body = response.json()
    assert body["catalog_revision"] == billing_settings.catalog_version
    # No country supplied: null country, config-owned international preview.
    assert body["country_code"] is None
    assert body["region"] == "international"
    assert body["currency"] == "USD"
    assert body["currency_minor_units"] == 2
    assert [plan["key"] for plan in body["plans"]] == [
        "tier_1",
        "tier_2",
        "tier_3",
        "enterprise",
    ]
    # Lists are always present and may be empty, never null.
    for key in ("plans", "addons", "topups", "providers"):
        assert isinstance(body[key], list)
    # No workspace state and no private provider reference anywhere.
    raw = response.text
    for token in (
        "provider_price_ref",
        "workspace_id",
        "connection",
        "latest_probe",
        "api_key",
    ):
        assert token not in raw


@pytest.mark.asyncio
async def test_public_catalog_resolves_india_region_server_side(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/api/v1/billing/catalog", params={"country": "in"})
    assert response.status_code == 200
    body = response.json()
    assert body["country_code"] == "IN"
    assert body["region"] == "india"
    assert body["currency"] == "INR"
    # No operator FX rate configured, so the INR amount is 0 (never guessed)
    # and checkout is unavailable.
    tier_1 = body["plans"][0]
    assert tier_1["base_price"] == {"currency": "INR", "amount_minor": 0}
    assert tier_1["checkout_available"] is False
    assert tier_1["unavailable_reason"] == "checkout_unavailable"


@pytest.mark.asyncio
async def test_public_catalog_plan_rows_separate_base_and_credit_prices(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/api/v1/billing/catalog")).json()
    plans = {plan["key"]: plan for plan in body["plans"]}
    assert [
        plans[key]["base_price"]["amount_minor"]
        for key in ("tier_1", "tier_2", "tier_3")
    ] == [9_900, 19_900, 29_900]
    for key in ("tier_1", "tier_2", "tier_3"):
        plan = plans[key]
        # Funded margin unset: no credit price and therefore no funded total.
        assert plan["credit_price"] is None
        assert plan["funded_total_price"] is None
        assert plan["trial_availability"] == "unavailable"
        assert plan["trial_unavailable_reason"] == "trial_unavailable"
        assert plan["trial_days"] == billing_settings.trial_days
        assert plan["contact_url"] is None
    enterprise = plans["enterprise"]
    assert enterprise["contact_only"] is True
    assert enterprise["self_serve"] is False
    assert enterprise["base_price"] is None
    assert enterprise["credit_price"] is None
    assert enterprise["checkout_available"] is False
    assert enterprise["unavailable_reason"] == "contact_only"
    assert enterprise["contact_url"] == billing_settings.contact_sales_url
    # Upper tiers show the coming-soon provider rows with no granted value.
    tier_2_rows = {row["key"]: row for row in plans["tier_2"]["capabilities"]}
    for key in ("provider.grok", "provider.perplexity", "provider.copilot"):
        assert tier_2_rows[key]["value"] is None
    assert tier_2_rows["provider.copilot"]["issuable"] is False
    assert "provider.grok" not in {
        row["key"] for row in plans["tier_1"]["capabilities"]
    }


@pytest.mark.asyncio
async def test_public_catalog_reports_unset_addons_and_topups_as_unavailable(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/api/v1/billing/catalog")).json()
    for addon in body["addons"]:
        assert addon["availability"] == "unavailable"
        assert addon["unavailable_reason"] == "checkout_unavailable"
        assert addon["cadence"] == "monthly"
        assert addon["quantity_min"] == 1
        assert addon["quantity_max"] >= addon["quantity_min"]
    topup = body["topups"][0]
    assert topup["availability"] == "unavailable"
    assert topup["unavailable_reason"] == "checkout_unavailable"
    assert topup["grant_key"] == "audit_credits"
    # Pack size unset: credits_per_unit is null, expiry copy is still present.
    assert topup["credits_per_unit"] is None
    assert topup["expiry_days"] == billing_settings.topup_credit_valid_days


@pytest.mark.asyncio
async def test_public_provider_rows_mark_coming_soon_engines_unavailable(
    client: httpx.AsyncClient,
) -> None:
    body = (await client.get("/api/v1/billing/catalog")).json()
    providers = {row["key"]: row for row in body["providers"]}
    for key in ("grok", "perplexity", "copilot"):
        row = providers[key]
        assert row["availability"] == "unavailable"
        assert row["unavailable_reason"] == "provider_unavailable"
        assert row["adapter_shipped"] is False
        assert row["grant_key"] == f"provider.{key}"
        assert row["routes"] == []
    assert providers["copilot"]["issuable"] is False
    assert providers["grok"]["issuable"] is True
    # Shipped engines carry both exact mode-specific routes.
    assert providers["chatgpt"]["availability"] == "available"
    assert providers["chatgpt"]["routes"] == [
        {
            "logical_engine": "chatgpt",
            "transport_provider": "openai",
            "model": "gpt-5.4-nano-2026-03-17",
        },
        {
            "logical_engine": "chatgpt",
            "transport_provider": "openai",
            "model": "gpt-5.6-sol",
        },
    ]
    # Public availability vocabulary only — never a connection state.
    assert {row["availability"] for row in body["providers"]} <= {
        "available",
        "unavailable",
    }


@pytest.mark.asyncio
async def test_public_catalog_openapi_locks_the_final_plan_literals(
    client: httpx.AsyncClient,
) -> None:
    schemas = (await client.get("/openapi.json")).json()["components"]["schemas"]
    assert schemas["CatalogPlanResponse"]["properties"]["key"]["enum"] == [
        "tier_1",
        "tier_2",
        "tier_3",
        "enterprise",
    ]
    assert schemas["BillingCatalogResponse"]["additionalProperties"] is False
