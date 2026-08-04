from __future__ import annotations

import hashlib
import hmac
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from pydantic import BaseModel, SecretStr, ValidationError
from sqlalchemy.exc import IntegrityError

from app.connectors.billing.base import BillingProviderError, ProviderMetadata
from app.connectors.billing.razorpay import RazorpayBillingProvider
from app.core.config.billing import (
    ADDON_EXTRA_PROJECT,
    CURRENCY_MINOR_UNITS,
    REASON_ADDON_PENDING,
    REASON_CHECKOUT_UNAVAILABLE,
    REASON_CONTACT_ONLY,
    REASON_SUBSCRIPTION_PENDING,
    REGION_CURRENCIES,
    REGION_INDIA,
    REGION_INTERNATIONAL,
    TOPUP_BENCHMARK_CREDITS,
    GrantTemplate,
    billing_settings,
    commercial_catalog,
    plan_checkout_availability,
    plan_period_grant_specs,
    resolve_region,
    scale_grant_specs,
    topup_grant_specs,
)
from app.core.config.entitlements import (
    BENCHMARK_CADENCE_VALUES,
    COMING_SOON_PROVIDER_KEYS,
    HISTORY_WINDOW_VALUES,
    KEY_BENCHMARK_CADENCE,
    KEY_BENCHMARK_CREDITS,
    KEY_EXPORTS,
    KEY_FANOUT,
    KEY_HISTORY_WINDOW,
    KEY_MANUAL_RUNS_PER_DAY,
    KEY_MONITORED_URLS,
    KEY_PROJECT_SLOTS,
    KEY_PROMPT_SLOTS,
    KEY_PROVIDER_COPILOT,
    KEY_PULSE_CADENCE,
    PULSE_CADENCE_VALUES,
)
from app.core.config.provider_catalog import (
    ACTIVE_TRANSPORTS,
    MEASUREMENT_ROUTES,
    PUBLIC_PROVIDER_CATALOG,
    public_provider_routes,
)
from app.domain.auth import service as auth_service
from app.domain.billing import schemas as billing_schemas
from app.domain.billing.idempotency import (
    _PENDING_SLOT_REASONS,
    TrialUnavailableError,
    _violated_constraint_name,
    reject_deferred_trial,
    request_fingerprint,
    validate_idempotency_key,
)
from app.domain.billing.schemas import (
    BillingEntitlementResponse,
    GrantProvenanceResponse,
    MoneyResponse,
    SubscriptionCreateRequest,
    UsageItemResponse,
)
from app.domain.billing.service import (
    BillingConflictError,
    resolve_addon_intent,
    resolve_base_intent,
)
from app.domain.billing.webhooks import verify_razorpay_signature
from scripts.provision_razorpay_plans import (
    _validate_environment,
    _verify,
    catalog_refs,
)


def test_webhook_signature_uses_exact_raw_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "webhook-test-secret"
    monkeypatch.setattr(billing_settings, "razorpay_webhook_secret", SecretStr(secret))
    raw = b'{"event":"subscription.activated"}'
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    assert verify_razorpay_signature(raw, signature)
    assert not verify_razorpay_signature(raw + b"\n", signature)


