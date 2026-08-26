import { fireEvent, screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { siteHealthApi } from '@/lib/api/site-health';
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

  it('opens category name and role correction controls', async () => {
    vi.spyOn(siteHealthApi, 'getDashboard').mockResolvedValue({ crawl: null } as never);

    renderWithProviders(<CatalogPanel projectId={PROJECT_ID} query={query() as never} />);
    fireEvent.click(await screen.findByRole('button', { name: 'Rename' }));

    expect(screen.getByRole('textbox', { name: 'Category name' })).toHaveValue('Running shoes');
    expect(screen.getByRole('combobox', { name: 'Category role' })).toHaveValue('leaf');
  });
});
