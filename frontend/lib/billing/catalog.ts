/**
 * Pure selectors over the public billing catalog.
 *
 * These functions are the ONLY place a price, limit, or availability decision
 * is derived, and they derive it entirely from the catalog response. No module
 * here holds a price constant, and none may compute a total the server did not
 * send: a null `credit_price` means funded is not yet priced, which is a
 * distinct outcome from "free" and must never collapse to zero.
 */
import type {
  BillingCatalog,
  CatalogAddon,
  CatalogPlan,
  CatalogProvider,
  CatalogTopup,
  CredentialMode,
  SelfServePlanKey,
} from '@/lib/api/billing';

export type Money = { currency: 'USD' | 'INR'; amount_minor: number };

/**
 * What a tier's headline should show. The `unavailable` variant carries the
 * backend's own reason so no component invents copy for it.
 */
export type HeadlinePrice =
  | { kind: 'price'; money: Money }
  | { kind: 'contact' }
  | { kind: 'unavailable'; reason: string | null };

export function catalogPlanByKey(catalog: BillingCatalog, key: string): CatalogPlan | undefined {
  return catalog.plans.find((plan) => plan.key === key);
}

export function isSelfServeKey(key: string): key is SelfServePlanKey {
  return key === 'tier_1' || key === 'tier_2' || key === 'tier_3';
}

/**
 * The price to display for one plan in one credential mode.
 *
 * BYOK resolves to `base_price` — the only measured, available price in this
 * release. Funded resolves to `credit_price`, which is null while funded
 * inputs are unset, so it returns an explicit unavailable result. A
 * contact-only plan never shows a number at all.
 */
export function headlinePrice(plan: CatalogPlan, mode: CredentialMode): HeadlinePrice {
  if (plan.contact_only) {
    return { kind: 'contact' };
  }
  if (mode === 'funded') {
    return plan.credit_price
      ? { kind: 'price', money: plan.credit_price }
      : { kind: 'unavailable', reason: plan.unavailable_reason };
  }
  return plan.base_price
    ? { kind: 'price', money: plan.base_price }
    : { kind: 'unavailable', reason: plan.unavailable_reason };
}

export type CheckoutSelection =
  | { ok: true; catalog_key: SelfServePlanKey; credential_mode: CredentialMode }
  | { ok: false; reason: string | null };

/**
 * The checkout request fields for one plan, or a refusal.
 *
 * Refuses contact-only plans, plans the catalog marks unpurchasable, and any
 * funded selection while `credit_price` is null — the client must not be able
 * to start a checkout the backend would have to reject.
 */
export function checkoutSelection(plan: CatalogPlan, mode: CredentialMode): CheckoutSelection {
  if (plan.contact_only || !plan.self_serve || !isSelfServeKey(plan.key)) {
    return { ok: false, reason: plan.unavailable_reason };
  }
  if (!plan.checkout_available) {
    return { ok: false, reason: plan.unavailable_reason };
  }
  if (mode === 'funded' && plan.credit_price === null) {
    return { ok: false, reason: plan.unavailable_reason };
  }
  return { ok: true, catalog_key: plan.key, credential_mode: mode };
}

export type ComparisonRow = {
  key: string;
  /** Per-plan capability value, keyed by plan key. */
  values: Record<string, CatalogPlan['capabilities'][number] | undefined>;
};

/**
 * The comparison grid, derived from the union of capability keys the plans
 * publish — never from a hardcoded axis list, so a new backend capability
 * appears without a frontend change.
 */
export function comparisonRows(catalog: BillingCatalog): ComparisonRow[] {
  const keys = new Set<string>();
  for (const plan of catalog.plans) {
    for (const capability of plan.capabilities) {
      keys.add(capability.key);
    }
  }
  return [...keys].map((key) => ({
    key,
    values: Object.fromEntries(
      catalog.plans.map((plan) => [plan.key, plan.capabilities.find((c) => c.key === key)]),
    ),
  }));
}

export function isPurchasable(entry: CatalogAddon | CatalogTopup): boolean {
  return entry.availability === 'available' && entry.unit_price !== null;
}

export type ProviderMarketingState = {
  key: string;
  label: string;
  /** True only when an adapter ships AND the catalog exposes a route. */
  shipped: boolean;
  comingSoon: boolean;
  reason: string | null;
};

/**
 * How a provider should be presented on marketing and settings surfaces.
 *
 * "Shipped" requires both a shipped adapter and at least one published route.
 * A logo alone is never evidence of capability: Grok, Perplexity and Copilot
 * are catalog entries with no route, so they project as coming-soon and can
 * never resolve to a connectable transport.
 */
function providerMarketingState(provider: CatalogProvider): ProviderMarketingState {
  const shipped =
    provider.availability === 'available' && provider.adapter_shipped && provider.routes.length > 0;
  return {
    key: provider.key,
    label: provider.label,
    shipped,
    comingSoon: !shipped,
    reason: provider.unavailable_reason,
  };
}

export function providerMarketingStates(catalog: BillingCatalog): ProviderMarketingState[] {
  return catalog.providers.map(providerMarketingState);
}

/**
 * Format a catalog amount using the catalog's own currency and minor units.
 * Contains no currency or price constants — everything comes from the response.
 */
export function formatMoney(money: Money, minorUnits: number): string {
  const value = money.amount_minor / 10 ** minorUnits;
  return new Intl.NumberFormat(undefined, {
    style: 'currency',
    currency: money.currency,
    minimumFractionDigits: value % 1 === 0 ? 0 : minorUnits,
    maximumFractionDigits: minorUnits,
  }).format(value);
}

/** The major-unit number an animated price tweens between. */
export function majorUnits(money: Money, minorUnits: number): number {
  return money.amount_minor / 10 ** minorUnits;
}
