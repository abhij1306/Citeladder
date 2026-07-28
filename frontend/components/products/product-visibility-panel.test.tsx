import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ApiError } from '@/lib/api/errors';
import { queryKeys } from '@/lib/api/query-keys';
import type { ProductVisibility, ProductVisibilityEntry } from '@/lib/api/types';
import type { useProductVisibilityQueries } from '@/lib/products/use-products-screen';

import { ProductVisibilityPanel } from './product-visibility-panel';

type VisibilityQueries = ReturnType<typeof useProductVisibilityQueries>;

const PROJECT = '11111111-1111-4111-8111-111111111111';
const PRODUCT = '22222222-2222-4222-8222-222222222222';
const COMPETITOR_PRODUCT = '33333333-3333-4333-8333-333333333333';

function makeQueries(overrides: Record<string, unknown> = {}): VisibilityQueries {
  return {
    auditsQuery: { isLoading: false },
    runOptions: [],
    activeRunId: null,
    selectRun: vi.fn(),
    engine: 'all',
    setEngine: vi.fn(),
    engineParam: undefined,
    surface: '',
    setSurface: vi.fn(),
    visibilityQuery: { isLoading: false, isError: false, data: undefined },
    ...overrides,
  } as unknown as VisibilityQueries;
}

function ownEntry(overrides: Partial<ProductVisibilityEntry> = {}): ProductVisibilityEntry {
  return {
    product_id: PRODUCT,
    sku: 'AC-VB500',
    name: 'Acme VoltBike 500',
    mention_count: 2,
    sov_share: 0.5,
    avg_rank: 1.0,
    rank_distribution: { top_1: 2, top_2_3: 0, top_4_5: 0, rank_6_plus: 0, unranked: 0 },
    price_mention_count: 2,
    price_accuracy_rate: 1.0,
    product_analyzer_version: 'product-analysis-2',
    win_rate: 0.34,
    price_mismatch_rate: 0.1,
    price_relation_counts: { match: 5, higher: 2, lower: 1 },
    attribute_dimension_frequency: { Facts: { Price: 3, Sizing: 1 } },
    buyer_destination_mix: {
      total: 3,
      by_kind: [
        { merchant_kind: 'brand_site', count: 2 },
        { merchant_kind: 'marketplace', count: 1 },
      ],
      by_domain: [
        {
          merchant_domain: 'acme.com',
          merchant_name: 'Acme',
          merchant_kind: 'brand_site',
          count: 2,
        },
        {
          merchant_domain: 'marketplace.example',
          merchant_name: 'Marketplace',
          merchant_kind: 'marketplace',
          count: 1,
        },
      ],
    },
    competitor_co_placement: {
      items: [
        {
          competitor_product_id: COMPETITOR_PRODUCT,
          competitor_name: 'Globex',
          product_name: 'Globex CityBike 450',
          count: 4,
        },
      ],
      truncated: true,
    },
    ...overrides,
  };
}

function makeVisibility(overrides: Partial<ProductVisibility> = {}): ProductVisibility {
  return {
    project_id: PROJECT,
    audit_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    audit_status: 'completed',
    product_analyzer_version: 'product-analysis-2',
    product_scoring_rule_version: 'product-scoring-v1',
    total_mentions: 4,
    total_analyses: 2,
    products: [ownEntry()],
    competitor_products: [
      {
        competitor_product_id: COMPETITOR_PRODUCT,
        competitor_name: 'Globex',
        name: 'Globex CityBike 450',
        mention_count: 2,
        sov_share: 0.5,
        avg_rank: 2.0,
        rank_distribution: { top_1: 0, top_2_3: 2, top_4_5: 0, rank_6_plus: 0, unranked: 0 },
        price_mention_count: 2,
        price_accuracy_rate: null,
        product_analyzer_version: 'product-analysis-2',
        win_rate: null,
        price_mismatch_rate: null,
        price_relation_counts: {},
        attribute_dimension_frequency: {},
        buyer_destination_mix: { total: 0, by_kind: [], by_domain: [] },
        competitor_co_placement: { items: [], truncated: false },
      },
    ],
    available_surfaces: ['', 'chatgpt-shopping'],
    created_at: '2026-07-15T00:00:00Z',
    ...overrides,
  };
}

function renderPanel(queries: VisibilityQueries) {
  return render(
    <ProductVisibilityPanel projectId={PROJECT} queries={queries} onGoToCatalog={() => {}} />,
  );
}

function renderWithData(data: ProductVisibility = makeVisibility()) {
  return renderPanel(makeQueries({ visibilityQuery: { isLoading: false, isError: false, data } }));
}

