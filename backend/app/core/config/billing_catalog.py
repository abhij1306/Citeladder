from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal

from app.core.config.billing_contracts import (
    ADDON_EXTRA_PROJECT,
    ADDON_EXTRA_PROJECT_SLOTS_PER_UNIT,
    ADDON_EXTRA_PROMPTS,
    ADDON_EXTRA_PROMPTS_SLOTS_PER_UNIT,
    ADDON_QUANTITY_MAX,
    ADDON_QUANTITY_MIN,
    CADENCE_CUSTOM,
    CADENCE_MONTHLY,
    CURRENCY_INR,
    CURRENCY_MINOR_UNITS,
    CURRENCY_USD,
    INDIA_COUNTRY_CODE,
    PLAN_ENTERPRISE,
    PLAN_KEYS,
    PLAN_TIER_1,
    PLAN_TIER_2,
    PLAN_TIER_3,
    PREVIEW_REGION,
    PRICE_PURPOSE_BASE,
    PRICE_PURPOSE_CREDIT,
    REASON_CHECKOUT_UNAVAILABLE,
    REASON_CONTACT_ONLY,
    REASON_TRIAL_UNAVAILABLE,
    REGION_INDIA,
    REGION_INTERNATIONAL,
    TAX_BEHAVIOR_EXCLUSIVE,
    TAX_BEHAVIOR_INCLUSIVE,
    TAX_BEHAVIORS,
    TIER_1_BASE_USD_MINOR,
    TIER_2_BASE_USD_MINOR,
    TIER_3_BASE_USD_MINOR,
    TOPUP_AUDIT_CREDITS,
    TOPUP_QUANTITY_MAX,
    TOPUP_QUANTITY_MIN,
)
from app.core.config.billing_settings import billing_settings
from app.core.config.entitlements import (
    CAPABILITY_REGISTRY,
    KEY_AUDIT_CADENCE,
    KEY_AUDIT_CREDITS,
    KEY_EXPORTS,
    KEY_FANOUT,
    KEY_HISTORY_WINDOW,
    KEY_MANUAL_RUNS_PER_DAY,
    KEY_MONITORED_URLS,
    KEY_PROJECT_SLOTS,
    KEY_PROMPT_SLOTS,
)
from app.core.config.provider_catalog import (
    AVAILABILITY_AVAILABLE,
    AVAILABILITY_UNAVAILABLE,
    PUBLIC_PROVIDER_CATALOG,
    ProviderCatalogEntry,
    validate_availability,
)


@dataclass(frozen=True, slots=True)
class CatalogPrice:
    """One configured price for one region.

    ``provider_price_ref`` is PRIVATE (invariant 6): it is the operator-owned
    external price/plan reference and must never appear in a response DTO. An
    ABSENT ref makes the owning item unavailable — a missing ref is never
    guessed and never replaced by a client-supplied value.
    """

    currency: str
    amount_minor: int
    tax_behavior: str
    provider_price_ref: str

    def __post_init__(self) -> None:
        if self.currency not in CURRENCY_MINOR_UNITS:
            raise ValueError(f"unsupported catalog currency: {self.currency!r}")
        if self.amount_minor < 0:
            raise ValueError("catalog price amount_minor must be >= 0")
        if self.tax_behavior not in TAX_BEHAVIORS:
            raise ValueError(f"unsupported tax behavior: {self.tax_behavior!r}")

    @property
    def purchasable(self) -> bool:
        """True only when a positive amount AND a private ref are configured."""
        return self.amount_minor > 0 and bool(self.provider_price_ref.strip())


@dataclass(frozen=True, slots=True)
class GrantTemplate:
    """One capability key/value a catalog item's grant bundle issues.

    ``key`` must be an ISSUABLE entitlement-registry capability: the registry
    owns the vocabulary (invariant 2) and Copilot can never be templated.
    """

    key: str
    value: int

    def __post_init__(self) -> None:
        definition = CAPABILITY_REGISTRY.require(self.key)
        if not definition.issuable:
            raise ValueError(f"capability {self.key!r} is non-issuable")
        if self.value < 0:
            raise ValueError(f"grant template {self.key!r} must be >= 0")


