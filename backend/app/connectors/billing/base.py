"""Provider-neutral billing DTOs, errors, and protocol.

The protocol is explicit and provider-neutral: every method names the
commercial operation it performs and takes only server-resolved arguments
(a PRIVATE ``price_ref`` from config, an opaque intent id, and an opaque
account ref). A browser value never reaches a provider call.

Provider DTOs carry the authoritative status, the amount/currency needed to
verify a payment, the provider update version, period bounds, and the
cancellation state. They deliberately carry NO payment-instrument
fingerprint in PR1 — that dependency is deferred with trial checkout.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


class BillingProviderError(RuntimeError):
    """A provider call failed.

    ``retryable`` marks an UNCERTAIN outcome (transport/5xx): the caller must
    leave the intent pending for reconciliation rather than failing it.
    """

    def __init__(self, code: str, *, retryable: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class HostedSubscription:
    """A created hosted subscription: the only safe fields we persist."""

    external_subscription_id: str
    checkout_url: str
    status: str
    price_ref: str = ""


@dataclass(frozen=True, slots=True)
class ProviderSubscription:
    """The provider's authoritative view of one subscription."""

    external_subscription_id: str
    status: str
    current_start: int | None
    current_end: int | None
    updated_at: int
    cancel_at_period_end: bool
    price_ref: str = ""
    # Opaque intent/account refs echoed back from the metadata we sent, used to
    # verify provider identity before any activation.
    intent_id: str = ""
    account_ref: str = ""


@dataclass(frozen=True, slots=True)
class HostedPayment:
    """A created hosted one-time payment awaiting the buyer."""

    external_payment_id: str
    checkout_url: str
    status: str
    amount_minor: int
    currency: str


@dataclass(frozen=True, slots=True)
class ProviderPayment:
    """The provider's authoritative view of one one-time payment."""

    external_payment_id: str
    status: str
    amount_minor: int
    currency: str
    updated_at: int
    paid_at: int | None = None
    intent_id: str = ""
    account_ref: str = ""


@dataclass(frozen=True, slots=True)
class ProviderMetadata:
    """Safe, opaque metadata attached to a provider object.

    Only opaque server ids are ever sent (invariant 6): no email, no prompt,
    no credential, no capability list.
    """

    intent_id: str
    account_ref: str
    catalog_revision: str
    extra: dict[str, str] = field(default_factory=dict)

    def as_notes(self) -> dict[str, str]:
        notes = {
            "citeladder_intent_id": self.intent_id,
            "citeladder_account_ref": self.account_ref,
            "citeladder_catalog_revision": self.catalog_revision,
        }
        notes.update(self.extra)
        return notes


class BillingProvider(Protocol):
    """The provider-neutral commercial surface the domain depends on."""

    async def create_base_subscription(
        self,
        *,
        price_ref: str,
        intent_id: str,
        account_ref: str,
        trial_days: int | None,
        metadata: ProviderMetadata,
    ) -> HostedSubscription: ...

    async def create_addon_subscription(
        self,
        *,
        price_ref: str,
        quantity: int,
        intent_id: str,
        account_ref: str,
        metadata: ProviderMetadata,
    ) -> HostedSubscription: ...

    async def cancel_subscription(
        self, external_subscription_id: str, *, at_cycle_end: bool = True
    ) -> ProviderSubscription: ...

    async def fetch_subscription(
        self, external_subscription_id: str
    ) -> ProviderSubscription: ...

    async def create_one_time_payment(
        self,
        *,
        amount_minor: int,
        currency: str,
        intent_id: str,
        account_ref: str,
        metadata: ProviderMetadata,
    ) -> HostedPayment: ...

    async def fetch_payment(self, external_payment_id: str) -> ProviderPayment: ...


__all__ = [
    "BillingProvider",
    "BillingProviderError",
    "HostedPayment",
    "HostedSubscription",
    "ProviderMetadata",
    "ProviderPayment",
    "ProviderSubscription",
]
