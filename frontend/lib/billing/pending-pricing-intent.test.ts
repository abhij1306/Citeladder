import { afterEach, describe, expect, it } from 'vitest';

import { PENDING_PRICING_INTENT_MAX_AGE_MS } from '@/lib/config/billing';

import {
  clearPendingIntent,
  hasPendingIntent,
  parsePendingIntent,
  readPendingIntent,
  writePendingIntent,
  type PendingPricingIntentV1,
} from './pending-pricing-intent';

const NOW = 1_800_000_000_000;

function intent(overrides: Partial<PendingPricingIntentV1> = {}): PendingPricingIntentV1 {
  return {
    version: 1,
    kind: 'checkout',
    catalog_key: 'tier_2',
    quantity: 1,
    byok: true,
    country_code: null,
    idempotency_key: 'idem-1',
    return_path: '/pricing',
    created_at_ms: NOW,
    ...overrides,
  };
}

afterEach(() => clearPendingIntent());

describe('pending pricing intent', () => {
  it('round-trips a valid record', () => {
    writePendingIntent(intent());
    expect(readPendingIntent(NOW)).toEqual(intent());
    expect(hasPendingIntent(NOW)).toBe(true);
  });

  it('clears', () => {
    writePendingIntent(intent());
    clearPendingIntent();
    expect(readPendingIntent(NOW)).toBeNull();
  });

  // This record is attacker-writable session state. Every one of these cases
  // must be rejected BEFORE it can influence a request.
  it.each([
    ['a different version', { version: 2 }],
    ['an unknown kind', { kind: 'refund' }],
    ['an empty catalog key', { catalog_key: '' }],
    ['a fractional quantity', { quantity: 1.5 }],
    ['a zero quantity', { quantity: 0 }],
    ['a non-boolean byok', { byok: 'yes' }],
    ['a missing idempotency key', { idempotency_key: '' }],
    ['a foreign return path', { return_path: 'https://evil.example/pricing' }],
  ])('rejects %s', (_label, overrides) => {
    expect(parsePendingIntent({ ...intent(), ...overrides }, NOW)).toBeNull();
  });

  it('rejects a stale record captured against an older catalog', () => {
    const stale = intent({ created_at_ms: NOW - PENDING_PRICING_INTENT_MAX_AGE_MS - 1 });
    expect(parsePendingIntent(stale, NOW)).toBeNull();
  });

  it('rejects a future-dated record', () => {
    expect(parsePendingIntent(intent({ created_at_ms: NOW + 10 * 60_000 }), NOW)).toBeNull();
  });

  it('rejects malformed stored JSON without throwing', () => {
    globalThis.sessionStorage.setItem('citeladder.pendingPricingIntent.v1', '{not json');
    expect(readPendingIntent(NOW)).toBeNull();
  });

  it('stores no amount, external id, or identity claim', () => {
    writePendingIntent(intent());
    const raw = globalThis.sessionStorage.getItem('citeladder.pendingPricingIntent.v1') ?? '';

    // The record must never become a channel for values the server owns.
    for (const forbidden of [
      'amount',
      'price',
      'currency',
      'user_id',
      'workspace_id',
      'token',
      'role',
    ]) {
      expect(raw).not.toContain(forbidden);
    }
    expect(Object.keys(JSON.parse(raw)).sort()).toEqual([
      'byok',
      'catalog_key',
      'country_code',
      'created_at_ms',
      'idempotency_key',
      'kind',
      'quantity',
      'return_path',
      'version',
    ]);
  });
});
