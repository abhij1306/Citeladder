/**
 * productsApi contract tests (agentic commerce): request paths, query
 * building, the export URL helper, and fail-loud strict validation. Transport
 * is stubbed at global fetch (mirrors client.test.ts).
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

const product = {
  id: UUID,
  project_id: UUID2,
  sku: 'AC-VB500',
  name: 'Acme VoltBike 500',
  aliases: ['VoltBike'],
  variants: [{ name: 'Graphite / Standard', sku: 'AC-VB500-GR', price: 2499.0 }],
  price: 2499.0,
  currency: 'USD',
  url: 'https://acme.com/p/voltbike',
  attributes: { brand: 'Acme', category: 'E-Bikes' },
  origin: 'manual',
  connection_id: null,
  external_item_ref: null,
  last_seen_sync_run_id: null,
  completeness: { score: 0.75, present: 9, total: 12, missing: ['gtin', 'mpn', 'condition'] },
  created_at: '2026-07-15T00:00:00Z',
  updated_at: '2026-07-15T00:00:00Z',
};

// The analyzer-v2 fields every product visibility entry carries.
const entryV2 = {
  product_analyzer_version: 'product-analysis-2',
  win_rate: 0.4,
  price_mismatch_rate: 0.1,
  price_relation_counts: { match: 3, higher: 1, lower: 0 },
  attribute_dimension_frequency: { Facts: { Price: 2 } },
  buyer_destination_mix: {
    total: 1,
    by_kind: [{ merchant_kind: 'brand_site', count: 1 }],
    by_domain: [
      {
        merchant_domain: 'acme.com',
        merchant_name: 'Acme',
        merchant_kind: 'brand_site',
        count: 1,
      },
    ],
  },
  prompt_coverage: 0.5,
  frozen_prompt_context: [],
  conversation_themes: [],
  visibility_rate: 0.5,
  top_three_rate: 0.5,
  engine_coverage: 1,
};

const visibility = {
  project_id: UUID2,
  audit_id: UUID3,
  audit_status: 'completed',
  product_analyzer_version: 'product-analysis-2',
  product_scoring_rule_version: 'product-scoring-v1',
  total_mentions: 4,
  total_analyses: 2,
  summary: {
    products_tracked: 1,
    products_visible: 1,
    visibility_rate: 1,
    top_three_rate: 1,
    average_rank: 1,
  },
  products: [
    {
      product_id: UUID,
      sku: 'AC-VB500',
      name: 'Acme VoltBike 500',
      category: 'E-Bikes',
      mention_count: 2,
      sov_share: 0.5,
      avg_rank: 1.0,
      rank_distribution: { top_1: 2, top_2_3: 0, top_4_5: 0, rank_6_plus: 0, unranked: 0 },
      price_mention_count: 2,
      price_accuracy_rate: 1.0,
      visibility_delta: 0.25,
      ...entryV2,
    },
  ],
  citation_comparison: { status: 'no_citations', limitation: '', categories: [] },
  created_at: '2026-07-15T00:00:00Z',
};

const evidence = {
  items: [
    {
      evidence_id: UUID,
      analysis_id: UUID,
      evidence_kind: 'product_mention',
      audit_id: UUID3,
      task_id: UUID2,
      artifact_id: UUID,
      logical_engine: 'gemini',
      transport_model: 'gemini-2.5-pro',
      prompt_text: 'best option 0',
      prompt_index: 0,
      repetition: 0,
      product_analyzer_version: 'product-analysis-2',
      matched_name: 'Acme VoltBike 500',
      matched_sku: 'AC-VB500',
      created_at: '2026-07-15T00:00:00Z',
      first_offset: 4,
      rank_position: 1,
      price_value: 2499.0,
      price_matches_catalog: true,
      price_relation: 'match',
      price_text: '$2,499.00',
      price_currency: 'USD',
      attribute_dimension: null,
      attribute_group: null,
      attribute_text: null,
      attribute_offset: null,
      merchant_name: null,
      merchant_domain: null,
      merchant_kind: null,
      destination_url: null,
    },
  ],
  truncated: false,
};

describe('productsApi', () => {
  beforeEach(() => {
    vi.resetModules();
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('lists the catalog at the project-scoped path', async () => {
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([product]));
    vi.stubGlobal('fetch', fetchMock);

    const { productsApi } = await import('./products');
    const rows = await productsApi.list(UUID2);

    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`/api/v1/projects/${UUID2}/products`);
    expect(rows).toHaveLength(1);
    expect(rows[0]?.completeness.missing).toContain('gtin');
  });

  it('creates / updates / removes a product on the flat paths', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(product, 201))
      .mockResolvedValueOnce(jsonResponse(product))
      .mockResolvedValueOnce(new Response(null, { status: 204 }));
    vi.stubGlobal('fetch', fetchMock);

    const { productsApi } = await import('./products');
    const input = { sku: 'AC-VB500', name: 'Acme VoltBike 500', currency: 'usd' };
    await productsApi.create(UUID2, input);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`/api/v1/projects/${UUID2}/products`);
    expect(fetchMock.mock.calls[0]?.[1]?.method).toBe('POST');
    expect(JSON.parse(String(fetchMock.mock.calls[0]?.[1]?.body))).toEqual(input);

    await productsApi.update(UUID, { price: 2399.0 });
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(`/api/v1/products/${UUID}`);
    expect(fetchMock.mock.calls[1]?.[1]?.method).toBe('PATCH');

    await productsApi.remove(UUID);
    expect(String(fetchMock.mock.calls[2]?.[0])).toBe(`/api/v1/products/${UUID}`);
    expect(fetchMock.mock.calls[2]?.[1]?.method).toBe('DELETE');
  });

  it('imports CSV as FormData and rows as a { products } JSON body (D1 summary)', async () => {
    const importResponse = {
      items: [product],
      summary: {
        created: 1,
        updated: 0,
        skipped: 1,
        errors: [
          {
            row: 3,
            field: 'sku',
            message: "Duplicate sku 'AC-VB500' in this import — the first occurrence was kept",
          },
        ],
      },
    };
    const fetchMock = vi
      .fn()
      .mockImplementation(() => Promise.resolve(jsonResponse(importResponse, 201)));
    vi.stubGlobal('fetch', fetchMock);

    const { productsApi } = await import('./products');
    const csvResult = await productsApi.importCsv(
      UUID2,
      new File(['sku,name\nAC-VB500,Acme'], 'products.csv'),
    );
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`/api/v1/projects/${UUID2}/products/import`);
    expect(fetchMock.mock.calls[0]?.[1]?.body).toBeInstanceOf(FormData);
    // D1: the refreshed catalog plus the per-row outcome summary.
    expect(csvResult.items).toHaveLength(1);
    expect(csvResult.summary.created).toBe(1);
    expect(csvResult.summary.skipped).toBe(1);
    expect(csvResult.summary.errors[0]).toMatchObject({ row: 3, field: 'sku' });

    const rows = [{ sku: 'AC-VB500', name: 'Acme VoltBike 500' }];
    const rowsResult = await productsApi.importRows(UUID2, rows);
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(`/api/v1/projects/${UUID2}/products/import`);
    expect(JSON.parse(String(fetchMock.mock.calls[1]?.[1]?.body))).toEqual({ products: rows });
    expect(rowsResult.summary.created).toBe(1);
  });

  it('reads the frozen-audit delete-guard check for one product (D4)', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(jsonResponse({ product_id: UUID, referenced: true, audit_count: 2 }));
    vi.stubGlobal('fetch', fetchMock);

    const { productsApi } = await import('./products');
    const references = await productsApi.getAuditReferences(UUID);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(`/api/v1/products/${UUID}/audit-references`);
    expect(references.referenced).toBe(true);
    expect(references.audit_count).toBe(2);
  });

  it('builds the visibility path with an optional audit_id query', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(visibility)));
    vi.stubGlobal('fetch', fetchMock);

    const { productsApi } = await import('./products');
    const latest = await productsApi.getProductVisibility(UUID2);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      `/api/v1/projects/${UUID2}/products/visibility`,
    );
    expect(latest.audit_status).toBe('completed');
    expect(latest.products[0]?.sov_share).toBe(0.5);

    await productsApi.getProductVisibility(UUID2, { audit_id: UUID3 });
    expect(String(fetchMock.mock.calls[1]?.[0])).toBe(
      `/api/v1/projects/${UUID2}/products/visibility?audit_id=${UUID3}`,
    );

    await productsApi.getProductVisibility(UUID2, { audit_id: UUID3, engine: 'gemini' });
    const slicedUrl = String(fetchMock.mock.calls[2]?.[0]);
    const sliced = new URLSearchParams(slicedUrl.split('?')[1]);
    expect(sliced.get('audit_id')).toBe(UUID3);
    expect(sliced.get('engine')).toBe('gemini');
  });

  it('reads the three-point product visibility trend', async () => {
    const trend = {
      project_id: UUID2,
      product_id: UUID,
      sku: 'AC-VB500',
      name: 'Acme VoltBike 500',
      points: [
        {
          audit_id: UUID3,
          observed_at: '2026-07-15T00:00:00Z',
          visibility_rate: 0.5,
          top_three_rate: 0.5,
          average_rank: 1,
        },
      ],
    };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(trend));
    vi.stubGlobal('fetch', fetchMock);
    const { productsApi } = await import('./products');
    await productsApi.getProductVisibilityTrend(UUID2, UUID, 'gemini');
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      `/api/v1/projects/${UUID2}/products/visibility/trends?product_id=${UUID}&engine=gemini`,
    );
  });

  it('builds the evidence path with audit/engine/limit filters', async () => {
    const fetchMock = vi.fn().mockImplementation(() => Promise.resolve(jsonResponse(evidence)));
    vi.stubGlobal('fetch', fetchMock);

    const { productsApi } = await import('./products');
    const unfiltered = await productsApi.getProductEvidence(UUID);
    expect(String(fetchMock.mock.calls[0]?.[0])).toBe(
      `/api/v1/products/${UUID}/visibility/evidence`,
    );
    expect(unfiltered.truncated).toBe(false);
    expect(unfiltered.items[0]?.price_matches_catalog).toBe(true);

    await productsApi.getProductEvidence(UUID, {
      audit_id: UUID3,
      engine: 'gemini',
      limit: 50,
    });
    const url = String(fetchMock.mock.calls[1]?.[0]);
    expect(url.startsWith(`/api/v1/products/${UUID}/visibility/evidence?`)).toBe(true);
    const params = new URLSearchParams(url.split('?')[1]);
    expect(params.get('audit_id')).toBe(UUID3);
    expect(params.get('engine')).toBe('gemini');
    expect(params.get('limit')).toBe('50');
  });

  it('builds same-origin export URLs with audit/engine params', async () => {
    const { productsApi } = await import('./products');
    expect(productsApi.exportCsvUrl(UUID2)).toBe(
      `/api/v1/projects/${UUID2}/products/visibility/export.csv`,
    );
    expect(productsApi.exportCsvUrl(UUID2, { audit_id: UUID3 })).toBe(
      `/api/v1/projects/${UUID2}/products/visibility/export.csv?audit_id=${UUID3}`,
    );
    const sliced = new URLSearchParams(
      productsApi.exportCsvUrl(UUID2, { audit_id: UUID3, engine: 'gemini' }).split('?')[1],
    );
    expect(sliced.get('audit_id')).toBe(UUID3);
    expect(sliced.get('engine')).toBe('gemini');
  });

  it('fails loud on contract drift (numeric id, missing completeness)', async () => {
    const drifted = { ...product, id: 7 };
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse([drifted]));
    vi.stubGlobal('fetch', fetchMock);

    const { productsApi } = await import('./products');
    await expect(productsApi.list(UUID2)).rejects.toThrow(
      /API validation failure in products\.list/,
    );

    const incomplete = { ...product };
    delete (incomplete as Record<string, unknown>).completeness;
    const { strictValidate, productSchema } = await import('./schemas');
    expect(() => strictValidate(productSchema, incomplete, 't')).toThrow(
      /API validation failure in t/,
    );
  });
});