describe('ProductVisibilityPanel states', () => {
  it('renders a loading skeleton while the projection loads', () => {
    const { container } = render(
      <ProductVisibilityPanel
        projectId={PROJECT}
        queries={makeQueries({ visibilityQuery: { isLoading: true, isError: false } })}
        onGoToCatalog={() => {}}
      />,
    );
    expect(screen.queryByText('Product rankings')).not.toBeInTheDocument();
    expect(container.querySelectorAll('[aria-hidden]').length).toBeGreaterThan(0);
  });

  it('renders the no-audit empty state with a catalog CTA on a 404', () => {
    const onGoToCatalog = vi.fn();
    render(
      <ProductVisibilityPanel
        projectId={PROJECT}
        queries={makeQueries({
          visibilityQuery: {
            isLoading: false,
            isError: true,
            error: new ApiError('not found', 404, '', 'req-1'),
          },
        })}
        onGoToCatalog={onGoToCatalog}
      />,
    );
    expect(screen.getByText('No product visibility yet')).toBeInTheDocument();
    screen.getByRole('button', { name: /Go to Catalog/ }).click();
    expect(onGoToCatalog).toHaveBeenCalled();
  });

  it('keeps the run selector reachable on a 404 for an explicitly selected run', () => {
    // Regression: picking a run without product metrics used to swap the whole
    // panel for the empty state — the selection stuck (screen-level state) and
    // the only way back to "Latest" was a full page reload.
    render(
      <ProductVisibilityPanel
        projectId={PROJECT}
        queries={makeQueries({
          activeRunId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
          runOptions: [{ id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', label: 'Jul 24, 2026' }],
          visibilityQuery: {
            isLoading: false,
            isError: true,
            error: new ApiError('not found', 404, '', 'req-1'),
          },
        })}
        onGoToCatalog={() => {}}
      />,
    );
    expect(screen.getByText('No product visibility yet')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Select run' })).toBeInTheDocument();
    expect(screen.getByText(/No product metrics in this run/)).toBeInTheDocument();
  });

  it('hides the run selector on a 404 with no explicit run selection', () => {
    render(
      <ProductVisibilityPanel
        projectId={PROJECT}
        queries={makeQueries({
          visibilityQuery: {
            isLoading: false,
            isError: true,
            error: new ApiError('not found', 404, '', 'req-1'),
          },
        })}
        onGoToCatalog={() => {}}
      />,
    );
    expect(screen.getByText('No product visibility yet')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Select run' })).not.toBeInTheDocument();
  });

  it('renders the summary strip and both rankings tables with data', () => {
    renderWithData();

    // Summary strip (computed from the persisted projection).
    expect(screen.getByText('Product SOV')).toBeInTheDocument();
    // 50% appears both in the SOV card and the table SOV column.
    expect(screen.getAllByText('50%').length).toBeGreaterThan(0);
    expect(screen.getByText('Product mentions')).toBeInTheDocument();
    expect(screen.getByText('Avg rank in product lists')).toBeInTheDocument();
    expect(screen.getByText('Price-mention accuracy')).toBeInTheDocument();

    // Own + competitor sections.
    expect(screen.getByText('Product rankings')).toBeInTheDocument();
    expect(screen.getByText('Competitor products')).toBeInTheDocument();
    expect(screen.getByText('Acme VoltBike 500')).toBeInTheDocument();
    expect(screen.getByText('Globex CityBike 450')).toBeInTheDocument();
    expect(screen.getByText('You')).toBeInTheDocument();

    // The own product links to its evidence drill-down.
    expect(screen.getByRole('link', { name: 'Acme VoltBike 500' })).toHaveAttribute(
      'href',
      `/products/${PRODUCT}`,
    );
    // The rank-distribution bar exposes bucket counts non-visually.
    expect(screen.getByRole('img', { name: /Top 1: 2, Top 2–3: 0/ })).toBeInTheDocument();
  });

  it('renders win rate and price relation columns; nulls stay —', () => {
    renderWithData();

    // Win rate: 34% persisted for the own row; the competitor's null renders —.
    expect(screen.getByText('34%')).toBeInTheDocument();

    // v2 price relation badges render from persisted counts only.
    expect(screen.getByText('Match 5')).toBeInTheDocument();
    expect(screen.getByText('Higher 2')).toBeInTheDocument();
    expect(screen.getByText('Lower 1')).toBeInTheDocument();
  });

  it('reads Direction unavailable for a v1 row and shows the v1 alert', () => {
    renderWithData(
      makeVisibility({
        products: [
          ownEntry({
            product_analyzer_version: 'product-analysis-1',
            price_relation_counts: { match: 4, mismatch: 3 },
          }),
        ],
      }),
    );

    expect(screen.getByText('Direction unavailable')).toBeInTheDocument();
    // Never Higher/Lower for v1 — and the muted mismatch count sits beside it.
    expect(screen.queryByText(/Higher/)).not.toBeInTheDocument();
    expect(screen.getByText(/product analyzer v1/)).toBeInTheDocument();
  });

  it('defaults the run selector to Latest and the surface to Answer-engine APIs', () => {
    renderWithData();
    expect(screen.getByRole('button', { name: 'Select run' })).toHaveTextContent('Latest');
    expect(screen.getByRole('button', { name: 'Filter by surface' })).toHaveTextContent(
      'Answer-engine APIs',
    );
  });

  it('builds the export URL with the audit, engine, and surface slice', () => {
    renderPanel(
      makeQueries({
        activeRunId: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb',
        runOptions: [{ id: 'bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb', label: 'Jul 24, 2026' }],
        engine: 'gemini',
        engineParam: 'gemini',
        surface: 'chatgpt-shopping',
        visibilityQuery: { isLoading: false, isError: false, data: makeVisibility() },
      }),
    );
    const href = screen.getByRole('link', { name: /Export CSV/ }).getAttribute('href') ?? '';
    expect(href.startsWith(`/api/v1/projects/${PROJECT}/products/visibility/export.csv?`)).toBe(
      true,
    );
    const params = new URLSearchParams(href.split('?')[1]);
    expect(params.get('audit_id')).toBe('bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb');
    expect(params.get('engine')).toBe('gemini');
    expect(params.get('surface')).toBe('chatgpt-shopping');
  });

  it('lists the measurement surface plus configured surfaces verbatim', async () => {
    const user = userEvent.setup();
    renderWithData();
    await user.click(screen.getByRole('button', { name: 'Filter by surface' }));
    expect(screen.getByRole('menuitem', { name: 'Answer-engine APIs' })).toBeInTheDocument();
    expect(screen.getByRole('menuitem', { name: 'chatgpt-shopping' })).toBeInTheDocument();
    // There is deliberately no "All surfaces" aggregate option.
    expect(screen.queryByRole('menuitem', { name: /all surfaces/i })).not.toBeInTheDocument();
  });
});

describe('ProductVisibilityPanel sub-tabs', () => {
  it('shows the attribute frequency table grouped by group/dimension', async () => {
    const user = userEvent.setup();
    renderWithData();
    await user.click(screen.getByRole('tab', { name: 'Attributes' }));

    expect(screen.getByText('Attribute dimensions')).toBeInTheDocument();
    // Group header row + dimension rows with integer counts.
    expect(screen.getByRole('columnheader', { name: 'Facts' })).toBeInTheDocument();
    expect(screen.getByText('Price')).toBeInTheDocument();
    expect(screen.getByText('Sizing')).toBeInTheDocument();
    // Share of group is stated in text, never bar-only.
    expect(screen.getByRole('img', { name: 'Facts · Price: 75% of group' })).toBeInTheDocument();
  });

  it('shows the buyer-destination donut and merchant table', async () => {
    const user = userEvent.setup();
    renderWithData();
    await user.click(screen.getByRole('tab', { name: 'Destinations' }));

    expect(screen.getByText('Buyer destinations')).toBeInTheDocument();
    // The donut ARIA summary names every segment and percentage.
    expect(
      screen.getByRole('img', {
        name: 'Buyer destinations by kind: Brand site 67%, Marketplace 33%',
      }),
    ).toBeInTheDocument();
    // The domain legend table states name, kind, count, and share (the kind
    // label appears both in the donut legend and the table badge).
    expect(screen.getByText('acme.com')).toBeInTheDocument();
    expect(screen.getAllByText('Brand site').length).toBeGreaterThan(0);
    expect(screen.getAllByText('Marketplace').length).toBeGreaterThan(0);
  });

  it('shows the co-placement matrix with header semantics and the truncation notice', async () => {
    const user = userEvent.setup();
    renderWithData();
    await user.click(screen.getByRole('tab', { name: 'Co-placement' }));

    expect(screen.getByRole('heading', { name: 'Co-placement' })).toBeInTheDocument();
    expect(screen.getByText('Truncated')).toBeInTheDocument();
    // Row + column headers, numeric cell, and the truncation notice.
    expect(screen.getByRole('columnheader', { name: /Globex CityBike 450/ })).toBeInTheDocument();
    expect(screen.getByRole('rowheader', { name: /Acme VoltBike 500/ })).toBeInTheDocument();
    expect(screen.getByRole('cell', { name: '4' })).toBeInTheDocument();
    expect(screen.getByText(/less frequent pairs are truncated/)).toBeInTheDocument();
  });
});

describe('product visibility query key', () => {
  it('defaults to the latest audit, all engines, and the measurement surface', () => {
    expect(queryKeys.products.visibility(PROJECT)).toEqual([
      'products',
      'visibility',
      PROJECT,
      'latest',
      'all',
      'measurement',
    ]);
    expect(queryKeys.products.visibility(PROJECT, 'abc', 'gemini', '')).toEqual([
      'products',
      'visibility',
      PROJECT,
      'abc',
      'gemini',
      'measurement',
    ]);
    expect(queryKeys.products.visibility(PROJECT, 'abc', 'gemini', 'chatgpt-shopping')).toEqual([
      'products',
      'visibility',
      PROJECT,
      'abc',
      'gemini',
      'chatgpt-shopping',
    ]);
  });
});
