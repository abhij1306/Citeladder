import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

const ACCOUNT = '11111111-1111-4111-8111-111111111111';

let entitlementValue: unknown = null;

vi.mock('@/lib/billing/entitlement-context', () => ({
  useEntitlement: () => ({
    entitlement: entitlementValue,
    isLoading: false,
    hasCapability: () => false,
    canStartPaidWork: false,
  }),
}));

import { BillingSettings } from './billing-settings';

function resolvedEntitlement(subscription: unknown = null) {
  return {
    billing_account_id: ACCOUNT,
    status: 'resolved',
    errors: [],
    registry_revision: 'registry-v8',
    entitlement_lifecycle_version: 1,
    resolved_at: '2026-08-01T00:00:00Z',
    valid_until: null,
    subscription,
    trial_grant: null,
    capabilities: [],
    grants: [],
  };
}

const CATALOG = {
  catalog_revision: 'commercial-v8',
  country_code: 'US',
  region: 'international',
  currency: 'USD',
  currency_minor_units: 2,
  plans: [
    {
      key: 'tier_1',
      name: 'Starter',
      description: 'Entry plan',
      cadence: 'monthly',
      self_serve: true,
      contact_only: false,
      contact_url: null,
      base_price: { currency: 'USD', amount_minor: 4900 },
      // Funded inputs are deliberately unset in this release.
      credit_price: null,
      funded_total_price: null,
      checkout_available: true,
      unavailable_reason: null,
      capabilities: [],
      trial_availability: 'unavailable',
      trial_unavailable_reason: 'trial_unavailable',
      trial_days: null,
    },
    {
      key: 'enterprise',
      name: 'Enterprise',
      description: 'Custom agreement',
      cadence: 'custom',
      self_serve: false,
      contact_only: true,
      contact_url: '/demo',
      base_price: null,
      credit_price: null,
      funded_total_price: null,
      checkout_available: false,
      unavailable_reason: 'contact_sales',
      capabilities: [],
      trial_availability: 'unavailable',
      trial_unavailable_reason: 'trial_unavailable',
      trial_days: null,
    },
  ],
  addons: [],
  topups: [],
  providers: [],
};

const USAGE = {
  billing_account_id: ACCOUNT,
  entitlement_lifecycle_version: 1,
  status: 'resolved',
  items: [
    {
      key: 'prompt_slots',
      capability_type: 'counter.occupancy',
      unit: 'prompts',
      limit_state: 'finite',
      allowance: 100,
      consumed: 42,
      reserved: 0,
      remaining: 58,
      window_started_at: null,
      resets_at: null,
      earliest_expiry: null,
      grants: [],
    },
    {
      key: 'benchmark_credits',
      capability_type: 'counter.consumable',
      unit: 'credits',
      limit_state: 'unknown',
      allowance: null,
      consumed: null,
      reserved: null,
      remaining: null,
      window_started_at: null,
      resets_at: null,
      earliest_expiry: null,
      grants: [],
    },
  ],
};

const catalogHandler = () => http.get('/api/v1/billing/catalog', () => HttpResponse.json(CATALOG));
const usageHandler = () => http.get('/api/v1/billing/usage', () => HttpResponse.json(USAGE));

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  mswServer.resetHandlers();
  entitlementValue = null;
});
afterAll(() => mswServer.close());