@dataclass(frozen=True, slots=True)
class QuantityBounds:
    """Inclusive purchase quantity bounds for an add-on or top-up."""

    minimum: int
    maximum: int

    def __post_init__(self) -> None:
        if self.minimum < 1 or self.maximum < self.minimum:
            raise ValueError("quantity bounds must satisfy 1 <= minimum <= maximum")


@dataclass(frozen=True, slots=True)
class PlanCatalogEntry:
    """One base plan.

    ``base_prices`` and ``credit_prices_by_cadence`` are keyed by region (and
    cadence for credits). ``base_price`` and ``credit_price`` stay SEPARATE: the
    funded total is ``base + credit``. Provider cost is never exposed and base
    is never derived from credit. Enterprise carries no price, no provider ref,
    and no grants.
    """

    key: str
    name: str
    description: str
    cadence: str
    base_prices: Mapping[str, CatalogPrice]
    credit_prices_by_cadence: Mapping[str, Mapping[str, CatalogPrice]]
    grant_bundle: tuple[GrantTemplate, ...]
    trial_availability: str
    trial_unavailable_reason: str | None
    self_serve: bool
    contact_only: bool

    def __post_init__(self) -> None:
        if self.key not in PLAN_KEYS:
            raise ValueError(f"unknown plan key: {self.key!r}")
        if self.contact_only and (
            self.self_serve
            or self.base_prices
            or self.credit_prices_by_cadence
            or self.grant_bundle
        ):
            raise ValueError(
                f"contact-only plan {self.key!r} must carry no prices or grants"
            )
        validate_availability(self.trial_availability, self.trial_unavailable_reason)

    def base_price(self, region: str) -> CatalogPrice | None:
        return self.base_prices.get(region)

    def credit_price(self, region: str) -> CatalogPrice | None:
        """Funded credit price for this plan's cadence in a region (or None)."""
        return self.credit_prices_by_cadence.get(self.cadence, {}).get(region)


@dataclass(frozen=True, slots=True)
class AddonCatalogEntry:
    """One recurring add-on, priced per unit and granting per unit."""

    key: str
    name: str
    description: str
    cadence: str
    quantity_bounds: QuantityBounds
    prices: Mapping[str, CatalogPrice]
    grant_bundle_per_unit: tuple[GrantTemplate, ...]
    availability: str
    unavailable_reason: str | None

    def __post_init__(self) -> None:
        validate_availability(self.availability, self.unavailable_reason)

    def price(self, region: str) -> CatalogPrice | None:
        return self.prices.get(region)


@dataclass(frozen=True, slots=True)
class TopupCatalogEntry:
    """One one-time credit pack. ``expiry_days`` is the fixed grant validity."""

    key: str
    name: str
    description: str
    quantity_bounds: QuantityBounds
    prices: Mapping[str, CatalogPrice]
    grant_bundle_per_unit: tuple[GrantTemplate, ...]
    availability: str
    unavailable_reason: str | None
    expiry_days: int

    def __post_init__(self) -> None:
        validate_availability(self.availability, self.unavailable_reason)
        if self.expiry_days <= 0:
            raise ValueError("top-up expiry_days must be positive")

    def price(self, region: str) -> CatalogPrice | None:
        return self.prices.get(region)


@dataclass(frozen=True, slots=True)
class CommercialCatalog:
    """The whole resolved commercial catalog for one revision.

    Immutable and rebuilt from settings by ``commercial_catalog()``: an
    operator adding a private provider ref or an FX rate changes availability
    without any code change (invariant 1).
    """

    revision: str
    plans: tuple[PlanCatalogEntry, ...]
    addons: tuple[AddonCatalogEntry, ...]
    topups: tuple[TopupCatalogEntry, ...]
    providers: tuple[ProviderCatalogEntry, ...]

    def plan(self, key: str) -> PlanCatalogEntry | None:
        for entry in self.plans:
            if entry.key == key:
                return entry
        return None

    def addon(self, key: str) -> AddonCatalogEntry | None:
        for entry in self.addons:
            if entry.key == key:
                return entry
        return None

    def topup(self, key: str) -> TopupCatalogEntry | None:
        for entry in self.topups:
            if entry.key == key:
                return entry
        return None


