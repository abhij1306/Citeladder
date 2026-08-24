import { describe, expect, it } from 'vitest';

import type { BillingCatalog, CatalogPlan } from '@/lib/api/billing';

import {
  checkoutSelection,
  comparisonRows,
  formatMoney,
  headlinePrice,
  isPurchasable,
  providerMarketingStates,
} from './catalog';

function plan(overrides: Partial<CatalogPlan> = {}): CatalogPlan {
  return {
    key: 'tier_1',
    name: 'Starter',
    description: 'Entry plan',
    cadence: 'monthly',
    self_serve: true,
    contact_only: false,
    contact_url: null,
    base_price: { currency: 'USD', amount_minor: 4900 },
    credit_price: null,
    funded_total_price: null,
    checkout_available: true,
    unavailable_reason: null,
    capabilities: [],
    trial_availability: 'unavailable',
    trial_unavailable_reason: 'trial_unavailable',
    trial_days: null,
    ...overrides,
  } as CatalogPlan;
}

function catalog(overrides: Partial<BillingCatalog> = {}): BillingCatalog {
  return {
    catalog_revision: 'commercial-v9',
    country_code: 'US',
    region: 'international',
    currency: 'USD',
    currency_minor_units: 2,
    plans: [plan()],
    addons: [],
    topups: [],
    providers: [],
    ...overrides,
  } as BillingCatalog;
}

describe('headlinePrice', () => {
  it('resolves BYOK from base_price', () => {
    expect(headlinePrice(plan(), 'byok')).toEqual({
      kind: 'price',
      money: { currency: 'USD', amount_minor: 4900 },
    });
  });

  // The central rule of this release: unpriced is NOT free. A funded headline
  // must never resolve to a number, least of all zero.
  it('returns unavailable — never zero — when credit_price is null', () => {
    const result = headlinePrice(plan({ unavailable_reason: 'funded_not_priced' }), 'funded');
    expect(result).toEqual({ kind: 'unavailable', reason: 'funded_not_priced' });
  });

  it('returns contact for a contact-only plan in either mode', () => {
    const contact = plan({ key: 'enterprise', contact_only: true, base_price: null });
    expect(headlinePrice(contact, 'byok')).toEqual({ kind: 'contact' });
    expect(headlinePrice(contact, 'funded')).toEqual({ kind: 'contact' });
  });
});

describe('checkoutSelection', () => {
  it('accepts an available BYOK self-serve plan', () => {
    expect(checkoutSelection(plan(), 'byok')).toEqual({
      ok: true,
      catalog_key: 'tier_1',
      credential_mode: 'byok',
    });
  });

  it('refuses funded while credit_price is null', () => {
    expect(checkoutSelection(plan(), 'funded').ok).toBe(false);
  });

  it('refuses a contact-only plan', () => {
    expect(checkoutSelection(plan({ key: 'enterprise', contact_only: true }), 'byok').ok).toBe(
      false,
    );
  });

  it('refuses a plan the catalog marks unpurchasable', () => {
    expect(checkoutSelection(plan({ checkout_available: false }), 'byok').ok).toBe(false);
  });
});

describe('comparisonRows', () => {
  it('derives rows from the union of published capability keys', () => {
    const rows = comparisonRows(
      catalog({
        plans: [
          plan({
            key: 'tier_1',
            capabilities: [
              {
                key: 'project_slots',
                capability_type: 'counter.occupancy',
                value: 1,
                issuable: true,
              },
            ],
          }),
          plan({
            key: 'tier_2',
            capabilities: [
              {
                key: 'project_slots',
                capability_type: 'counter.occupancy',
                value: 5,
                issuable: true,
              },
              { key: 'audit_web_search', capability_type: 'flag', value: true, issuable: true },
            ],
          }),
        ],
      }),
    );

    expect(rows.map((row) => row.key)).toEqual(['project_slots', 'audit_web_search']);
    expect(rows[0].values.tier_2?.value).toBe(5);
    // A plan that does not publish a key has no value for it — the caller
    // renders that as "not included", never as zero.
    expect(rows[1].values.tier_1).toBeUndefined();
  });
});

describe('isPurchasable', () => {
  it('rejects an available-but-unpriced entry', () => {
    expect(
      isPurchasable({
        key: 'topup_bench',
        name: 'Audit credits',
        description: '',
        cadence: 'monthly',
        unit_price: null,
        quantity_min: 1,
        quantity_max: 10,
        availability: 'available',
        unavailable_reason: null,
        grant_key: 'audit_credits',
        grant_value_per_unit: 1,
      }),
    ).toBe(false);
  });
});

describe('providerMarketingState', () => {
  it('projects planned providers as coming-soon with no route', () => {
    const states = providerMarketingStates(
      catalog({
        providers: [
          {
            key: 'provider.openai',
            label: 'ChatGPT',
            availability: 'available',
            unavailable_reason: null,
            adapter_shipped: true,
            grant_key: 'provider.openai',
            issuable: true,
            routes: [
              {
                logical_engine: 'chatgpt',
                transport_provider: 'openai',
                model: 'gpt-5',
              },
            ],
          },
          {
            key: 'provider.grok',
            label: 'Grok',
            availability: 'unavailable',
            unavailable_reason: 'adapter_not_shipped',
            adapter_shipped: false,
            grant_key: 'provider.grok',
            issuable: true,
            routes: [],
          },
        ],
      }),
    );

    expect(states[0]).toMatchObject({ label: 'ChatGPT', shipped: true, comingSoon: false });
    expect(states[1]).toMatchObject({
      label: 'Grok',
      shipped: false,
      comingSoon: true,
      reason: 'adapter_not_shipped',
    });
  });

  // A shipped adapter with no published route is still not connectable — a
  // logo must never imply capability the catalog does not back.
  it('treats an adapter with no route as coming-soon', () => {
    const [state] = providerMarketingStates(
      catalog({
        providers: [
          {
            key: 'provider.perplexity',
            label: 'Perplexity',
            availability: 'available',
            unavailable_reason: null,
            adapter_shipped: true,
            grant_key: 'provider.perplexity',
            issuable: true,
            routes: [],
          },
        ],
      }),
    );
    expect(state.comingSoon).toBe(true);
  });
});

describe('formatMoney', () => {
  it('uses the catalog currency and minor units, with no price constants', () => {
    expect(formatMoney({ currency: 'USD', amount_minor: 4900 }, 2)).toBe('$49');
    expect(formatMoney({ currency: 'INR', amount_minor: 499900 }, 2)).toContain('4,999');
  });
});
