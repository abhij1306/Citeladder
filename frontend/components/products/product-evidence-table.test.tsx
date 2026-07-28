/**
 * Product evidence drill-down: one bounded query feeds three kind-sliced
 * sub-tab panels (mentions | attributes | destinations). Per the C4 spec:
 * every kind renders only its applicable fields, nulls render —, the
 * destination URL opens safely (already sanitized by the backend), and the
 * truncation notice stays visible. MSW stubs the persisted projection.
 */
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import type { Product } from '@/lib/api/types';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

import { ProductEvidenceTable } from './product-evidence-table';

const PRODUCT_ID = '11111111-1111-4111-8111-111111111111';
const EVIDENCE_URL = `/api/v1/products/${PRODUCT_ID}/visibility/evidence`;

const product = {
  id: PRODUCT_ID,
  project_id: '22222222-2222-4222-8222-222222222222',
  sku: 'AC-VB500',
  name: 'Acme VoltBike 500',
  aliases: [],
  variants: [],
  price: 2499.0,
  currency: 'USD',
  url: 'https://acme.com/p/voltbike',
  attributes: { brand: 'Acme' },
  origin: 'manual',
  connection_id: null,
  external_item_ref: null,
  last_seen_sync_run_id: null,
  completeness: { score: 1, present: 12, total: 12, missing: [] },
  created_at: '2026-07-15T00:00:00Z',
  updated_at: '2026-07-15T00:00:00Z',
} as unknown as Product;

// One pinned-shape row per evidence kind (kind-specific fields null on the
// other kinds, exactly as the backend emits them).
function evidenceItem(kind: string, id: string) {
  const base = {
    evidence_id: id,
    analysis_id: '44444444-4444-4444-8444-444444444444',
    evidence_kind: kind,
    audit_id: '55555555-5555-4555-8555-555555555555',
    task_id: '66666666-6666-4666-8666-666666666666',
    artifact_id: null,
    logical_engine: 'gemini',
    transport_model: 'gemini-2.5-pro',
    prompt_text: `prompt for ${kind}`,
    prompt_index: 0,
    repetition: 1,
    product_analyzer_version: 'product-analysis-2',
    shopping_surface: '',
    matched_name: 'Acme VoltBike 500',
    matched_sku: 'AC-VB500',
    created_at: '2026-07-15T00:00:00Z',
    first_offset: null,
    rank_position: null,
    price_value: null,
    price_matches_catalog: null,
    price_relation: null,
    price_text: '',
    price_currency: 'USD',
    attribute_dimension: null,
    attribute_group: null,
    attribute_text: null,
    attribute_offset: null,
    merchant_name: null,
    merchant_domain: null,
    merchant_kind: null,
    destination_url: null,
  };
  if (kind === 'product_mention') {
    return {
      ...base,
      first_offset: 118,
      rank_position: 2,
      price_value: 2499.0,
      price_matches_catalog: true,
      price_relation: 'match',
      price_text: '$2,499.00',
    };
  }
  if (kind === 'attribute_mention') {
    return {
      ...base,
      attribute_dimension: 'Waterproofing',
      attribute_group: 'Characteristics',
      attribute_text: 'fully waterproof membrane',
      attribute_offset: 88,
    };
  }
  return {
    ...base,
    price_value: 2549.0,
    price_text: '$2,549.00',
    merchant_name: 'Acme Corp',
    merchant_domain: 'acme.example',
    merchant_kind: 'brand_site',
    destination_url: 'https://acme.example/products/acme-voltbike-500',
  };
}

