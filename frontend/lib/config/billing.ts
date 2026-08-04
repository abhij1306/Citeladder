/**
 * Commercial-surface configuration (invariant 1: no component-owned prices,
 * thresholds, or cadences).
 *
 * Checkout prices, limits, and availability come from `GET /billing/catalog`.
 * The temporary public price presentation below does not authorize checkout.
 */

/**
 * BYOK is ON by default in this release because `base_price` is the only
 * measured, available price: funded inputs are deliberately unset, so
 * `credit_price` is null and funded checkout cannot start. Frozen §7.1's
 * "default OFF shows funded, BYOK animates downward" behaviour is deferred
 * until the funded catalog values are measured (PR3).
 */
export const PRICING_BYOK_DEFAULT_ON = true;

/** Duration of the numeric price tween. Only real number-to-number changes animate. */
export const PRICING_PRICE_TWEEN_MS = 275;

/** Approved public monthly plan presentation, in USD minor units. */
export const PLAN_MONTHLY_PRICE_USD_MINOR = {
  tier_1: { byok: 4_900, funded: 9_900 },
  tier_2: { byok: 9_900, funded: 14_900 },
  tier_3: { byok: 14_900, funded: 29_900 },
} as const;

export function planMonthlyPriceUsdMinor(key: string, mode: 'byok' | 'funded'): number | null {
  if (!Object.hasOwn(PLAN_MONTHLY_PRICE_USD_MINOR, key)) return null;
  return PLAN_MONTHLY_PRICE_USD_MINOR[key as keyof typeof PLAN_MONTHLY_PRICE_USD_MINOR][mode];
}

/** The query parameter that mirrors BYOK selection into the URL. */
export const PRICING_BYOK_QUERY_PARAM = 'byok';

/** Set on return from auth when a captured pricing intent should be resumed. */
export const PRICING_RESUME_QUERY_PARAM = 'resumeActivation';

/** Where a captured pricing intent returns to after authentication. */
export const PRICING_RETURN_PATH = '/pricing';

/** Same-tab storage key for a captured (untrusted) pricing intent. */
export const PENDING_PRICING_INTENT_KEY = 'citeladder.pendingPricingIntent.v1';

/**
 * A captured intent older than this is stale: the catalog it was captured
 * against may have changed, so it is discarded rather than replayed.
 */
export const PENDING_PRICING_INTENT_MAX_AGE_MS = 60 * 60 * 1000;

/**
 * Usage-meter threshold bands. These apply ONLY to `limit_state: 'finite'`
 * rows with real numeric aggregates — an `unlimited` or `unknown` row has no
 * ratio and must never be coloured by one. A server-supplied status always
 * wins over these.
 */
export const USAGE_METER_WARNING_RATIO = 0.8;
export const USAGE_METER_CRITICAL_RATIO = 0.95;
