import { z } from 'zod';

import { apiClient, type ApiRequestOptions } from './client';
import {
  brandDiscoveryCatalogSchema,
  brandDiscoveryCompleteSchema,
  brandDiscoverySchema,
  strictValidate,
} from './schemas';

export type BrandDiscovery = z.infer<typeof brandDiscoverySchema>;
export type BrandDiscoveryInput = {
  brand_name: string;
  website_url: string;
  industry?: string;
  subindustry?: string;
  primary_market: string;
  language_code?: string;
};

export type DiscoveryProfile = {
  description: string;
  positioning: string;
  products_services: string[];
  target_audience: string;
  industry: string;
  business_type: 'b2b' | 'b2c' | 'both';
  price_tier: string;
  field_confidence: Record<string, number>;
  /**
   * The resolved business context. `category` and `category_terms` are open
   * vocabulary and decide what the generated questions are about; the rest are
   * closed facets that select which kinds of question apply. This replaces the
   * industry / sub-industry pair the user used to pick from a dropdown.
   */
  category: string;
  /** Alternative phrasings offered as choices, so the user picks instead of types. */
  category_options: string[];
  category_aliases: string[];
  category_terms: string[];
  jobs_to_be_done: string[];
  sector: string;
  business_model: string;
  secondary_business_models: string[];
  market_scope: 'global' | 'national' | 'regional' | 'local';
  buyer_register: string;
  buyer_roles: string[];
  service_areas: string[];
  /** How much the model actually recognised the brand; drives the thin-data notice. */
  knowledge_strength: 'strong' | 'weak' | 'none';
};

type DiscoveryCompetitor = { name: string; aliases: string[]; domains: string[] };
export type BrandDiscoveryCompletion = {
  name: string;
  profile: DiscoveryProfile;
  domains: string[];
  competitors: DiscoveryCompetitor[];
};

export const brandDiscoveriesApi = {
  catalog: async (options?: ApiRequestOptions) => {
    const value = await apiClient.get('/brand-discovery-catalog', options);
    return strictValidate(brandDiscoveryCatalogSchema, value, 'brandDiscovery.catalog');
  },
  create: async (input: BrandDiscoveryInput, idempotencyKey: string) => {
    const value = await apiClient.post('/brand-discoveries', input, {
      idempotencyKey,
      retryNetworkFailures: true,
    });
    return strictValidate(brandDiscoverySchema, value, 'brandDiscovery.create');
  },
  get: async (id: string, options?: ApiRequestOptions) => {
    const value = await apiClient.get(`/brand-discoveries/${id}`, options);
    return strictValidate(brandDiscoverySchema, value, 'brandDiscovery.get');
  },
  complete: async (id: string, input: BrandDiscoveryCompletion, idempotencyKey: string) => {
    const value = await apiClient.post(`/brand-discoveries/${id}/complete`, input, {
      idempotencyKey,
      retryNetworkFailures: true,
    });
    return strictValidate(brandDiscoveryCompleteSchema, value, 'brandDiscovery.complete');
  },
};
