/**
 * Commercial-surface configuration (invariant 1: no component-owned prices,
 * thresholds, or cadences).
 *
 * Nothing here is a price. Prices, limits and availability come only from
 * `GET /billing/catalog` — a component that cannot reach the catalog renders a
 * loading or error shell, never a fallback number.
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
