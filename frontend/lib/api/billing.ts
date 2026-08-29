/**
 * Billing domain endpoints (v8 commercial surface).
 *
 * The server owns every amount. A request from here carries a catalog key, a
 * quantity, a credential mode and an ISO country — never a price, a currency,
 * a margin, or an external provider/plan id (invariant 6). The activation
 * response's `quote` is what proves the terms the user was shown.
 *
 * Every commercial POST is idempotent: the caller supplies an
 * `Idempotency-Key` and a retry of the same key replays the stored response
 * rather than charging twice.
 */
import type { z } from 'zod';

import { apiClient, type ApiRequestOptions } from './client';
import {
  activationSchema,
  billingCatalogSchema,
  billingEntitlementSchema,
  billingUsageSchema,
  strictValidate,
  subscriptionChangeSchema,
} from './schemas';

export type BillingCatalog = z.infer<typeof billingCatalogSchema>;
export type CatalogPlan = BillingCatalog['plans'][number];
export type CatalogAddon = BillingCatalog['addons'][number];
export type CatalogTopup = BillingCatalog['topups'][number];
export type CatalogProvider = BillingCatalog['providers'][number];
export type BillingEntitlement = z.infer<typeof billingEntitlementSchema>;
type BillingUsage = z.infer<typeof billingUsageSchema>;
export type UsageItem = BillingUsage['items'][number];
export type CredentialMode = 'byok' | 'funded';
export type SelfServePlanKey = 'tier_1' | 'tier_2' | 'tier_3';

/**
 * A fresh idempotency key for one commercial intent.
 *
 * Mirrors `createRequestId` in `client.ts`. The key is a per-account
 * uniqueness token, not a secret or a capability — it authorizes nothing on
 * its own, and the backend scopes every lookup to the authenticated account.
 * `crypto.randomUUID` is the real path in every supported browser; the suffix
 * fallback only keeps a non-crypto test environment from throwing.
 */
export function createIdempotencyKey(): string {
  return (
    globalThis.crypto?.randomUUID?.() ??
    `intent-${Date.now()}-${Math.random().toString(16).slice(2)}`
  );
}

export type SubscriptionCheckoutInput = {
  catalog_key: SelfServePlanKey;
  credential_mode: CredentialMode;
  country_code: string;
};

export const billingApi = {
  catalog: async (countryCode?: string, options?: ApiRequestOptions) => {
    const query = countryCode ? `?country=${encodeURIComponent(countryCode)}` : '';
    const response = await apiClient.get<unknown>(`/billing/catalog${query}`, options);
    return strictValidate(billingCatalogSchema, response, 'billing.catalog');
  },

  entitlement: async (options?: ApiRequestOptions) => {
    const response = await apiClient.get<unknown>('/billing/entitlement', options);
    return strictValidate(billingEntitlementSchema, response, 'billing.entitlement');
  },

  usage: async (options?: ApiRequestOptions) => {
    const response = await apiClient.get<unknown>('/billing/usage', options);
    return strictValidate(billingUsageSchema, response, 'billing.usage');
  },

  /**
   * Start a base-plan checkout. `trial_requested` is always false in this
   * release — the backend answers `trial_unavailable` for anything else, so
   * there is no trial UI to expose.
   */
  createSubscription: async (
    input: SubscriptionCheckoutInput,
    idempotencyKey: string,
    options?: ApiRequestOptions,
  ) => {
    const response = await apiClient.post<unknown>(
      '/billing/subscriptions',
      { ...input, trial_requested: false },
      { ...options, idempotencyKey },
    );
    return strictValidate(activationSchema, response, 'billing.createSubscription');
  },

  activateAddon: async (
    catalogKey: string,
    quantity: number,
    idempotencyKey: string,
    options?: ApiRequestOptions,
  ) => {
    const response = await apiClient.post<unknown>(
      '/billing/addons',
      { catalog_key: catalogKey, quantity },
      { ...options, idempotencyKey },
    );
    return strictValidate(activationSchema, response, 'billing.activateAddon');
  },

  purchaseTopup: async (
    catalogKey: string,
    quantity: number,
    idempotencyKey: string,
    options?: ApiRequestOptions,
  ) => {
    const response = await apiClient.post<unknown>(
      '/billing/topups',
      { catalog_key: catalogKey, quantity },
      { ...options, idempotencyKey },
    );
    return strictValidate(activationSchema, response, 'billing.purchaseTopup');
  },

  /**
   * Deactivation has its OWN response vocabulary. Parsing it through the
   * activation state machine would invent a pending/failed lifecycle the
   * backend never reports.
   */
  deactivateAddon: async (catalogKey: string, options?: ApiRequestOptions) => {
    const response = await apiClient.delete<unknown>(
      `/billing/addons/${encodeURIComponent(catalogKey)}`,
      options,
    );
    return strictValidate(subscriptionChangeSchema, response, 'billing.deactivateAddon');
  },

  cancelSubscription: async (options?: ApiRequestOptions) => {
    const response = await apiClient.delete<unknown>('/billing/subscription', options);
    return strictValidate(subscriptionChangeSchema, response, 'billing.cancelSubscription');
  },
};
