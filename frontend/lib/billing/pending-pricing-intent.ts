/**
 * A pricing selection captured before the visitor authenticated.
 *
 * This record is untrusted navigation state. It carries only enough to locate
 * a current catalog entry after authentication; price and availability are
 * always read from the live catalog before a server request is made.
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

type IntentFields = Omit<PendingPricingIntentV1, 'version' | 'return_path'>;

function recordFrom(raw: unknown): Record<string, unknown> | null {
  return typeof raw === 'object' && raw !== null ? (raw as Record<string, unknown>) : null;
}

function validKind(value: unknown): value is PendingIntentKind {
  return typeof value === 'string' && KINDS.includes(value as PendingIntentKind);
}

function isNonEmptyString(value: unknown): value is string {
  return typeof value === 'string' && value !== '';
}

function validQuantity(value: unknown): value is number {
  return typeof value === 'number' && Number.isInteger(value) && value >= 1;
}

function validFields(value: Record<string, unknown>): value is Record<keyof IntentFields, unknown> {
  return (
    validKind(value.kind) &&
    isNonEmptyString(value.catalog_key) &&
    validQuantity(value.quantity) &&
    typeof value.byok === 'boolean' &&
    (value.country_code === null || typeof value.country_code === 'string') &&
    isNonEmptyString(value.idempotency_key) &&
    typeof value.created_at_ms === 'number' &&
    Number.isFinite(value.created_at_ms)
  );
}

function hasValidTimestamp(createdAt: number, now: number): boolean {
  return now - createdAt <= PENDING_PRICING_INTENT_MAX_AGE_MS && createdAt <= now + 60_000;
}

/** Strict parse, rejecting malformed, stale, and future-versioned state. */
export function parsePendingIntent(
  raw: unknown,
  now: number = Date.now(),
): PendingPricingIntentV1 | null {
  const value = recordFrom(raw);
  if (
    !value ||
    value.version !== 1 ||
    value.return_path !== PRICING_RETURN_PATH ||
    !validFields(value)
  ) {
    return null;
  }
  if (!hasValidTimestamp(value.created_at_ms as number, now)) return null;

  return {
    version: 1,
    kind: value.kind as PendingIntentKind,
    catalog_key: value.catalog_key as string,
    quantity: value.quantity as number,
    byok: value.byok as boolean,
    country_code: value.country_code as string | null,
    idempotency_key: value.idempotency_key as string,
    return_path: PRICING_RETURN_PATH,
    created_at_ms: value.created_at_ms as number,
  };
}

function storage(): Storage | null {
  try {
    return globalThis.sessionStorage ?? null;
  } catch {
    return null;
  }
}

export function writePendingIntent(intent: PendingPricingIntentV1): void {
  try {
    storage()?.setItem(PENDING_PRICING_INTENT_KEY, JSON.stringify(intent));
  } catch {
    // A blocked store only means this tab cannot resume automatically.
  }
}

export function readPendingIntent(now: number = Date.now()): PendingPricingIntentV1 | null {
  try {
    const raw = storage()?.getItem(PENDING_PRICING_INTENT_KEY);
    return raw === null || raw === undefined ? null : parsePendingIntent(JSON.parse(raw), now);
  } catch {
    return null;
  }
}

export function clearPendingIntent(): void {
  try {
    storage()?.removeItem(PENDING_PRICING_INTENT_KEY);
  } catch {
    // Stale records expire independently.
  }
}

export function hasPendingIntent(now: number = Date.now()): boolean {
  return readPendingIntent(now) !== null;
}