def resolve_region(country_code: str | None) -> str:
    """Resolve a region from a normalized ISO country, server-side only.

    ``None`` is the PUBLIC preview: it resolves to the config-owned preview
    region and never authorizes a purchase (checkout requires a country).
    """
    country = (country_code or "").strip().upper()
    if not country:
        return PREVIEW_REGION
    return REGION_INDIA if country == INDIA_COUNTRY_CODE else REGION_INTERNATIONAL


def _minor_units(value: Decimal) -> int:
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _level_ordinal(key: str, value: str) -> int:
    """The registry ordinal a level grant stores for a public level value."""
    definition = CAPABILITY_REGISTRY.require(key)
    return definition.ordered_values.index(value)


def _india_amount_minor(usd_minor: int) -> int:
    """India minor units from the operator-owned USD/INR rate.

    A zero/unset rate deliberately yields 0 ("route unavailable"), never a
    guessed rate.
    """
    rate = billing_settings.usd_inr_rate
    if rate <= 0:
        return 0
    return _minor_units(Decimal(usd_minor) * rate)


def _regional_prices(
    usd_minor: int, catalog_key: str, purpose: str
) -> dict[str, CatalogPrice]:
    """Both regional prices for one amount, each with its PRIVATE ref."""
    return {
        REGION_INTERNATIONAL: CatalogPrice(
            currency=CURRENCY_USD,
            amount_minor=usd_minor,
            tax_behavior=TAX_BEHAVIOR_INCLUSIVE,
            provider_price_ref=provider_price_ref(
                catalog_key, REGION_INTERNATIONAL, purpose
            ),
        ),
        REGION_INDIA: CatalogPrice(
            currency=CURRENCY_INR,
            amount_minor=_india_amount_minor(usd_minor),
            tax_behavior=TAX_BEHAVIOR_EXCLUSIVE,
            provider_price_ref=provider_price_ref(catalog_key, REGION_INDIA, purpose),
        ),
    }


def provider_price_ref(catalog_key: str, region: str, purpose: str) -> str:
    """The PRIVATE operator-owned provider price ref, or "" when absent.

    Single owner of the lookup (invariant 2). The map is keyed
    ``"{catalog_key}:{region}:{purpose}"`` and is settings-supplied, so an
    absent ref makes the item unavailable instead of failing at purchase.
    """
    return billing_settings.provider_price_refs.get(
        f"{catalog_key}:{region}:{purpose}", ""
    ).strip()


def _funded_credit_prices(catalog_key: str) -> dict[str, dict[str, CatalogPrice]]:
    """Funded credit prices by cadence/region, or empty while UNSET.

    The funded credit price is the funded execution budget plus the
    operator-owned margin. The margin is deliberately NULL until product sets
    it, so funded checkout stays UNAVAILABLE rather than guessing a price.
    """
    margin_bps = billing_settings.funded_margin_bps
    if margin_bps is None:
        return {}
    usd_minor = _minor_units(
        Decimal(billing_settings.funded_monthly_budget_minor)
        * (Decimal(10_000 + margin_bps) / Decimal(10_000))
    )
    return {
        CADENCE_MONTHLY: _regional_prices(usd_minor, catalog_key, PRICE_PURPOSE_CREDIT)
    }


