/**
 * commerceApi contract tests (Commerce workspace): the catalog-health read
 * path and fail-loud strict validation. Transport is stubbed at global fetch
 * (mirrors products.test.ts).
 */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const UUID = '11111111-1111-4111-8111-111111111111';
const UUID2 = '22222222-2222-4222-8222-222222222222';
const UUID3 = '33333333-3333-4333-8333-333333333333';

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'content-type': 'application/json' },
  });
}

const catalogHealth = {
  project_id: UUID2,
  connections: [
    {
      connection_id: UUID,
      provider: 'shopify',
      label: 'Acme shop',
      account_ref: 'acme.myshopify.com',
      grant_status: 'connected',
      last_synced_at: '2026-07-24T06:00:00Z',
      latest_sync: {
        sync_run_id: UUID3,
        connection_id: UUID,
        status: 'succeeded',
        window_start: '2026-07-24T05:00:00Z',
        window_end: '2026-07-24T06:00:00Z',
        row_count: 128,
        error_code: '',
        completed_at: '2026-07-24T06:00:00Z',
      },
    },
  ],
  products: [
    {
      product_id: UUID2,
      connection_id: UUID,
      external_item_ref: 'gid://shopify/Product/1',
      sync_run_id: UUID3,
      status: 'warning',
      highest_severity: 'warning',
      issue_count: 2,
      rule_ids: ['price_missing'],
      last_seen_in_feed: true,
    },
  ],
  generated_at: '2026-07-24T06:05:00Z',
};

describe('commerceApi', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('reads the catalog-health projection at the project-scoped path', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(catalogHealth));
    vi.stubGlobal('fetch', fetchMock);

    const { commerceApi } = await import('./commerce');
    const health = await commerceApi.getCatalogHealth(UUID2);

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      `/api/v1/projects/${UUID2}/commerce/catalog-health`,
    );
    expect(fetchMock.mock.calls[0]?.[1]?.method ?? 'GET').toBe('GET');
    expect(health.connections[0]?.latest_sync?.status).toBe('succeeded');
    expect(health.products[0]?.rule_ids).toEqual(['price_missing']);
  });

  it('accepts null latest_sync / generated_at (never synced)', async () => {
    const empty = {
      ...catalogHealth,
      connections: [{ ...catalogHealth.connections[0], latest_sync: null, last_synced_at: null }],
      products: [],
      generated_at: null,
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(empty));
    vi.stubGlobal('fetch', fetchMock);

    const { commerceApi } = await import('./commerce');
    const health = await commerceApi.getCatalogHealth(UUID2);
    expect(health.connections[0]?.latest_sync).toBeNull();
    expect(health.generated_at).toBeNull();
  });

  it('fails loud on contract drift (unknown feed status, bogus severity)', async () => {
    const drifted = {
      ...catalogHealth,
      products: [{ ...catalogHealth.products[0], status: 'degraded' }],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(drifted));
    vi.stubGlobal('fetch', fetchMock);

    const { commerceApi } = await import('./commerce');
    await expect(commerceApi.getCatalogHealth(UUID2)).rejects.toThrow(
      /API validation failure in commerce\.getCatalogHealth/,
    );
  });

  it('reads the latest typed audit comparison', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({
        id: UUID3,
        project_id: UUID2,
        audit_id: UUID,
        matcher_version: 'commerce-match-1',
        comparison_version: 'commerce-comparison-1',
        source_metric_ids: [],
        source_artifact_ids: [],
        items: [],
        created_at: '2026-07-24T06:00:00Z',
      }),
    );
    vi.stubGlobal('fetch', fetchMock);
    const { commerceApi } = await import('./commerce');
    await commerceApi.getComparison(UUID2);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      `/api/v1/projects/${UUID2}/commerce/comparisons`,
    );
    expect(fetchMock.mock.calls[0]?.[1]?.method ?? 'GET').toBe('GET');
  });
});
