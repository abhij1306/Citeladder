import { afterEach, describe, expect, it, vi } from 'vitest';

import { billingApi } from './billing';

const QUOTE = {
  quote_id: 'q_opaque',
  catalog_revision: 'commercial-v9',
  catalog_key: 'tier_2',
  credential_mode: 'byok',
  country_code: 'IN',
  region: 'india',
  base_price: { currency: 'INR', amount_minor: 499900 },
  credit_price: null,
  tax: { currency: 'INR', amount_minor: 89982 },
  total_price: { currency: 'INR', amount_minor: 589882 },
  expires_at: '2026-08-01T12:00:00Z',
};

const ACTIVATION = {
  activation_id: '11111111-1111-4111-8111-111111111111',
  kind: 'base',
  catalog_key: 'tier_2',
  quantity: 1,
  status: 'pending',
  quote: QUOTE,
  checkout_url: 'https://rzp.io/i/test',
  expires_at: '2026-08-01T12:00:00Z',
  failure_code: null,
};

function json(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'content-type': 'application/json' },
  });
}

function stubFetch(body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(json(body));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe('billing API contract', () => {
  it('submits only catalog key, mode and country — never an amount or plan id', async () => {
    const fetchMock = stubFetch(ACTIVATION);

    await billingApi.createSubscription(
      { catalog_key: 'tier_2', credential_mode: 'byok', country_code: 'IN' },
      'checkout-idempotency-key',
    );

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/billing/subscriptions');
    // The server owns every amount. A body carrying a price, currency, region
    // or external id would mean the browser could influence the charge.
    expect(JSON.parse(String(init.body))).toEqual({
      catalog_key: 'tier_2',
      credential_mode: 'byok',
      country_code: 'IN',
      trial_requested: false,
    });
    expect(new Headers(init.headers).get('Idempotency-Key')).toBe('checkout-idempotency-key');
  });

  it('sends trial_requested:false — the backend answers trial_unavailable otherwise', async () => {
    const fetchMock = stubFetch(ACTIVATION);
    await billingApi.createSubscription(
      { catalog_key: 'tier_1', credential_mode: 'byok', country_code: 'US' },
      'key-1',
    );
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(String(init.body)).trial_requested).toBe(false);
  });

  it('carries an Idempotency-Key on every commercial POST', async () => {
    const addon = stubFetch({ ...ACTIVATION, kind: 'addon', catalog_key: 'addon_seats' });
    await billingApi.activateAddon('addon_seats', 3, 'addon-key');
    expect(
      new Headers((addon.mock.calls[0] as [string, RequestInit])[1].headers).get('Idempotency-Key'),
    ).toBe('addon-key');
    vi.unstubAllGlobals();

    const topup = stubFetch({ ...ACTIVATION, kind: 'topup', catalog_key: 'topup_bench' });
    await billingApi.purchaseTopup('topup_bench', 2, 'topup-key');
    expect(
      new Headers((topup.mock.calls[0] as [string, RequestInit])[1].headers).get('Idempotency-Key'),
    ).toBe('topup-key');
  });

  it('parses add-on deactivation through its own vocabulary, not the activation machine', async () => {
    const fetchMock = stubFetch({
      catalog_key: 'addon_seats',
      status: 'cancellation_scheduled',
      effective_at: '2026-09-01T00:00:00Z',
    });

    const result = await billingApi.deactivateAddon('addon_seats');

    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe('/api/v1/billing/addons/addon_seats');
    expect(init.method).toBe('DELETE');
    expect(result.status).toBe('cancellation_scheduled');
    // A deactivation has no pending/activated/failed lifecycle at all.
    expect('quote' in result).toBe(false);
  });

  it('rejects a retired tier key rather than rendering it as an unknown plan', async () => {
    stubFetch({
      catalog_revision: 'commercial-v9',
      country_code: 'IN',
      region: 'india',
      currency: 'INR',
      currency_minor_units: 2,
      plans: [{ key: 'paid', name: 'Paid', description: '', cadence: 'monthly' }],
      addons: [],
      topups: [],
      providers: [],
    });

    await expect(billingApi.catalog('IN')).rejects.toThrow(/billing\.catalog/);
  });

  it('strips leaked provider fields from the catalog (tolerant-on-unknown)', async () => {
    stubFetch({
      catalog_revision: 'commercial-v9',
      country_code: 'IN',
      region: 'india',
      currency: 'INR',
      currency_minor_units: 2,
      plans: [],
      addons: [],
      topups: [],
      providers: [],
      razorpay_plan_id: 'plan_leaked',
    });

    // Additive provider fields must never break the UI — they are stripped
    // from the parsed output, so the leak never reaches app state.
    const catalog = await billingApi.catalog('IN');
    expect('razorpay_plan_id' in catalog).toBe(false);
  });

  it('reads entitlement and usage from account-scoped routes', async () => {
    const usage = stubFetch({
      billing_account_id: '11111111-1111-4111-8111-111111111111',
      entitlement_lifecycle_version: 1,
      status: 'resolved',
      items: [],
    });
    await billingApi.usage();
    expect((usage.mock.calls[0] as [string, RequestInit])[0]).toBe('/api/v1/billing/usage');
  });
});