def _plan_entry(
    *,
    key: str,
    name: str,
    description: str,
    base_usd_minor: int,
    grant_bundle: tuple[GrantTemplate, ...],
) -> PlanCatalogEntry:
    return PlanCatalogEntry(
        key=key,
        name=name,
        description=description,
        cadence=CADENCE_MONTHLY,
        base_prices=_regional_prices(base_usd_minor, key, PRICE_PURPOSE_BASE),
        credit_prices_by_cadence=_funded_credit_prices(key),
        grant_bundle=grant_bundle,
        # Trial checkout is DEFERRED: the terms below are catalog copy and
        # grant-algebra fixtures only; they never enable a purchase.
        trial_availability=AVAILABILITY_UNAVAILABLE,
        trial_unavailable_reason=REASON_TRIAL_UNAVAILABLE,
        self_serve=True,
        contact_only=False,
    )


def _tier_1_grants() -> tuple[GrantTemplate, ...]:
    return (
        GrantTemplate(KEY_AUDIT_CADENCE, _level_ordinal(KEY_AUDIT_CADENCE, "weekly")),
        GrantTemplate(KEY_PROJECT_SLOTS, 1),
        GrantTemplate(KEY_PROMPT_SLOTS, 10),
        GrantTemplate(KEY_MONITORED_URLS, 50),
        GrantTemplate(KEY_HISTORY_WINDOW, _level_ordinal(KEY_HISTORY_WINDOW, "90d")),
        GrantTemplate(KEY_MANUAL_RUNS_PER_DAY, 3),
        GrantTemplate(KEY_EXPORTS, 1),
    )


def _upper_tier_grants(
    *,
    project_slots: int,
    prompt_slots: int,
    monitored_urls: int,
    history_window: str,
    manual_runs_per_day: int,
) -> tuple[GrantTemplate, ...]:
    """Tier 2/3 bundle. Grok/Perplexity/Copilot are shown as coming-soon
    capability rows and are deliberately NOT granted here — a plan never issues
    a runnable provider grant for an unshipped adapter.
    """
    return (
        GrantTemplate(KEY_AUDIT_CADENCE, _level_ordinal(KEY_AUDIT_CADENCE, "daily")),
        GrantTemplate(KEY_PROJECT_SLOTS, project_slots),
        GrantTemplate(KEY_PROMPT_SLOTS, prompt_slots),
        GrantTemplate(KEY_MONITORED_URLS, monitored_urls),
        GrantTemplate(
            KEY_HISTORY_WINDOW, _level_ordinal(KEY_HISTORY_WINDOW, history_window)
        ),
        GrantTemplate(KEY_FANOUT, 1),
        GrantTemplate(KEY_MANUAL_RUNS_PER_DAY, manual_runs_per_day),
        GrantTemplate(KEY_EXPORTS, 1),
    )


def _build_plans() -> tuple[PlanCatalogEntry, ...]:
    return (
        _plan_entry(
            key=PLAN_TIER_1,
            name="Tier 1",
            description="Weekly citation-capable audits for one project.",
            base_usd_minor=TIER_1_BASE_USD_MINOR,
            grant_bundle=_tier_1_grants(),
        ),
        _plan_entry(
            key=PLAN_TIER_2,
            name="Tier 2",
            description="Daily audits, prompt fan-out, and a year of history.",
            base_usd_minor=TIER_2_BASE_USD_MINOR,
            grant_bundle=_upper_tier_grants(
                project_slots=3,
                prompt_slots=30,
                monitored_urls=150,
                history_window="12mo",
                manual_runs_per_day=6,
            ),
        ),
        _plan_entry(
            key=PLAN_TIER_3,
            name="Tier 3",
            description="Portfolio coverage with two years of retained history.",
            base_usd_minor=TIER_3_BASE_USD_MINOR,
            grant_bundle=_upper_tier_grants(
                project_slots=10,
                prompt_slots=60,
                monitored_urls=400,
                history_window="24mo",
                manual_runs_per_day=12,
            ),
        ),
        # Enterprise is contact-only: no price, no provider ref, no grants.
        PlanCatalogEntry(
            key=PLAN_ENTERPRISE,
            name="Enterprise",
            description="Custom volume, security review, and deployment options.",
            cadence=CADENCE_CUSTOM,
            base_prices={},
            credit_prices_by_cadence={},
            grant_bundle=(),
            trial_availability=AVAILABILITY_UNAVAILABLE,
            trial_unavailable_reason=REASON_CONTACT_ONLY,
            self_serve=False,
            contact_only=True,
        ),
    )


