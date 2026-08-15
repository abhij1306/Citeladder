import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { mswServer } from '@/test/msw-server';

import { brandDiscoveriesApi, type BrandDiscoveryCompletion } from './brand-discoveries';

const DISCOVERY_ID = '11111111-1111-4111-8111-111111111111';
const PROJECT_ID = '22222222-2222-4222-8222-222222222222';
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
            project_id: PROJECT_ID,
            crawl_id: CRAWL_ID,
            activation_state: 'queued',
            page_limit: 10,
            warnings: [],
          },
          { status: 201 },
        );
      }),
    );

    await expect(
      brandDiscoveriesApi.complete(DISCOVERY_ID, completion, 'complete-once'),
    ).resolves.toEqual({
      project_id: PROJECT_ID,
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
