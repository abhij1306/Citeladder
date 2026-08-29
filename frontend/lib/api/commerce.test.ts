import { afterEach, describe, expect, it, vi } from 'vitest';

import { COMMERCE_BUYER_PROMPT_REQUEST_TIMEOUT_MS } from '@/lib/config/operational';
import { commerceApi } from './commerce';
import { commerceCatalogSchema, shelfSchema } from './schemas/commerce-suite';

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe('Commerce replacement contracts', () => {
  it('keeps catalog provenance and empty persisted shelf states explicit', () => {
    const catalog = commerceCatalogSchema.parse({
      products: [],
      categories: [],
      projection_tasks: { queued: 1 },
    });
    expect(catalog.projection_tasks.queued).toBe(1);
    expect(
      shelfSchema.parse({
        target: null,
        selected_audit_id: null,
        snapshots: [],
        observations: [],
      }),
    ).toEqual({
      target: null,
      selected_audit_id: null,
      snapshots: [],
      observations: [],
    });
  });

  it('keeps model-backed buyer-prompt generation alive beyond the default API timeout', async () => {
    const projectId = '10000000-0000-4000-8000-000000000001';
    const targetId = '20000000-0000-4000-8000-000000000002';
    const timeoutSpy = vi.spyOn(AbortSignal, 'timeout');
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify([
            {
              id: '30000000-0000-4000-8000-000000000003',
              prompt_set_id: '40000000-0000-4000-8000-000000000004',
              target: { kind: 'category', id: targetId },
              text: 'best black leggings for everyday wear',
              enabled: false,
              approved_at: null,
            },
          ]),
          { status: 201, headers: { 'content-type': 'application/json' } },
        ),
      ),
    );

    await commerceApi.generateBuyerPrompts(projectId, [{ kind: 'category', id: targetId }], 5);

    expect(timeoutSpy).toHaveBeenCalledWith(COMMERCE_BUYER_PROMPT_REQUEST_TIMEOUT_MS);
  });
});