def _addon_availability(prices: Mapping[str, CatalogPrice]) -> tuple[str, str | None]:
    """Available only when at least one region has a positive priced ref."""
    if any(price.purchasable for price in prices.values()):
        return AVAILABILITY_AVAILABLE, None
    return AVAILABILITY_UNAVAILABLE, REASON_CHECKOUT_UNAVAILABLE


def _build_addons() -> tuple[AddonCatalogEntry, ...]:
    entries: list[AddonCatalogEntry] = []
    for key, name, description, usd_minor, grants in (
        (
            ADDON_EXTRA_PROJECT,
            "Extra project",
            "One additional tracked project.",
            billing_settings.addon_extra_project_usd_minor,
            (GrantTemplate(KEY_PROJECT_SLOTS, ADDON_EXTRA_PROJECT_SLOTS_PER_UNIT),),
        ),
        (
            ADDON_EXTRA_PROMPTS,
            "Extra prompts",
            "Ten additional tracked prompts.",
            billing_settings.addon_extra_prompts_usd_minor,
            (GrantTemplate(KEY_PROMPT_SLOTS, ADDON_EXTRA_PROMPTS_SLOTS_PER_UNIT),),
        ),
    ):
        prices = _regional_prices(usd_minor, key, PRICE_PURPOSE_BASE)
        availability, reason = _addon_availability(prices)
        entries.append(
            AddonCatalogEntry(
                key=key,
                name=name,
                description=description,
                cadence=CADENCE_MONTHLY,
                quantity_bounds=QuantityBounds(ADDON_QUANTITY_MIN, ADDON_QUANTITY_MAX),
                prices=prices,
                grant_bundle_per_unit=grants,
                availability=availability,
                unavailable_reason=reason,
            )
        )
    return tuple(entries)


def _build_topups() -> tuple[TopupCatalogEntry, ...]:
    """Audit-credit packs. The pack size is UNSET, so the pack has no
    grant template and stays unavailable until product configures it.
    """
    credits_per_unit = billing_settings.topup_audit_credits_per_pack
    prices = _regional_prices(
        billing_settings.topup_audit_credits_usd_minor,
        TOPUP_AUDIT_CREDITS,
        PRICE_PURPOSE_BASE,
    )
    priced = any(price.purchasable for price in prices.values())
    grants = (
        (GrantTemplate(KEY_AUDIT_CREDITS, credits_per_unit),)
        if credits_per_unit
        else ()
    )
    available = priced and bool(grants)
    return (
        TopupCatalogEntry(
            key=TOPUP_AUDIT_CREDITS,
            name="Audit credits",
            description="One-time credits for additional citation-capable audits.",
            quantity_bounds=QuantityBounds(TOPUP_QUANTITY_MIN, TOPUP_QUANTITY_MAX),
            prices=prices,
            grant_bundle_per_unit=grants,
            availability=(
                AVAILABILITY_AVAILABLE if available else AVAILABILITY_UNAVAILABLE
            ),
            unavailable_reason=None if available else REASON_CHECKOUT_UNAVAILABLE,
            expiry_days=billing_settings.topup_credit_valid_days,
        ),
    )


def commercial_catalog() -> CommercialCatalog:
    """Build the immutable commercial catalog from current settings.

    Rebuilt per call (cheap, no I/O) so an operator-supplied provider ref or FX
    rate takes effect without a process restart and tests can vary settings.
    """
    return CommercialCatalog(
        revision=billing_settings.catalog_version,
        plans=_build_plans(),
        addons=_build_addons(),
        topups=_build_topups(),
        providers=PUBLIC_PROVIDER_CATALOG,
    )