describe('BillingSettings', () => {
  it('renders the plan from the catalog with no retired free/paid vocabulary', async () => {
    entitlementValue = resolvedEntitlement({
      catalog_key: 'tier_1',
      status: 'active',
      current_period_end: '2026-09-01T00:00:00Z',
      cancel_at_period_end: false,
    });
    mswServer.use(catalogHandler(), usageHandler());

    renderWithProviders(<BillingSettings />);

    expect((await screen.findAllByText('Starter')).length).toBeGreaterThan(0);
    const body = document.body.textContent ?? '';
    expect(body).not.toMatch(/Free plan/);
    expect(body).not.toMatch(/Upgrade with Razorpay/);
  });

  it('fails closed when the entitlement cannot resolve', async () => {
    entitlementValue = null;
    mswServer.use(catalogHandler(), usageHandler());

    renderWithProviders(<BillingSettings />);

    expect(await screen.findByText(/entitlement could not be resolved/i)).toBeInTheDocument();
  });

  it('shows the BYOK base price and blocks checkout until a country is supplied', async () => {
    entitlementValue = resolvedEntitlement();
    mswServer.use(catalogHandler(), usageHandler());

    renderWithProviders(<BillingSettings />);

    // The headline equals the catalog's own base_price — never a constant.
    expect(await screen.findByText('$49 / month')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Choose Starter/ })).toBeDisabled();

    await userEvent.type(screen.getByLabelText(/Billing country/i), 'US');
    await waitFor(() =>
      expect(screen.getByRole('button', { name: /Choose Starter/ })).toBeEnabled(),
    );
  });

  it('submits only the catalog key, BYOK mode and country — never an amount', async () => {
    entitlementValue = resolvedEntitlement();
    const bodies: unknown[] = [];
    mswServer.use(
      catalogHandler(),
      usageHandler(),
      http.post('/api/v1/billing/subscriptions', async ({ request }) => {
        bodies.push(await request.json());
        return HttpResponse.json({
          activation_id: ACCOUNT,
          kind: 'base',
          catalog_key: 'tier_1',
          quantity: 1,
          status: 'pending',
          quote: {
            quote_id: 'q1',
            catalog_revision: 'commercial-v8',
            catalog_key: 'tier_1',
            credential_mode: 'byok',
            country_code: 'US',
            region: 'international',
            base_price: { currency: 'USD', amount_minor: 4900 },
            credit_price: null,
            tax: { currency: 'USD', amount_minor: 0 },
            total_price: { currency: 'USD', amount_minor: 4900 },
            expires_at: '2026-08-01T12:00:00Z',
          },
          checkout_url: null,
          expires_at: '2026-08-01T12:00:00Z',
          failure_code: null,
        });
      }),
    );

    renderWithProviders(<BillingSettings />);
    await screen.findByText('$49 / month');
    await userEvent.type(screen.getByLabelText(/Billing country/i), 'US');
    await userEvent.click(screen.getByRole('button', { name: /Choose Starter/ }));

    await waitFor(() => expect(bodies).toHaveLength(1));
    expect(bodies[0]).toEqual({
      catalog_key: 'tier_1',
      credential_mode: 'byok',
      country_code: 'US',
      trial_requested: false,
    });
  });

  it('renders Enterprise as contact-only, with no checkout and no trial CTA', async () => {
    entitlementValue = resolvedEntitlement();
    mswServer.use(catalogHandler(), usageHandler());

    renderWithProviders(<BillingSettings />);
    await screen.findByText('$49 / month');

    const enterprise = document.querySelector('[data-tier="enterprise"]') as HTMLElement;
    expect(enterprise).not.toBeNull();
    expect(within(enterprise).getByText('Contact us')).toBeInTheDocument();
    expect(within(enterprise).queryByRole('button', { name: /Choose/ })).toBeNull();
    expect(document.body.textContent).not.toMatch(/free trial|7 days free/i);
  });

  it('distinguishes an unknown usage allowance from zero', async () => {
    entitlementValue = resolvedEntitlement();
    mswServer.use(catalogHandler(), usageHandler());

    renderWithProviders(<BillingSettings />);

    // A finite row shows the real ratio…
    expect(await screen.findByText('42 / 100 prompts')).toBeInTheDocument();
    // …and an `unknown` row says so rather than rendering a zero meter.
    expect(screen.getByText('Not available')).toBeInTheDocument();
    expect(screen.queryByText(/0 \/ 0 credits/)).toBeNull();
  });

  it('requires the cancellation dialog before mutating', async () => {
    entitlementValue = resolvedEntitlement({
      catalog_key: 'tier_1',
      status: 'active',
      current_period_end: '2026-09-01T00:00:00Z',
      cancel_at_period_end: false,
    });
    let deleted = 0;
    mswServer.use(
      catalogHandler(),
      usageHandler(),
      http.delete('/api/v1/billing/subscription', () => {
        deleted += 1;
        return HttpResponse.json({
          catalog_key: 'tier_1',
          status: 'cancellation_scheduled',
          effective_at: '2026-09-01T00:00:00Z',
        });
      }),
    );

    renderWithProviders(<BillingSettings />);

    await userEvent.click(
      (await screen.findAllByRole('button', { name: /Cancel at period end/ }))[0],
    );
    expect(deleted).toBe(0);

    const dialog = await screen.findByRole('dialog');
    await userEvent.click(within(dialog).getByRole('button', { name: /Cancel at period end/ }));
    await waitFor(() => expect(deleted).toBe(1));
  });

  it('surfaces a catalog failure without falling back to a price', async () => {
    entitlementValue = resolvedEntitlement();
    mswServer.use(
      http.get('/api/v1/billing/catalog', () =>
        HttpResponse.json({ detail: 'catalog unavailable' }, { status: 400 }),
      ),
      usageHandler(),
    );

    renderWithProviders(<BillingSettings />);

    expect(await screen.findByText(/Could not load the plan catalog/i)).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Choose/ })).toBeNull();
    // No component-owned fallback price may appear when the catalog is gone.
    expect(document.body.textContent).not.toMatch(/\$\d/);
  });
});
