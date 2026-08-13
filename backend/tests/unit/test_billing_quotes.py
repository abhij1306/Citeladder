"""Server-resolved commercial quote and provisioning contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.core.config.billing import (
    ADDON_EXTRA_PROJECT,
    REGION_INDIA,
    REGION_INTERNATIONAL,
    TOPUP_BENCHMARK_CREDITS,
    billing_settings,
    scale_grant_specs,
    topup_grant_specs,
)
from app.core.config.entitlements import KEY_BENCHMARK_CREDITS
from app.domain.billing.service import (
    BillingConflictError,
    resolve_addon_intent,
    resolve_base_intent,
)
from scripts.provision_razorpay_plans import _verify, catalog_refs


def _enable_checkout(monkeypatch, refs) -> None:
    for name, value in (
        ("checkout_enabled", True),
        ("razorpay_live_ready", True),
        ("razorpay_international_ready", True),
        ("provider_price_refs", refs),
    ):
        monkeypatch.setattr(billing_settings, name, value)


def test_base_quote_separates_byok_and_funded_prices(monkeypatch) -> None:
    refs = {f"tier_1:{REGION_INTERNATIONAL}:base": "ref_private"}
    _enable_checkout(monkeypatch, refs)
    now = datetime.now(UTC)
    quote = resolve_base_intent(
        catalog_key="tier_1", credential_mode="byok", country_code=" us ", at=now
    ).quote
    assert (
        quote.catalog_key,
        quote.catalog_revision,
        quote.credential_mode,
        quote.region,
    ) == ("tier_1", billing_settings.catalog_version, "byok", REGION_INTERNATIONAL)
    assert (
        quote.base_price.amount_minor,
        quote.credit_price,
        quote.tax.amount_minor,
        quote.total_price.amount_minor,
    ) == (9_900, None, 0, 9_900)
    assert "ref_private" not in quote.model_dump_json()
    monkeypatch.setattr(billing_settings, "funded_margin_bps", 2_000)
    monkeypatch.setattr(
        billing_settings,
        "provider_price_refs",
        {**refs, f"tier_1:{REGION_INTERNATIONAL}:credit": "ref_credit"},
    )
    funded = resolve_base_intent(
        catalog_key="tier_1", credential_mode="funded", country_code="US", at=now
    ).quote
    assert (
        funded.credit_price.amount_minor,
        funded.base_price.amount_minor,
        funded.total_price.amount_minor,
    ) == (60_000, 9_900, 69_900)


def test_base_quote_refuses_unknown_or_unavailable_checkout(monkeypatch) -> None:
    _enable_checkout(
        monkeypatch, {f"tier_1:{REGION_INTERNATIONAL}:base": "ref_private"}
    )
    now = datetime.now(UTC)
    for kwargs, error in (
        ({"catalog_key": "nope", "credential_mode": "byok"}, "catalog_key_unknown"),
        (
            {"catalog_key": "tier_1", "credential_mode": "funded"},
            "checkout_unavailable",
        ),
    ):
        with pytest.raises(BillingConflictError, match=error):
            resolve_base_intent(**kwargs, country_code="US", at=now)
    monkeypatch.setattr(billing_settings, "checkout_enabled", False)
    with pytest.raises(BillingConflictError, match="checkout_unavailable"):
        resolve_base_intent(
            catalog_key="tier_1", credential_mode="byok", country_code="US", at=now
        )


def test_india_quote_applies_configured_gst(monkeypatch) -> None:
    _enable_checkout(monkeypatch, {f"tier_1:{REGION_INDIA}:base": "ref_private_in"})
    monkeypatch.setattr(billing_settings, "usd_inr_rate", Decimal("83"))
    quote = resolve_base_intent(
        catalog_key="tier_1",
        credential_mode="byok",
        country_code="IN",
        at=datetime.now(UTC),
    ).quote
    assert (quote.region, quote.base_price.currency, quote.base_price.amount_minor) == (
        REGION_INDIA,
        "INR",
        9_900 * 83,
    )
    assert (
        quote.total_price.amount_minor
        == quote.base_price.amount_minor + quote.tax.amount_minor
        == 9_900 * 83 + int(round(9_900 * 83 * 0.18))
    )


def test_addon_quote_bounds_quantity_and_availability(monkeypatch) -> None:
    _enable_checkout(
        monkeypatch,
        {f"{ADDON_EXTRA_PROJECT}:{REGION_INTERNATIONAL}:base": "ref_private"},
    )
    now = datetime.now(UTC)
    for key, quantity, error in (
        (ADDON_EXTRA_PROJECT, 1, "checkout_unavailable"),
        ("nope", 1, "catalog_key_unknown"),
    ):
        with pytest.raises(BillingConflictError, match=error):
            resolve_addon_intent(
                catalog_key=key, quantity=quantity, country_code="US", at=now
            )
    monkeypatch.setattr(billing_settings, "addon_extra_project_usd_minor", 1_900)
    with pytest.raises(BillingConflictError, match="quantity_out_of_bounds"):
        resolve_addon_intent(
            catalog_key=ADDON_EXTRA_PROJECT, quantity=21, country_code="US", at=now
        )
    quote = resolve_addon_intent(
        catalog_key=ADDON_EXTRA_PROJECT, quantity=3, country_code="US", at=now
    ).quote
    assert (quote.total_price.amount_minor, quote.credential_mode) == (
        3 * 1_900,
        "byok",
    )


def test_topup_specs_and_provisioning_refs(monkeypatch) -> None:
    version = billing_settings.catalog_version
    assert topup_grant_specs(TOPUP_BENCHMARK_CREDITS, version) is None
    monkeypatch.setattr(billing_settings, "topup_benchmark_credits_per_pack", 25)
    specs = topup_grant_specs(TOPUP_BENCHMARK_CREDITS, version)
    assert specs == ((KEY_BENCHMARK_CREDITS, 25),)
    assert scale_grant_specs(specs, 3) == ((KEY_BENCHMARK_CREDITS, 75),)
    with pytest.raises(ValueError, match=">= 1"):
        scale_grant_specs(specs, 0)
    assert (
        topup_grant_specs(TOPUP_BENCHMARK_CREDITS, "billing-v1")
        is topup_grant_specs("nope", version)
        is None
    )
    rows = catalog_refs()
    assert {row.settings_key for row in rows} == {
        f"{key}:{REGION_INTERNATIONAL}:base" for key in ("tier_1", "tier_2", "tier_3")
    }
    assert all(not row.configured for row in rows) and _verify(rows) == 1
    monkeypatch.setattr(
        billing_settings,
        "provider_price_refs",
        {row.settings_key: "ref_private" for row in rows},
    )
    assert (
        all(row.configured for row in catalog_refs()) and _verify(catalog_refs()) == 0
    )
    monkeypatch.setattr(billing_settings, "funded_margin_bps", 2_000)
    assert f"tier_1:{REGION_INTERNATIONAL}:credit" in {
        row.settings_key for row in catalog_refs()
    }