def region_checkout_ready(region: str) -> bool:
    """Whether the operator has enabled checkout for a region at all."""
    if not (billing_settings.checkout_enabled and billing_settings.razorpay_live_ready):
        return False
    if region == REGION_INTERNATIONAL:
        return billing_settings.razorpay_international_ready
    return True


def plan_checkout_availability(
    plan: PlanCatalogEntry, region: str
) -> tuple[bool, str | None]:
    """Whether a plan is purchasable in a region, with a safe reason if not.

    Config owns the rule (invariant 1): contact-only plans are never
    purchasable, and an absent private provider ref or an unpriced region makes
    the plan unavailable rather than failing at purchase.
    """
    if plan.contact_only or not plan.self_serve:
        return False, REASON_CONTACT_ONLY
    price = plan.base_price(region)
    if price is None or not price.purchasable or not region_checkout_ready(region):
        return False, REASON_CHECKOUT_UNAVAILABLE
    return True, None


def price_tax_minor(price: CatalogPrice) -> int:
    """Region tax added ON TOP of one configured price (0 when inclusive).

    Config owns the rate (invariant 1): an ``exclusive`` price (India) adds
    GST, an ``inclusive`` price is already final. Domain code never embeds a
    tax rate or a rounding rule.
    """
    if price.tax_behavior != TAX_BEHAVIOR_EXCLUSIVE:
        return 0
    return _minor_units(Decimal(price.amount_minor) * billing_settings.india_gst_rate)


def item_checkout_availability(
    *, availability: str, price: CatalogPrice | None, region: str
) -> tuple[bool, str | None]:
    """Whether one add-on/top-up is purchasable in a region, with a safe reason.

    An absent private provider ref, an unpriced region, a catalog-unavailable
    item, or a region without operator-enabled checkout all refuse here rather
    than failing mid-purchase.
    """
    if availability != AVAILABILITY_AVAILABLE:
        return False, REASON_CHECKOUT_UNAVAILABLE
    if price is None or not price.purchasable or not region_checkout_ready(region):
        return False, REASON_CHECKOUT_UNAVAILABLE
    return True, None


def plan_period_grant_specs(
    catalog_key: str, catalog_revision: str
) -> tuple[tuple[str, int], ...] | None:
    """Grant templates for one subscription period (config-owned seam).

    Owned here (invariant 1) so the lifecycle projector never hard-codes a
    grant bundle. Returns None for an unknown key or a revision the current
    catalog does not own — a stale revision must never silently issue today's
    bundle.
    """
    catalog = commercial_catalog()
    if catalog_revision != catalog.revision:
        return None
    plan = catalog.plan(catalog_key)
    templates = plan.grant_bundle if plan is not None else ()
    if not templates:
        addon = catalog.addon(catalog_key)
        templates = addon.grant_bundle_per_unit if addon is not None else ()
    if not templates:
        return None
    return tuple((template.key, template.value) for template in templates)


def topup_grant_specs(
    catalog_key: str, catalog_revision: str
) -> tuple[tuple[str, int], ...] | None:
    """PER-UNIT grant templates for one top-up pack (config-owned seam).

    Returns None for an unknown key, a revision the current catalog does not
    own, or a pack whose size is UNSET (an unsized pack issues nothing).
    """
    catalog = commercial_catalog()
    if catalog_revision != catalog.revision:
        return None
    topup = catalog.topup(catalog_key)
    templates = topup.grant_bundle_per_unit if topup is not None else ()
    if not templates:
        return None
    return tuple((template.key, template.value) for template in templates)


def scale_grant_specs(
    specs: tuple[tuple[str, int], ...], quantity: int
) -> tuple[tuple[str, int], ...]:
    """Scale per-unit grant templates by a purchased quantity.

    Config owns the scaling rule (invariant 1) so no activation path
    multiplies a pack size inline.
    """
    if quantity < 1:
        raise ValueError("grant scaling quantity must be >= 1")
    return tuple((key, value * quantity) for key, value in specs)
