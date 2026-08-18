"""Razorpay Subscriptions + Payment Links adapter. Translation/transport only.

Every method takes only server-resolved arguments (a PRIVATE ``price_ref``
from config, an opaque intent id, an opaque account ref) and validates the
response shape, the hosted URL host, the echoed price ref, and the expected
amount/currency before the domain sees it. No commercial amount, catalog key,
status vocabulary, or tax rule is decided here — config owns all of it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.connectors.billing.base import (
    BillingProviderError,
    HostedPayment,
    HostedSubscription,
    ProviderMetadata,
    ProviderPayment,
    ProviderSubscription,
)
from app.core.config.billing_contracts import (
    RAZORPAY_PAYMENT_STATUS_MAP,
)
from app.core.config.billing_settings import (
    BillingSettings,
    billing_settings,
)

_SECONDS_PER_DAY = 86_400
_NOTE_INTENT = "citeladder_intent_id"
_NOTE_ACCOUNT = "citeladder_account_ref"


class RazorpayBillingProvider:
    def __init__(
        self,
        *,
        settings: BillingSettings = billing_settings,
        client: httpx.AsyncClient,
    ) -> None:
        self.settings = settings
        self._client = client

    def _auth(self) -> httpx.BasicAuth:
        key_id = self.settings.razorpay_key_id.strip()
        secret = self.settings.razorpay_key_secret.get_secret_value()
        if not key_id or not secret:
            raise BillingProviderError("provider_not_configured")
        return httpx.BasicAuth(key_id, secret)

    async def _request(
        self, method: str, path: str, *, payload: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        try:
            response = await self._client.request(
                method,
                f"{self.settings.razorpay_api_base_url.rstrip('/')}{path}",
                auth=self._auth(),
                json=payload,
                timeout=self.settings.request_timeout_seconds,
            )
        except httpx.TransportError as exc:
            raise BillingProviderError("provider_unavailable", retryable=True) from exc
        if response.status_code >= 400:
            code = (
                "provider_rejected"
                if response.status_code < 500
                else "provider_unavailable"
            )
            raise BillingProviderError(code, retryable=response.status_code >= 500)
        try:
            data = response.json()
        except ValueError as exc:
            raise BillingProviderError("provider_invalid_response") from exc
        if not isinstance(data, dict):
            raise BillingProviderError("provider_invalid_response")
        return data

    # --- response translation ---------------------------------------------
    def _subscription(self, data: dict[str, Any]) -> ProviderSubscription:
        external_id = data.get("id")
        status = data.get("status")
        if not isinstance(external_id, str) or not isinstance(status, str):
            raise BillingProviderError("provider_invalid_response")
        notes = _notes_map(data.get("notes"))
        return ProviderSubscription(
            external_subscription_id=external_id,
            status=status,
            current_start=_optional_int(data.get("current_start")),
            current_end=_optional_int(data.get("current_end")),
            updated_at=_optional_int(data.get("updated_at")) or 0,
            cancel_at_period_end=_provider_bool(data.get("cancel_at_cycle_end")),
            price_ref=_optional_str(data.get("plan_id")),
            intent_id=_optional_str(notes.get(_NOTE_INTENT)),
            account_ref=_optional_str(notes.get(_NOTE_ACCOUNT)),
        )

    def _validated_checkout_url(self, value: object) -> str:
        if not isinstance(value, str) or len(value) > 2048:
            raise BillingProviderError("provider_invalid_checkout_url")
        parsed = urlsplit(value)
        if (
            parsed.scheme.lower() != "https"
            or not parsed.hostname
            or parsed.hostname.lower() not in self.settings.checkout_hosts()
            or parsed.username
            or parsed.password
        ):
            raise BillingProviderError("provider_invalid_checkout_url")
        return value

    def _hosted_subscription(
        self, data: dict[str, Any], *, expected_price_ref: str
    ) -> HostedSubscription:
        subscription = self._subscription(data)
        _require_price_ref(subscription, expected_price_ref)
        return HostedSubscription(
            external_subscription_id=subscription.external_subscription_id,
            checkout_url=self._validated_checkout_url(data.get("short_url")),
            status=subscription.status,
            price_ref=subscription.price_ref,
        )

    def _payment(self, data: dict[str, Any]) -> ProviderPayment:
        external_id = data.get("id")
        status = data.get("status")
        amount = _optional_int(data.get("amount"))
        currency = data.get("currency")
        if (
            not isinstance(external_id, str)
            or not isinstance(status, str)
            or amount is None
            or not isinstance(currency, str)
        ):
            raise BillingProviderError("provider_invalid_response")
        if status not in RAZORPAY_PAYMENT_STATUS_MAP:
            raise BillingProviderError("provider_invalid_response")
        # Read once and narrow the result: calling ``get`` twice gives the type
        # checker no way to tie the isinstance check to the value being used.
        raw_notes = data.get("notes")
        notes = raw_notes if isinstance(raw_notes, dict) else {}
        return ProviderPayment(
            external_payment_id=external_id,
            status=RAZORPAY_PAYMENT_STATUS_MAP[status],
            amount_minor=amount,
            currency=currency.upper(),
            updated_at=_optional_int(data.get("updated_at")) or 0,
            paid_at=_optional_int(data.get("paid_at")),
            intent_id=_optional_str(notes.get(_NOTE_INTENT)),
            account_ref=_optional_str(notes.get(_NOTE_ACCOUNT)),
        )

    # --- protocol ---------------------------------------------------------
    async def create_base_subscription(
        self,
        *,
        price_ref: str,
        intent_id: str,
        account_ref: str,
        trial_days: int | None,
        metadata: ProviderMetadata,
    ) -> HostedSubscription:
        payload: dict[str, Any] = {
            "plan_id": price_ref,
            "total_count": self.settings.subscription_total_cycles,
            "customer_notify": 1,
            "notes": metadata.as_notes(),
        }
        if trial_days:
            # Trial checkout is DEFERRED: the caller never supplies days in
            # PR1, and the free-period translation is the provider's
            # ``start_at`` when it does.
            payload["start_at"] = int(
                datetime.now(UTC).timestamp() + trial_days * _SECONDS_PER_DAY
            )
        data = await self._request("POST", "/subscriptions", payload=payload)
        return self._hosted_subscription(data, expected_price_ref=price_ref)

    async def create_addon_subscription(
        self,
        *,
        price_ref: str,
        quantity: int,
        intent_id: str,
        account_ref: str,
        metadata: ProviderMetadata,
    ) -> HostedSubscription:
        data = await self._request(
            "POST",
            "/subscriptions",
            payload={
                "plan_id": price_ref,
                "quantity": quantity,
                "total_count": self.settings.subscription_total_cycles,
                "customer_notify": 1,
                "notes": metadata.as_notes(),
            },
        )
        return self._hosted_subscription(data, expected_price_ref=price_ref)

    async def fetch_subscription(
        self, external_subscription_id: str
    ) -> ProviderSubscription:
        return self._subscription(
            await self._request("GET", f"/subscriptions/{external_subscription_id}")
        )

    async def cancel_subscription(
        self, external_subscription_id: str, *, at_cycle_end: bool = True
    ) -> ProviderSubscription:
        return self._subscription(
            await self._request(
                "POST",
                f"/subscriptions/{external_subscription_id}/cancel",
                payload={"cancel_at_cycle_end": 1 if at_cycle_end else 0},
            )
        )

    async def create_one_time_payment(
        self,
        *,
        amount_minor: int,
        currency: str,
        intent_id: str,
        account_ref: str,
        metadata: ProviderMetadata,
    ) -> HostedPayment:
        data = await self._request(
            "POST",
            "/payment_links",
            payload={
                "amount": amount_minor,
                "currency": currency,
                "accept_partial": False,
                "reference_id": intent_id,
                "notes": metadata.as_notes(),
            },
        )
        payment = self._payment(data)
        if payment.amount_minor != amount_minor or payment.currency != currency.upper():
            raise BillingProviderError("provider_amount_mismatch")
        return HostedPayment(
            external_payment_id=payment.external_payment_id,
            checkout_url=self._validated_checkout_url(data.get("short_url")),
            status=payment.status,
            amount_minor=payment.amount_minor,
            currency=payment.currency,
        )

    async def fetch_payment(self, external_payment_id: str) -> ProviderPayment:
        return self._payment(
            await self._request("GET", f"/payment_links/{external_payment_id}")
        )


def _notes_map(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _require_price_ref(subscription: ProviderSubscription, expected: str) -> None:
    """Reject a hosted subscription whose echoed plan is not the one we named."""
    if subscription.price_ref != expected:
        raise BillingProviderError("provider_price_ref_mismatch")


def _optional_int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _optional_str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _provider_bool(value: object) -> bool:
    return value is True or value == 1
