import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

vi.mock('next/navigation', () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

vi.mock('@/lib/billing/entitlement-context', () => ({
  useEntitlement: () => ({
    entitlement: {
      workspace_id: '22222222-2222-4222-8222-222222222222',
      tier_key: 'free',
      capability_revision: 1,
      audit_web_search: false,
      audit_scheduling: false,
      site_health_capability: 'free',
      paid_through: null,
      grace_until: null,
    },
    isLoading: false,
    canStartPaidWork: false,
  }),
}));

import { BillingSettings } from './billing-settings';

const SUMMARY = {
  billing_account_id: '11111111-1111-4111-8111-111111111111',
  billing_country: 'US',
  country_verification: 'provisional',
  tier_key: 'free',
  subscription_status: null,
  current_period_end: null,
  cancel_at_period_end: false,
  paid_through: null,
  grace_until: null,
  can_checkout: false,
  checkout_block_reason: 'checkout_not_enabled',
};

const CATALOG = {
  catalog_version: 'billing-v1',
  country_code: 'US',
  plans: [
    {
      tier_key: 'paid',
      name: 'Paid',
      cadence: 'monthly',
      self_serve: true,
      description: 'Paid plan',
      features: [],
      price: {
        region: 'international',
        currency: 'USD',
        base_amount_minor: 4900,
        tax_amount_minor: 0,
        total_amount_minor: 4900,
        tax_label: null,
        checkout_available: false,
      },
    },
  ],
};

function summaryHandler(overrides: Record<string, unknown> = {}) {
  return http.get('/api/v1/billing/me', () => HttpResponse.json({ ...SUMMARY, ...overrides }));
}

function catalogHandler() {
  return http.get('/api/v1/billing/catalog', () => HttpResponse.json(CATALOG));
}

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
beforeEach(() => window.history.replaceState(null, '', '/settings?tab=billing'));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('BillingSettings', () => {
  it('consumes the checkout return parameter while preserving the initial banner', async () => {
    window.history.replaceState(null, '', '/settings?tab=billing&checkout=return');
    mswServer.use(summaryHandler(), catalogHandler());

    renderWithProviders(<BillingSettings />);

    expect(await screen.findByText(/confirming payment/i)).toBeInTheDocument();
    await waitFor(() => expect(window.location.search).toBe('?tab=billing'));
  });

  it('surfaces a regional catalog failure', async () => {
    mswServer.use(
      summaryHandler(),
      http.get('/api/v1/billing/catalog', () =>
        HttpResponse.json({ detail: 'catalog unavailable' }, { status: 400 }),
      ),
    );

    renderWithProviders(<BillingSettings />);

    expect(
      await screen.findByText(/could not load the regional price catalog/i),
    ).toBeInTheDocument();
  });

  it('waits for the billing country before requesting the catalog', async () => {
    const requestedCountries: Array<string | null> = [];
    mswServer.use(
      summaryHandler(),
      http.get('/api/v1/billing/catalog', ({ request }) => {
        requestedCountries.push(new URL(request.url).searchParams.get('country'));
        return HttpResponse.json(CATALOG);
      }),
    );

    renderWithProviders(<BillingSettings />);

    expect(await screen.findByText('$49.00')).toBeInTheDocument();
    await waitFor(() => expect(requestedCountries).toEqual(['US']));
  });

  it('requires the styled cancellation dialog before mutating', async () => {
    const user = userEvent.setup();
    let cancellations = 0;
    mswServer.use(
      summaryHandler({
        subscription_status: 'active',
        current_period_end: '2026-08-26T00:00:00Z',
      }),
      catalogHandler(),
      http.post('/api/v1/billing/cancel', () => {
        cancellations += 1;
        return HttpResponse.json({ status: 'cancel_scheduled', cancel_at_period_end: true });
      }),
    );

    renderWithProviders(<BillingSettings />);
    await user.click(await screen.findByRole('button', { name: /cancel at period end/i }));
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    expect(cancellations).toBe(0);
    await user.click(screen.getByRole('button', { name: 'Keep Paid' }));
    expect(screen.queryByRole('dialog')).toBeNull();

    await user.click(screen.getByRole('button', { name: /cancel at period end/i }));
    await user.click(
      within(screen.getByRole('dialog')).getByRole('button', { name: /cancel at period end/i }),
    );
    await waitFor(() => expect(cancellations).toBe(1));
  });

  it('shows cancellation failures inside the open dialog', async () => {
    const user = userEvent.setup();
    mswServer.use(
      summaryHandler({
        subscription_status: 'active',
        current_period_end: '2026-08-26T00:00:00Z',
      }),
      catalogHandler(),
      http.post('/api/v1/billing/cancel', () =>
        HttpResponse.json({ detail: 'provider_unavailable' }, { status: 502 }),
      ),
    );

    renderWithProviders(<BillingSettings />);
    await user.click(await screen.findByRole('button', { name: /cancel at period end/i }));
    const dialog = screen.getByRole('dialog');
    await user.click(within(dialog).getByRole('button', { name: /cancel at period end/i }));

    expect(await within(dialog).findByText('provider_unavailable')).toBeInTheDocument();
  });
});
