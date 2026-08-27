import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { siteHealthApi } from '@/lib/api/site-health';
import { commerceApi } from '@/lib/api/commerce';
import { renderWithProviders } from '@/test/render';
import { CatalogPanel } from './catalog-panel';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const CATEGORY_ID = '22222222-2222-4222-8222-222222222222';
const PRODUCT_ID = '33333333-3333-4333-8333-333333333333';

function query() {
  return {
    data: {
      categories: [
        {
          id: CATEGORY_ID,
          name: 'Running shoes',
          role: 'leaf',
          canonical_url: 'https://shop.test/shoes',
          product_count: 1,
          field_sources: {},
          source_analysis_id: null,
          projector_version: 'commerce-projector-3',
        },
      ],
      products: [
        {
          id: PRODUCT_ID,
          canonical_url: 'https://shop.test/products/trail-one',
          name: 'Trail One',
          description: '',
          brand: 'Acme',
          price: 19,
          currency: 'AUD',
          sku: null,
          gtin: null,
          mpn: null,
          observed_external_id: '',
          variants: [],
          attributes: {},
          field_sources: {},
          lifecycle_state: 'active',
          category_ids: [CATEGORY_ID],
          created_at: '2026-08-26T00:00:00Z',
          updated_at: '2026-08-26T00:00:00Z',
        },
      ],
      projection_tasks: { succeeded: 3, queued: 1 },
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn().mockResolvedValue(undefined),
  };
}

describe('Catalog panel', () => {
  afterEach(() => vi.restoreAllMocks());

  it('shows Site Health discovery, projection progress, categories, and memberships', async () => {
    vi.spyOn(siteHealthApi, 'getDashboard').mockResolvedValue({ crawl: null } as never);
    const create = vi.spyOn(siteHealthApi, 'createCrawl').mockResolvedValue({} as never);

    renderWithProviders(<CatalogPanel projectId={PROJECT_ID} query={query() as never} />);

    expect(await screen.findByText('3 succeeded · 1 queued', { exact: false })).toBeInTheDocument();
    expect(screen.getAllByText('Running shoes')).toHaveLength(2);
    expect(screen.getByText('leaf')).toBeInTheDocument();
    await screen.findByText('No Site Health crawl is available yet.');
    fireEvent.click(screen.getByRole('button', { name: 'Discover from Site Health' }));

    await waitFor(() => expect(create).toHaveBeenCalledWith({ project_id: PROJECT_ID }));
  });

  it('opens a product correction form with category reassignment controls', async () => {
    vi.spyOn(siteHealthApi, 'getDashboard').mockResolvedValue({ crawl: null } as never);

    renderWithProviders(<CatalogPanel projectId={PROJECT_ID} query={query() as never} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));

    expect(screen.getByRole('textbox', { name: 'Product name' })).toHaveValue('Trail One');
    expect(screen.getByRole('checkbox', { name: 'Running shoes' })).toBeChecked();
    expect(screen.getByRole('button', { name: 'Save correction' })).toBeInTheDocument();
  });

  it('sends only product fields changed by the user', async () => {
    vi.spyOn(siteHealthApi, 'getDashboard').mockResolvedValue({ crawl: null } as never);
    const edit = vi
      .spyOn(commerceApi, 'editProduct')
      .mockResolvedValue(query().data.products[0] as never);

    renderWithProviders(<CatalogPanel projectId={PROJECT_ID} query={query() as never} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Edit' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Product name' }), {
      target: { value: 'Trail One Updated' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save correction' }));

    await waitFor(() =>
      expect(edit).toHaveBeenCalledWith(PROJECT_ID, PRODUCT_ID, { name: 'Trail One Updated' }),
    );
  });

  it('renders a zero price rather than dropping it, with or without a currency', async () => {
    // `filter(Boolean)` treated a price of 0 as absent: a free item rendered
    // as a bare "AUD", or as an empty cell when no currency was observed.
    vi.spyOn(siteHealthApi, 'getDashboard').mockResolvedValue({ crawl: null } as never);
    const state = query();
    const [product] = state.data.products;
    state.data.products = [
      { ...product, id: PRODUCT_ID, price: 0, currency: 'AUD' },
      {
        ...product,
        id: '44444444-4444-4444-8444-444444444444',
        name: 'Sample Pack',
        canonical_url: 'https://shop.test/products/sample-pack',
        price: 0,
        currency: '',
      },
    ];

    renderWithProviders(<CatalogPanel projectId={PROJECT_ID} query={state as never} />);

    expect(await screen.findByText('AUD 0')).toBeInTheDocument();
    expect(screen.getByText('0')).toBeInTheDocument();
  });

  it('opens category name and role correction controls', async () => {
    vi.spyOn(siteHealthApi, 'getDashboard').mockResolvedValue({ crawl: null } as never);

    renderWithProviders(<CatalogPanel projectId={PROJECT_ID} query={query() as never} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Rename' }));

    expect(screen.getByRole('textbox', { name: 'Category name' })).toHaveValue('Running shoes');
    expect(screen.getByRole('combobox', { name: 'Category role' })).toHaveValue('leaf');
  });
});
