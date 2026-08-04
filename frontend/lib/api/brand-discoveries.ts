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

type DiscoveryProfile = {
  description: string;
  positioning: string;
  products_services: string[];
  target_audience: string;
  industry: string;
  business_type: 'b2b' | 'b2c' | 'both';
  price_tier: string;
  field_confidence: Record<string, number>;
};

type DiscoveryCompetitor = { name: string; aliases: string[]; domains: string[] };
type DiscoveryPrompt = {
  text: string;
  intent: 'discovery' | 'comparison' | 'purchase' | 'service' | 'local';
  cohort: 'market_visibility' | 'brand_diagnostic';
};

export type BrandDiscoveryCompletion = {
  name: string;
  profile: DiscoveryProfile;
  domains: string[];
  competitors: DiscoveryCompetitor[];
  prompt_groups: Array<{
    topic: string;
    prompts: DiscoveryPrompt[];
  }>;
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
