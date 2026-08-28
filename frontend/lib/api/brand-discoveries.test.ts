import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { mswServer } from '@/test/msw-server';

import { brandDiscoveriesApi, type BrandDiscoveryCompletion } from './brand-discoveries';

const DISCOVERY_ID = '11111111-1111-4111-8111-111111111111';
const CRAWL_ID = '33333333-3333-4333-8333-333333333333';

const completion: BrandDiscoveryCompletion = {
  name: 'Acme',
  profile: {
    description: 'A commerce platform',
    positioning: 'Reliable product data',
    products_services: ['Product feeds'],
    target_audience: 'Retailers',
    industry: 'Commerce software',
    business_type: 'b2b',
    price_tier: 'premium',
    field_confidence: {},
    category: 'product feed management platform',
    category_options: [],
    category_aliases: [],
    category_terms: ['product feed management'],
    jobs_to_be_done: [],
    sector: 'Software',
    business_model: 'b2b_saas',
    secondary_business_models: [],
    market_scope: 'global',
    buyer_register: 'research_comparative',
    buyer_roles: [],
    service_areas: [],
    knowledge_strength: 'strong',
  },
  domains: ['acme.example'],
  competitors: [{ name: 'Globex', aliases: [], domains: ['globex.example'] }],
};

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

describe('brand discovery completion contract', () => {
  it('sends confirmed ICP once with an idempotency key and validates activation identity', async () => {
    let body: unknown;
    let idempotencyKey: string | null = null;
    mswServer.use(
      http.post(`/api/v1/brand-discoveries/${DISCOVERY_ID}/complete`, async ({ request }) => {
        body = await request.json();
        idempotencyKey = request.headers.get('Idempotency-Key');
        return HttpResponse.json(
          {
            discovery_id: DISCOVERY_ID,
            status: 'completing',
            project_id: null,
            crawl_id: CRAWL_ID,
            activation_state: 'queued',
            page_limit: 10,
            warnings: [],
          },
          { status: 202 },
        );
      }),
    );

    // Completion is accepted as a job: the project id arrives via the
    // discovery poll, not in this response.
    await expect(
      brandDiscoveriesApi.complete(DISCOVERY_ID, completion, 'complete-once'),
    ).resolves.toEqual({
      discovery_id: DISCOVERY_ID,
      status: 'completing',
      project_id: null,
      crawl_id: CRAWL_ID,
      activation_state: 'queued',
      page_limit: 10,
      warnings: [],
    });
    expect(idempotencyKey).toBe('complete-once');
    expect(body).toEqual(completion);
    expect(JSON.stringify(body)).not.toContain('prompt_groups');
  });
});