const evidence = {
  items: [
    evidenceItem('product_mention', 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa'),
    evidenceItem('attribute_mention', 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb'),
    evidenceItem('buyer_destination', 'cccccccc-cccc-4ccc-8ccc-cccccccccccc'),
  ],
  truncated: true,
};

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

function renderTable() {
  return renderWithProviders(<ProductEvidenceTable product={product} />);
}

describe('ProductEvidenceTable kind sub-tabs', () => {
  it('defaults to the mentions panel with rank/price/relation/offset/execution', async () => {
    mswServer.use(http.get(EVIDENCE_URL, () => HttpResponse.json(evidence)));
    renderTable();

    await waitFor(() => expect(screen.getByText('prompt for product_mention')).toBeInTheDocument());

    // The nested tablist defaults to Mentions; only its panel renders.
    expect(screen.getByRole('tab', { name: 'Mentions' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByText('#2')).toBeInTheDocument();
    expect(screen.getByText('$2,499.00')).toBeInTheDocument();
    expect(screen.getByText('Match')).toBeInTheDocument();
    expect(screen.getByText('118')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Open' })).toHaveAttribute(
      'href',
      '/runs/55555555-5555-4555-8555-555555555555/executions/66666666-6666-4666-8666-666666666666',
    );
    // Other kinds' rows are not in the mentions panel.
    expect(screen.queryByText('Waterproofing')).not.toBeInTheDocument();
    expect(screen.queryByText('Acme Corp')).not.toBeInTheDocument();
  });

  it('shows dimension, group, exact text, and offset on the attributes panel', async () => {
    const user = userEvent.setup();
    mswServer.use(http.get(EVIDENCE_URL, () => HttpResponse.json(evidence)));
    renderTable();

    await waitFor(() => expect(screen.getByText('prompt for product_mention')).toBeInTheDocument());
    await user.click(screen.getByRole('tab', { name: 'Attributes' }));

    expect(screen.getByText('Waterproofing')).toBeInTheDocument();
    expect(screen.getByText('Characteristics')).toBeInTheDocument();
    expect(screen.getByText('“fully waterproof membrane”')).toBeInTheDocument();
    expect(screen.getByText('88')).toBeInTheDocument();
    // Mentions-only columns are gone.
    expect(screen.queryByText('vs catalog')).not.toBeInTheDocument();
  });

  it('shows merchant, kind, the sanitized URL (safe target), and price on destinations', async () => {
    const user = userEvent.setup();
    mswServer.use(http.get(EVIDENCE_URL, () => HttpResponse.json(evidence)));
    renderTable();

    await waitFor(() => expect(screen.getByText('prompt for product_mention')).toBeInTheDocument());
    await user.click(screen.getByRole('tab', { name: 'Destinations' }));

    expect(screen.getByText('Acme Corp')).toBeInTheDocument();
    expect(screen.getByText('acme.example')).toBeInTheDocument();
    expect(screen.getByText('Brand site')).toBeInTheDocument();
    const link = screen.getByRole('link', {
      name: 'https://acme.example/products/acme-voltbike-500',
    });
    expect(link).toHaveAttribute('target', '_blank');
    expect(link).toHaveAttribute('rel', expect.stringContaining('noopener'));
    expect(screen.getByText('$2,549.00')).toBeInTheDocument();
  });

  it('keeps the truncation notice visible per panel', async () => {
    const user = userEvent.setup();
    mswServer.use(http.get(EVIDENCE_URL, () => HttpResponse.json(evidence)));
    renderTable();

    await waitFor(() => expect(screen.getByText('prompt for product_mention')).toBeInTheDocument());
    expect(screen.getAllByText('Truncated').length).toBeGreaterThan(0);
    expect(screen.getByText(/older mentions are truncated/)).toBeInTheDocument();

    await user.click(screen.getByRole('tab', { name: 'Destinations' }));
    expect(
      screen.getByText(/buyer destinations for this product; the rest are truncated/),
    ).toBeInTheDocument();
  });

  it('renders the empty copy per kind when nothing persisted', async () => {
    mswServer.use(http.get(EVIDENCE_URL, () => HttpResponse.json({ items: [], truncated: false })));
    renderTable();

    await waitFor(() =>
      expect(screen.getByText(/No mentions of this product yet/)).toBeInTheDocument(),
    );
  });

  it('sends engine + surface + limit on the evidence request', async () => {
    const user = userEvent.setup();
    const urls: string[] = [];
    mswServer.use(
      http.get(EVIDENCE_URL, ({ request }) => {
        urls.push(request.url);
        return HttpResponse.json({ items: [], truncated: false });
      }),
    );
    renderTable();

    await waitFor(() => expect(urls.length).toBeGreaterThan(0));
    const params = new URL(urls[0]!).searchParams;
    expect(params.get('limit')).toBe('100');
    expect(params.get('surface')).toBe('');

    await user.click(screen.getByRole('button', { name: 'Filter by engine' }));
    await user.click(screen.getByRole('menuitem', { name: 'Gemini' }));
    await waitFor(() => expect(urls.length).toBeGreaterThan(1));
    expect(new URL(urls.at(-1)!).searchParams.get('engine')).toBe('gemini');
  });
});