@pytest.mark.asyncio
async def test_login_skips_billing_repair_when_bootstrap_is_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = SimpleNamespace(
        id="11111111-1111-4111-8111-111111111111",
        is_active=True,
        hashed_password="hash",
    )
    repair = AsyncMock()
    session = SimpleNamespace(commit=AsyncMock())
    monkeypatch.setattr(auth_service, "get_user_by_email", AsyncMock(return_value=user))
    monkeypatch.setattr(auth_service, "verify_password", lambda *_args: True)
    monkeypatch.setattr(
        auth_service, "ensure_personal_workspace", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(
        auth_service,
        "user_billing_bootstrap_complete",
        AsyncMock(return_value=True),
    )
    monkeypatch.setattr(auth_service, "ensure_user_billing", repair)
    monkeypatch.setattr(auth_service, "create_access_token", lambda _user_id: "token")

    result = await auth_service.authenticate_user(
        session, "user@example.com", "password"
    )

    assert result == ("token", user)
    repair.assert_not_awaited()
    session.commit.assert_not_awaited()


def _metadata() -> ProviderMetadata:
    return ProviderMetadata(
        intent_id="intent-1", account_ref="account-1", catalog_revision="commercial-v8"
    )


@pytest.mark.asyncio
async def test_razorpay_adapter_creates_hosted_subscription(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(
        billing_settings, "razorpay_key_secret", SecretStr("test-secret")
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/subscriptions"
        assert request.method == "POST"
        assert request.headers["authorization"].startswith("Basic ")
        body = request.content.decode()
        assert '"plan_id":"plan_test"' in body
        assert '"total_count":1200' in body
        assert "citeladder_intent_id" in body
        assert "test-secret" not in body
        return httpx.Response(
            200,
            json={
                "id": "sub_test",
                "status": "created",
                "plan_id": "plan_test",
                "short_url": "https://rzp.io/i/hosted-test",
            },
        )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler), base_url="https://api.razorpay.com"
    ) as client:
        provider = RazorpayBillingProvider(client=client)
        hosted = await provider.create_base_subscription(
            price_ref="plan_test",
            intent_id="intent-1",
            account_ref="account-1",
            trial_days=None,
            metadata=_metadata(),
        )
    assert hosted.external_subscription_id == "sub_test"
    assert hosted.checkout_url == "https://rzp.io/i/hosted-test"
    assert hosted.price_ref == "plan_test"


@pytest.mark.asyncio
async def test_razorpay_adapter_rejects_untrusted_checkout_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(
        billing_settings, "razorpay_key_secret", SecretStr("test-secret")
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        assert _request.method == "POST"
        return httpx.Response(
            200,
            json={
                "id": "sub_test",
                "status": "created",
                "plan_id": "plan_test",
                "short_url": "https://example.com/phishing",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RazorpayBillingProvider(client=client)
        with pytest.raises(BillingProviderError, match="provider_invalid_checkout_url"):
            await provider.create_base_subscription(
                price_ref="plan_test",
                intent_id="intent-1",
                account_ref="account-1",
                trial_days=None,
                metadata=_metadata(),
            )


@pytest.mark.asyncio
async def test_razorpay_fetch_subscription_echoes_intent_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(
        billing_settings, "razorpay_key_secret", SecretStr("test-secret")
    )
    requests: list[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "id": "sub_existing",
                "status": "active",
                "plan_id": "plan_test",
                "current_start": 1,
                "current_end": 2,
                "updated_at": 3,
                "cancel_at_cycle_end": 1,
                "notes": {
                    "citeladder_intent_id": "intent-1",
                    "citeladder_account_ref": "account-1",
                },
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RazorpayBillingProvider(client=client)
        record = await provider.fetch_subscription("sub_existing")
    assert record.external_subscription_id == "sub_existing"
    assert record.price_ref == "plan_test"
    # The opaque identity refs echoed from the metadata we sent are what the
    # activation transaction verifies before granting anything.
    assert record.intent_id == "intent-1"
    assert record.account_ref == "account-1"
    assert record.cancel_at_period_end is True
    assert [request.method for request in requests] == ["GET"]


@pytest.mark.asyncio
async def test_razorpay_adapter_rejects_an_echoed_price_ref_mismatch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(
        billing_settings, "razorpay_key_secret", SecretStr("test-secret")
    )

    async def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": "sub_test",
                "status": "created",
                "plan_id": "plan_other",
                "short_url": "https://rzp.io/i/hosted-test",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RazorpayBillingProvider(client=client)
        with pytest.raises(BillingProviderError, match="provider_price_ref_mismatch"):
            await provider.create_addon_subscription(
                price_ref="plan_test",
                quantity=2,
                intent_id="intent-1",
                account_ref="account-1",
                metadata=_metadata(),
            )


@pytest.mark.asyncio
async def test_razorpay_one_time_payment_validates_the_echoed_amount(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(
        billing_settings, "razorpay_key_secret", SecretStr("test-secret")
    )
    bodies: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(request.content.decode())
        amount = 1_000 if len(bodies) == 1 else 500
        return httpx.Response(
            200,
            json={
                "id": "plink_test",
                "status": "created",
                "amount": amount,
                "currency": "USD",
                "short_url": "https://rzp.io/i/pay-test",
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RazorpayBillingProvider(client=client)
        hosted = await provider.create_one_time_payment(
            amount_minor=1_000,
            currency="USD",
            intent_id="intent-1",
            account_ref="account-1",
            metadata=_metadata(),
        )
        assert hosted.external_payment_id == "plink_test"
        assert hosted.amount_minor == 1_000
        # The intent id is the provider-side reference; partial payments are
        # never accepted.
        assert '"reference_id":"intent-1"' in bodies[0]
        assert '"accept_partial":false' in bodies[0]
        with pytest.raises(BillingProviderError, match="provider_amount_mismatch"):
            await provider.create_one_time_payment(
                amount_minor=1_000,
                currency="USD",
                intent_id="intent-1",
                account_ref="account-1",
                metadata=_metadata(),
            )


@pytest.mark.asyncio
async def test_razorpay_adapter_maps_all_transport_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(billing_settings, "razorpay_key_id", "rzp_test_key")
    monkeypatch.setattr(
        billing_settings, "razorpay_key_secret", SecretStr("test-secret")
    )

    async def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ProtocolError("broken transport", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = RazorpayBillingProvider(client=client)
        with pytest.raises(BillingProviderError, match="provider_unavailable") as exc:
            await provider.create_base_subscription(
                price_ref="plan_test",
                intent_id="intent-1",
                account_ref="account-1",
                trial_days=None,
                metadata=_metadata(),
            )
    assert exc.value.retryable is True


@pytest.mark.parametrize(
    ("environment", "key_id", "valid"),
    [
        ("test", "rzp_test_example", True),
        ("live", "rzp_live_example", True),
        ("test", "rzp_live_example", False),
        ("live", "rzp_test_example", False),
    ],
)
def test_plan_provisioning_validates_credential_environment(
    monkeypatch: pytest.MonkeyPatch,
    environment: str,
    key_id: str,
    valid: bool,
) -> None:
    monkeypatch.setattr(billing_settings, "razorpay_key_id", key_id)
    if valid:
        _validate_environment(environment)
    else:
        with pytest.raises(RuntimeError, match="does not match"):
            _validate_environment(environment)


# --- v8 commercial catalog + strict DTOs -----------------------------------
def test_catalog_has_final_plan_keys_in_order_with_exact_defaults() -> None:
    catalog = commercial_catalog()
    assert [plan.key for plan in catalog.plans] == [
        "tier_1",
        "tier_2",
        "tier_3",
        "enterprise",
    ]
    base = {
        plan.key: plan.base_price(REGION_INTERNATIONAL) for plan in catalog.plans[:3]
    }
    assert [price.amount_minor for price in base.values()] == [9_900, 19_900, 29_900]
    assert {price.currency for price in base.values()} == {"USD"}
    enterprise = catalog.plans[3]
    assert enterprise.contact_only is True
    assert enterprise.self_serve is False
    assert enterprise.base_prices == {}
    assert enterprise.credit_prices_by_cadence == {}
    assert enterprise.grant_bundle == ()


def test_catalog_vocabulary_has_no_free_paid_or_bundle_tokens() -> None:
    catalog = commercial_catalog()
    text = " ".join(
        f"{plan.key} {plan.name} {plan.description}" for plan in catalog.plans
    ).lower()
    assert "free" not in text
    assert "paid" not in text
    assert "bundle" not in text


def test_plan_grant_templates_match_the_registry_and_omit_coming_soon() -> None:
    catalog = commercial_catalog()
    grants = {
        plan.key: {template.key: template.value for template in plan.grant_bundle}
        for plan in catalog.plans
    }
    assert grants["tier_1"] == {
        KEY_PULSE_CADENCE: PULSE_CADENCE_VALUES.index("daily"),
        KEY_BENCHMARK_CADENCE: BENCHMARK_CADENCE_VALUES.index("weekly"),
        KEY_PROJECT_SLOTS: 1,
        KEY_PROMPT_SLOTS: 10,
        KEY_MONITORED_URLS: 50,
        KEY_HISTORY_WINDOW: HISTORY_WINDOW_VALUES.index("90d"),
        KEY_MANUAL_RUNS_PER_DAY: 3,
        KEY_EXPORTS: 1,
    }
    assert grants["tier_2"][KEY_PROJECT_SLOTS] == 3
    assert grants["tier_2"][KEY_PROMPT_SLOTS] == 30
    assert grants["tier_2"][KEY_MONITORED_URLS] == 150
    assert grants["tier_2"][KEY_HISTORY_WINDOW] == HISTORY_WINDOW_VALUES.index("12mo")
    assert grants["tier_2"][KEY_MANUAL_RUNS_PER_DAY] == 6
    assert grants["tier_2"][KEY_FANOUT] == 1
    assert grants["tier_3"][KEY_PROJECT_SLOTS] == 10
    assert grants["tier_3"][KEY_PROMPT_SLOTS] == 60
    assert grants["tier_3"][KEY_MONITORED_URLS] == 400
    assert grants["tier_3"][KEY_HISTORY_WINDOW] == HISTORY_WINDOW_VALUES.index("24mo")
    assert grants["tier_3"][KEY_MANUAL_RUNS_PER_DAY] == 12
    # No plan issues a runnable coming-soon provider grant, and no plan carries
    # a benchmark-credit grant (included counts are unconfigured).
    for bundle in grants.values():
        assert not COMING_SOON_PROVIDER_KEYS & set(bundle)
        assert KEY_BENCHMARK_CREDITS not in bundle


def test_grant_template_rejects_non_issuable_and_unknown_keys() -> None:
    with pytest.raises(ValueError, match="non-issuable"):
        GrantTemplate(KEY_PROVIDER_COPILOT, 1)
    with pytest.raises(KeyError):
        GrantTemplate("not_a_capability", 1)


def test_base_and_credit_prices_stay_separate_and_funded_needs_a_margin(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tier_1 = commercial_catalog().plan("tier_1")
    assert tier_1 is not None
    # Funded margin UNSET: no credit price exists, so base is never derived
    # from (or confused with) a credit price.
    assert tier_1.credit_price(REGION_INTERNATIONAL) is None
    monkeypatch.setattr(billing_settings, "funded_margin_bps", 2_000)
    funded = commercial_catalog().plan("tier_1")
    assert funded is not None
    base = funded.base_price(REGION_INTERNATIONAL)
    credit = funded.credit_price(REGION_INTERNATIONAL)
    assert base is not None and credit is not None
    assert base.amount_minor == 9_900
    assert credit.amount_minor == 60_000
    assert base.amount_minor != credit.amount_minor


def test_items_are_unavailable_until_the_open_config_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = commercial_catalog()
    for addon in catalog.addons:
        assert addon.availability == "unavailable"
        assert addon.unavailable_reason == REASON_CHECKOUT_UNAVAILABLE
    topup = catalog.topups[0]
    assert topup.availability == "unavailable"
    assert topup.unavailable_reason == REASON_CHECKOUT_UNAVAILABLE
    assert topup.grant_bundle_per_unit == ()
    assert topup.expiry_days == 30
    # A configured price alone is not enough: the private provider ref must
    # also be present before anything becomes purchasable.
    monkeypatch.setattr(billing_settings, "addon_extra_project_usd_minor", 1_900)
    assert commercial_catalog().addons[0].availability == "unavailable"
    monkeypatch.setattr(
        billing_settings,
        "provider_price_refs",
        {f"{ADDON_EXTRA_PROJECT}:{REGION_INTERNATIONAL}:base": "ref_private"},
    )
    assert commercial_catalog().addons[0].availability == "available"


def test_plan_checkout_requires_a_private_ref_and_enabled_region(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tier_1 = commercial_catalog().plan("tier_1")
    assert tier_1 is not None
    assert plan_checkout_availability(tier_1, REGION_INTERNATIONAL) == (
        False,
        REASON_CHECKOUT_UNAVAILABLE,
    )
    enterprise = commercial_catalog().plan("enterprise")
    assert enterprise is not None
    assert plan_checkout_availability(enterprise, REGION_INTERNATIONAL) == (
        False,
        REASON_CONTACT_ONLY,
    )
    monkeypatch.setattr(billing_settings, "checkout_enabled", True)
    monkeypatch.setattr(billing_settings, "razorpay_live_ready", True)
    monkeypatch.setattr(billing_settings, "razorpay_international_ready", True)
    monkeypatch.setattr(
        billing_settings,
        "provider_price_refs",
        {f"tier_1:{REGION_INTERNATIONAL}:base": "ref_private"},
    )
    priced = commercial_catalog().plan("tier_1")
    assert priced is not None
    assert plan_checkout_availability(priced, REGION_INTERNATIONAL) == (True, None)


def test_region_and_currency_resolution_stays_server_side() -> None:
    assert resolve_region("in") == REGION_INDIA
    assert resolve_region("US") == REGION_INTERNATIONAL
    # No country = public preview only.
    assert resolve_region(None) == REGION_INTERNATIONAL
    assert REGION_CURRENCIES[REGION_INDIA] == "INR"
    assert CURRENCY_MINOR_UNITS["INR"] == 2


def test_india_price_is_zero_until_the_operator_sets_a_rate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tier_1 = commercial_catalog().plan("tier_1")
    assert tier_1 is not None
    india = tier_1.base_price(REGION_INDIA)
    assert india is not None
    assert india.currency == "INR"
    assert india.amount_minor == 0
    assert india.purchasable is False
    monkeypatch.setattr(billing_settings, "usd_inr_rate", Decimal("83"))
    rated = commercial_catalog().plan("tier_1")
    assert rated is not None
    priced = rated.base_price(REGION_INDIA)
    assert priced is not None
    assert priced.amount_minor == 9_900 * 83


def test_plan_period_grant_specs_reads_the_catalog_and_rejects_stale_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    specs = plan_period_grant_specs("tier_1", billing_settings.catalog_version)
    assert specs is not None
    assert dict(specs)[KEY_PROJECT_SLOTS] == 1
    assert plan_period_grant_specs("tier_1", "billing-v1") is None
    assert (
        plan_period_grant_specs("enterprise", billing_settings.catalog_version) is None
    )
    assert plan_period_grant_specs("nope", billing_settings.catalog_version) is None


def test_active_write_enums_stay_openai_anthropic_google_only() -> None:
    assert ACTIVE_TRANSPORTS == frozenset({"openai", "anthropic", "google"})
    assert set(MEASUREMENT_ROUTES) == {
        ("chatgpt", "pulse"),
        ("chatgpt", "benchmark"),
        ("claude", "pulse"),
        ("claude", "benchmark"),
        ("gemini", "pulse"),
        ("gemini", "benchmark"),
    }
    coming_soon = {"grok", "perplexity", "copilot"}
    assert not coming_soon & {engine for engine, _ in MEASUREMENT_ROUTES}
    assert not coming_soon & ACTIVE_TRANSPORTS
    for key in coming_soon:
        assert public_provider_routes(key) == ()


def test_public_provider_catalog_marks_coming_soon_providers_unavailable() -> None:
    entries = {entry.key: entry for entry in PUBLIC_PROVIDER_CATALOG}
    for key in ("grok", "perplexity", "copilot"):
        entry = entries[key]
        assert entry.availability == "unavailable"
        assert entry.unavailable_reason == "provider_unavailable"
        assert entry.adapter_shipped is False
    assert entries["copilot"].issuable is False
    assert entries["grok"].issuable is True
    assert entries["perplexity"].issuable is True


def test_no_dto_field_can_carry_a_provider_price_ref() -> None:
    forbidden = ("provider_price_ref", "external", "provider_plan", "payment_id")
    for name in billing_schemas.__all__:
        model = getattr(billing_schemas, name)
        if not isinstance(model, type) or not issubclass(model, BaseModel):
            continue
        for field in model.model_fields:
            assert not any(token in field for token in forbidden), (name, field)


def test_response_models_forbid_extra_fields() -> None:
    with pytest.raises(ValidationError):
        MoneyResponse(currency="USD", amount_minor=1, provider_price_ref="ref")
    with pytest.raises(ValidationError):
        MoneyResponse(currency="EUR", amount_minor=1)
    with pytest.raises(ValidationError):
        MoneyResponse(currency="USD", amount_minor=-1)


def test_usage_item_limit_state_nullability_is_explicit() -> None:
    base = {
        "key": KEY_BENCHMARK_CREDITS,
        "capability_type": "counter.consumable",
        "unit": "credits",
        "window_started_at": None,
        "resets_at": None,
        "earliest_expiry": None,
        "grants": [],
    }
    finite = UsageItemResponse(
        **base,
        limit_state="finite",
        allowance=10,
        consumed=2,
        reserved=1,
        remaining=7,
    )
    assert finite.grants == []
    with pytest.raises(ValidationError, match="finite"):
        UsageItemResponse(
            **base,
            limit_state="finite",
            allowance=None,
            consumed=2,
            reserved=1,
            remaining=7,
        )
    unlimited = UsageItemResponse(
        **base,
        limit_state="unlimited",
        allowance=None,
        consumed=4,
        reserved=0,
        remaining=None,
    )
    assert unlimited.consumed == 4
    with pytest.raises(ValidationError, match="unlimited"):
        UsageItemResponse(
            **base,
            limit_state="unlimited",
            allowance=None,
            consumed=None,
            reserved=0,
            remaining=None,
        )
    unknown = UsageItemResponse(
        **base,
        limit_state="unknown",
        allowance=None,
        consumed=None,
        reserved=None,
        remaining=None,
    )
    assert unknown.limit_state == "unknown"
    with pytest.raises(ValidationError, match="unknown"):
        UsageItemResponse(
            **base,
            limit_state="unknown",
            allowance=5,
            consumed=None,
            reserved=None,
            remaining=None,
        )


def test_entitlement_response_has_no_funded_execution_flag() -> None:
    assert "funded_execution_allowed" not in BillingEntitlementResponse.model_fields
    assert "source_ref" not in GrantProvenanceResponse.model_fields


def test_subscription_create_request_normalizes_and_bounds_the_country() -> None:
    request = SubscriptionCreateRequest(
        catalog_key="tier_1", credential_mode="byok", country_code=" in "
    )
    assert request.country_code == "IN"
    assert request.trial_requested is False
    with pytest.raises(ValidationError):
        SubscriptionCreateRequest(
            catalog_key="tier_1", credential_mode="byok", country_code="IND"
        )
    with pytest.raises(ValidationError):
        SubscriptionCreateRequest(
            catalog_key="enterprise", credential_mode="byok", country_code="US"
        )
    # A browser cannot submit an amount, a currency, or a provider reference.
    with pytest.raises(ValidationError):
        SubscriptionCreateRequest(
            catalog_key="tier_1",
            credential_mode="byok",
            country_code="US",
            amount_minor=1,
        )


# --- Idempotent intent: key validation, fingerprint, deferred trial --------
def test_validate_idempotency_key_requires_a_bounded_token() -> None:
    for bad in (None, "", "short", "has whitespace", "tab\tkey", "x" * 256):
        with pytest.raises(ValueError, match="idempotency_key_required"):
            validate_idempotency_key(bad)
    assert validate_idempotency_key("  abcdefgh  ") == "abcdefgh"
    assert validate_idempotency_key("x" * 255) == "x" * 255


def test_request_fingerprint_is_canonical_and_sensitive_to_the_body() -> None:
    account_id = uuid.uuid4()
    base = {
        "operation": "subscription.create",
        "account_id": account_id,
        "catalog_revision": "commercial-v8",
        "catalog_key": "tier_1",
        "quantity": 1,
        "credential_mode": "byok",
    }
    fingerprint = request_fingerprint(**base)
    assert fingerprint == request_fingerprint(**base)
    assert len(fingerprint) == 64
    for change in (
        {"catalog_key": "tier_2"},
        {"quantity": 2},
        {"credential_mode": "funded"},
        {"operation": "addon.activate"},
    ):
        assert request_fingerprint(**{**base, **change}) != fingerprint


def test_reject_deferred_trial_raises_before_any_write() -> None:
    reject_deferred_trial(False)
    with pytest.raises(TrialUnavailableError, match="trial_unavailable"):
        reject_deferred_trial(True)


class _UniqueViolation(Exception):
    """Minimal asyncpg/psycopg-shaped driver error (constraint_name carrier)."""

    def __init__(self, constraint_name: str) -> None:
        super().__init__(constraint_name)
        self.constraint_name = constraint_name


def test_pending_slot_violations_map_to_the_guard_reasons() -> None:
    """The different-key slot race surfaces the SAME safe 409 codes the
    pre-insert guards return; a same-key violation stays on the replay path.
    """
    assert REASON_SUBSCRIPTION_PENDING == "subscription_pending"
    assert REASON_ADDON_PENDING == "addon_pending"
    cases = (
        ("uq_pending_activation_one_pending_base", REASON_SUBSCRIPTION_PENDING),
        ("uq_pending_activation_one_pending_addon", REASON_ADDON_PENDING),
        ("uq_pending_activation_account_idempotency", None),
        ("uq_idempotency_record_account_key", None),
    )
    for constraint_name, expected in cases:
        violation = IntegrityError("INSERT", {}, _UniqueViolation(constraint_name))
        name = _violated_constraint_name(violation)
        assert name == constraint_name
        assert _PENDING_SLOT_REASONS.get(name or "") == expected


def test_violated_constraint_name_unwraps_the_driver_adapter() -> None:
    """SQLAlchemy's asyncpg dialect re-raises a fresh IntegrityError FROM the
    driver error, so the name must be recovered from the ``__cause__`` chain.
    """
    adapted = Exception("adapted IntegrityError")
    adapted.__cause__ = _UniqueViolation("uq_pending_activation_one_pending_addon")
    violation = IntegrityError("INSERT", {}, adapted)
    assert (
        _violated_constraint_name(violation)
        == "uq_pending_activation_one_pending_addon"
    )


# --- Server-resolved quotes -------------------------------------------------
def _enable_international_checkout(
    monkeypatch: pytest.MonkeyPatch, refs: dict[str, str]
) -> None:
    monkeypatch.setattr(billing_settings, "checkout_enabled", True)
    monkeypatch.setattr(billing_settings, "razorpay_live_ready", True)
    monkeypatch.setattr(billing_settings, "razorpay_international_ready", True)
    monkeypatch.setattr(billing_settings, "provider_price_refs", refs)


def test_resolve_base_intent_quote_matches_catalog_and_separates_credit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = {f"tier_1:{REGION_INTERNATIONAL}:base": "ref_private"}
    _enable_international_checkout(monkeypatch, refs)
    now = datetime.now(UTC)
    intent = resolve_base_intent(
        catalog_key="tier_1", credential_mode="byok", country_code=" us ", at=now
    )
    quote = intent.quote
    assert quote.catalog_key == "tier_1"
    assert quote.catalog_revision == billing_settings.catalog_version
    assert quote.credential_mode == "byok"
    assert quote.region == REGION_INTERNATIONAL
    assert quote.base_price.amount_minor == 9_900
    # BYOK: no credit price, and the total is the base alone (tax inclusive).
    assert quote.credit_price is None
    assert quote.tax.amount_minor == 0
    assert quote.total_price.amount_minor == 9_900
    # The private provider ref NEVER reaches the quote DTO.
    assert "ref_private" not in quote.model_dump_json()

    # Funded: the margin-configured credit price is separate; total = base +
    # credit, and base is never derived from credit.
    monkeypatch.setattr(billing_settings, "funded_margin_bps", 2_000)
    refs[f"tier_1:{REGION_INTERNATIONAL}:credit"] = "ref_credit"
    monkeypatch.setattr(billing_settings, "provider_price_refs", refs)
    funded = resolve_base_intent(
        catalog_key="tier_1", credential_mode="funded", country_code="US", at=now
    )
    assert funded.quote.credit_price is not None
    assert funded.quote.credit_price.amount_minor == 60_000
    assert funded.quote.base_price.amount_minor == 9_900
    assert funded.quote.total_price.amount_minor == 69_900


def test_resolve_base_intent_refuses_unknown_keys_and_unconfigured_funded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = {f"tier_1:{REGION_INTERNATIONAL}:base": "ref_private"}
    _enable_international_checkout(monkeypatch, refs)
    now = datetime.now(UTC)
    with pytest.raises(BillingConflictError, match="catalog_key_unknown"):
        resolve_base_intent(
            catalog_key="nope", credential_mode="byok", country_code="US", at=now
        )
    # Funded margin UNSET: funded checkout refuses rather than guessing.
    with pytest.raises(BillingConflictError, match="checkout_unavailable"):
        resolve_base_intent(
            catalog_key="tier_1", credential_mode="funded", country_code="US", at=now
        )
    # Checkout disabled at the operator level: nothing is purchasable.
    monkeypatch.setattr(billing_settings, "checkout_enabled", False)
    with pytest.raises(BillingConflictError, match="checkout_unavailable"):
        resolve_base_intent(
            catalog_key="tier_1", credential_mode="byok", country_code="US", at=now
        )


def test_resolve_quote_applies_india_gst_server_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = {f"tier_1:{REGION_INDIA}:base": "ref_private_in"}
    _enable_international_checkout(monkeypatch, refs)
    monkeypatch.setattr(billing_settings, "usd_inr_rate", Decimal("83"))
    intent = resolve_base_intent(
        catalog_key="tier_1",
        credential_mode="byok",
        country_code="IN",
        at=datetime.now(UTC),
    )
    quote = intent.quote
    assert quote.region == REGION_INDIA
    assert quote.base_price.currency == "INR"
    assert quote.base_price.amount_minor == 9_900 * 83
    # Exclusive India GST: 18% ON TOP, owned by config.
    assert quote.tax.amount_minor == int(round(9_900 * 83 * 0.18))
    assert quote.total_price.amount_minor == (
        quote.base_price.amount_minor + quote.tax.amount_minor
    )


def test_resolve_addon_intent_bounds_quantity_and_requires_availability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    refs = {f"{ADDON_EXTRA_PROJECT}:{REGION_INTERNATIONAL}:base": "ref_private"}
    _enable_international_checkout(monkeypatch, refs)
    now = datetime.now(UTC)
    with pytest.raises(BillingConflictError, match="checkout_unavailable"):
        # Unit price unset: the add-on stays unavailable.
        resolve_addon_intent(
            catalog_key=ADDON_EXTRA_PROJECT, quantity=1, country_code="US", at=now
        )
    monkeypatch.setattr(billing_settings, "addon_extra_project_usd_minor", 1_900)
    with pytest.raises(BillingConflictError, match="quantity_out_of_bounds"):
        resolve_addon_intent(
            catalog_key=ADDON_EXTRA_PROJECT, quantity=21, country_code="US", at=now
        )
    with pytest.raises(BillingConflictError, match="catalog_key_unknown"):
        resolve_addon_intent(catalog_key="nope", quantity=1, country_code="US", at=now)
    intent = resolve_addon_intent(
        catalog_key=ADDON_EXTRA_PROJECT, quantity=3, country_code="US", at=now
    )
    assert intent.quote.total_price.amount_minor == 3 * 1_900
    assert intent.quote.credential_mode == "byok"


def test_topup_grant_specs_scale_and_reject_stale_revisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Pack size UNSET: no grant template exists for the current revision.
    assert (
        topup_grant_specs(TOPUP_BENCHMARK_CREDITS, billing_settings.catalog_version)
        is None
    )
    monkeypatch.setattr(billing_settings, "topup_benchmark_credits_per_pack", 25)
    specs = topup_grant_specs(TOPUP_BENCHMARK_CREDITS, billing_settings.catalog_version)
    assert specs == ((KEY_BENCHMARK_CREDITS, 25),)
    assert scale_grant_specs(specs, 3) == ((KEY_BENCHMARK_CREDITS, 75),)
    with pytest.raises(ValueError, match=">= 1"):
        scale_grant_specs(specs, 0)
    # A stale revision never silently issues today's bundle.
    assert topup_grant_specs(TOPUP_BENCHMARK_CREDITS, "billing-v1") is None
    assert topup_grant_specs("nope", billing_settings.catalog_version) is None


# --- Provisioning CLI over the commercial catalog ---------------------------
def test_provision_script_reports_missing_and_configured_refs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = catalog_refs()
    # Only the three self-serve plans have a positive international price by
    # default (India is unrated, add-ons/top-ups are unpriced).
    assert {row.settings_key for row in rows} == {
        f"{key}:{REGION_INTERNATIONAL}:base" for key in ("tier_1", "tier_2", "tier_3")
    }
    assert all(not row.configured for row in rows)
    assert _verify(rows) == 1
    monkeypatch.setattr(
        billing_settings,
        "provider_price_refs",
        {row.settings_key: "ref_private" for row in rows},
    )
    configured = catalog_refs()
    assert all(row.configured for row in configured)
    assert _verify(configured) == 0
    # A configured funded margin surfaces the credit refs as their own rows.
    monkeypatch.setattr(billing_settings, "funded_margin_bps", 2_000)
    keys = {row.settings_key for row in catalog_refs()}
    assert f"tier_1:{REGION_INTERNATIONAL}:credit" in keys
