from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class BillingSettings(BaseSettings):
    """Environment-owned billing catalog and Razorpay integration settings."""

    _backend_dir = Path(__file__).resolve().parents[3]
    model_config = SettingsConfigDict(
        env_prefix="BILLING_",
        env_file=(str(_backend_dir.parent / ".env"), str(_backend_dir / ".env")),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # The v8 commercial catalog revision. Stamped on every quote, activation,
    # and grant bundle; bump it whenever a price, key, or grant template
    # changes so old rows keep their frozen terms.
    catalog_version: str = "commercial-v8"
    checkout_enabled: bool = False
    razorpay_live_ready: bool = False
    razorpay_international_ready: bool = False

    # India price is frozen when an item is provisioned from this
    # operator-owned rate. Zero deliberately means "route unavailable", never a
    # guessed rate.
    usd_inr_rate: Decimal = Decimal("0")
    india_gst_rate: Decimal = Decimal("0.18")

    # --- Commercial catalog (open config) --------------------------------
    # PRIVATE provider price/plan references, keyed
    # ``"{catalog_key}:{region}:{purpose}"`` (invariant 6: never in a DTO). An
    # ABSENT ref makes the item unavailable rather than failing at purchase.
    provider_price_refs: dict[str, str] = {}

    # Where a contact-only plan sends the buyer (display metadata, no price).
    contact_sales_url: str = "/demo"

    # Funded admission budget (minor USD units). The SOLE commercial amount
    # kept here; expected execution costs live in ``config/costs.py``.
    funded_monthly_budget_minor: int = 50_000
    # Funded margin over the budget, in basis points. NULL/UNSET keeps funded
    # credit pricing (and therefore funded checkout) unavailable — a margin is
    # never guessed.
    funded_margin_bps: int | None = None

    # Add-on unit prices in minor USD units. Zero means "not yet priced", which
    # renders the add-on unavailable.
    addon_extra_project_usd_minor: int = 0
    addon_extra_prompts_usd_minor: int = 0

    # Top-up pack price + pack size. Both UNSET: the pack size is NULLABLE and
    # a top-up without a configured size issues no grant and stays
    # unavailable. Included benchmark credits and benchmark repetitions are
    # likewise unset and carry no default.
    topup_benchmark_credits_usd_minor: int = 0
    topup_benchmark_credits_per_pack: int | None = None
    included_benchmark_credits: int | None = None
    benchmark_repetitions: int | None = None
    # Fixed validity of a purchased top-up grant, in days.
    topup_credit_valid_days: int = 30

    # DEFERRED trial terms. Retained only as future catalog copy and as
    # grant-algebra/API fixtures: they never enable checkout (the catalog
    # reports trial_availability='unavailable' unconditionally).
    trial_days: int = 7
    trial_max_executions: int = 30

    razorpay_key_id: str = ""
    razorpay_key_secret: SecretStr = SecretStr("")
    razorpay_webhook_secret: SecretStr = SecretStr("")
    razorpay_api_base_url: str = "https://api.razorpay.com/v1"
    razorpay_checkout_hosts: str = "rzp.io,razorpay.com"
    request_timeout_seconds: float = 15.0
    http_max_connections: int = 20
    http_max_keepalive_connections: int = 10
    http_keepalive_expiry_seconds: float = 60.0
    checkout_expiry_minutes: int = 60
    # Validity of a server-resolved quote and of the pending activation that
    # stores it. A pending row older than this is eligible for abandonment.
    quote_validity_minutes: int = 60
    # Server-side digest secret for ``quote_id``. Empty falls back to the
    # webhook secret so a quote is never signed with a client-visible value.
    quote_signing_secret: SecretStr = SecretStr("")
    # Reconciliation sweep bounds (invariant 8: bounded SKIP LOCKED claims).
    reconciliation_batch_size: int = 50
    # A pending row is only probed once it has had this long to settle.
    reconciliation_stale_after_seconds: int = 300
    # After this long with no provider record, a pending row is abandoned.
    reconciliation_abandon_after_seconds: int = 86_400
    reconciliation_list_count: int = 100
    reconciliation_lookback_seconds: int = 86_400
    subscription_total_cycles: int = 1200
    past_due_grace_days: int = 3
    max_webhook_body_bytes: int = 262_144

    def checkout_hosts(self) -> frozenset[str]:
        return frozenset(
            host.strip().lower()
            for host in self.razorpay_checkout_hosts.split(",")
            if host.strip()
        )


billing_settings = BillingSettings()
