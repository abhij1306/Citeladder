/**
 * A pricing selection captured before the visitor authenticated.
 *
 * This record is UNTRUSTED NAVIGATION STATE and nothing more. It lives in
 * same-tab `sessionStorage`, which any script on the page can write, so it
 * stores no amount, no external id, no user/workspace id, and no
 * authorization claim — only enough to re-find the same catalog entry after
 * a full-page auth round-trip. Every field that matters (price, availability,
 * quantity bounds) is re-read from the LIVE catalog on resume; a stored value
 * is never replayed into a server request.
 *
 * The one field that carries forward is the idempotency key, deliberately: if
 * the visitor's first attempt did reach the backend, reusing the key replays
 * that intent instead of creating a second charge.
 */
import {
  PENDING_PRICING_INTENT_KEY,
  PENDING_PRICING_INTENT_MAX_AGE_MS,
  PRICING_RETURN_PATH,
} from '@/lib/config/billing';

export type PendingIntentKind = 'checkout' | 'addon' | 'topup';

export type PendingPricingIntentV1 = {
  version: 1;
  kind: PendingIntentKind;
  catalog_key: string;
  quantity: number;
  byok: boolean;
  country_code: string | null;
  idempotency_key: string;
  return_path: typeof PRICING_RETURN_PATH;
  created_at_ms: number;
};

const KINDS: readonly PendingIntentKind[] = ['checkout', 'addon', 'topup'];

/**
 * Strict parse. Anything malformed, versioned differently, or older than the
 * max age is rejected — a stale intent was captured against a catalog that may
 * since have changed price or availability.
 */
export function parsePendingIntent(
  raw: unknown,
  now: number = Date.now(),
): PendingPricingIntentV1 | null {
  if (typeof raw !== 'object' || raw === null) return null;
  const value = raw as Record<string, unknown>;
  if (value.version !== 1) return null;
  if (typeof value.kind !== 'string' || !KINDS.includes(value.kind as PendingIntentKind)) {
    return null;
  }
  if (typeof value.catalog_key !== 'string' || value.catalog_key === '') return null;
  if (
    typeof value.quantity !== 'number' ||
    !Number.isInteger(value.quantity) ||
    value.quantity < 1
  ) {
    return null;
  }
  if (typeof value.byok !== 'boolean') return null;
  if (value.country_code !== null && typeof value.country_code !== 'string') return null;
  if (typeof value.idempotency_key !== 'string' || value.idempotency_key === '') return null;
  if (value.return_path !== PRICING_RETURN_PATH) return null;
  if (typeof value.created_at_ms !== 'number' || !Number.isFinite(value.created_at_ms)) return null;
  if (now - value.created_at_ms > PENDING_PRICING_INTENT_MAX_AGE_MS) return null;
  if (value.created_at_ms > now + 60_000) return null; // clock skew / forged future stamp

  return {
    version: 1,
    kind: value.kind as PendingIntentKind,
    catalog_key: value.catalog_key,
    quantity: value.quantity,
    byok: value.byok,
    country_code: value.country_code as string | null,
    idempotency_key: value.idempotency_key,
    return_path: PRICING_RETURN_PATH,
    created_at_ms: value.created_at_ms,
  };
}

function storage(): Storage | null {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    // Storage can throw outright under strict privacy settings.
    return null;
  }
}

export function writePendingIntent(intent: PendingPricingIntentV1): void {
  try {
    storage()?.setItem(PENDING_PRICING_INTENT_KEY, JSON.stringify(intent));
  } catch {
    // A full or blocked store is not worth failing the click over — the
    // visitor still reaches auth, just without the resume.
  }
}

export function readPendingIntent(now: number = Date.now()): PendingPricingIntentV1 | null {
  const raw = (() => {
    try {
      return storage()?.getItem(PENDING_PRICING_INTENT_KEY) ?? null;
    } catch {
      return null;
    }
  })();
  if (raw === null) return null;
  try {
    return parsePendingIntent(JSON.parse(raw), now);
  } catch {
    return null;
  }
}

export function clearPendingIntent(): void {
  try {
    storage()?.removeItem(PENDING_PRICING_INTENT_KEY);
  } catch {
    // Nothing to do — a stale record expires on its own.
  }
}

export function hasPendingIntent(now: number = Date.now()): boolean {
  return readPendingIntent(now) !== null;
}
