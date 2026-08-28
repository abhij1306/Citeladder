import { http, HttpResponse } from 'msw';
import { screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';
import { ArchitecturePanel } from './architecture-panel';

const PROJECT = '11111111-1111-4111-8111-111111111111';
const CRAWL = '22222222-2222-4222-8222-222222222222';
const HOME = '33333333-3333-4333-8333-333333333333';
const BAGS = '44444444-4444-4444-8444-444444444444';
const BOOTS = '55555555-5555-4555-8555-555555555555';

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

const NODES = [
  {
    site_url_id: HOME,
    url: 'https://acme.test/',
    title: 'Home',
    page_kind: 'homepage',
    family: '/',
    parent_site_url_id: null,
    parent_source: 'unknown',
    depth_from_home: 0,
  },
  {
    site_url_id: BAGS,
    url: 'https://acme.test/shop/bags',
    title: 'Bags',
    page_kind: 'category',
    family: '/shop/*',
    parent_site_url_id: HOME,
    parent_source: 'breadcrumb',
    depth_from_home: 1,
  },
  {
    site_url_id: BOOTS,
    url: 'https://acme.test/shop/boots',
    title: 'Boots',
    page_kind: 'product',
    family: '/shop/*',
    parent_site_url_id: HOME,
    parent_source: 'breadcrumb',
    depth_from_home: 1,
  },
];

const FAMILIES = [
  {
    family: '/',
    url_count: 1,
    page_kind_distribution: { homepage: 1 },
    median_depth: 0,
    indexable_count: 1,
    metadata_duplication_rate: 0,
    orphan_count: 0,
  },
  {
    family: '/shop/*',
    url_count: 2,
    page_kind_distribution: { category: 1, product: 1 },
    median_depth: 1,
    indexable_count: 2,
    metadata_duplication_rate: 0.5,
    orphan_count: 1,
  },
];

function architecture(overrides: Record<string, unknown> = {}) {
  return {
    state: 'available',
    crawl_id: CRAWL,
    coverage_state: 'complete',
    page_count: 3,
    page_kind_counts: { homepage: 1, category: 1, product: 1 },
    families: FAMILIES,
    nodes: NODES,
    architecture_formula_version: 'sh-architecture-1',
    limitations: [],
    ...overrides,
  };
}

function stubArchitecture(overrides: Record<string, unknown> = {}) {
  mswServer.use(
    http.get(`/api/v1/projects/${PROJECT}/site-health/architecture`, () =>
      HttpResponse.json(architecture(overrides)),
    ),
  );
}

describe('Architecture panel', () => {
  it('lists page families largest first and keeps their pages collapsed', async () => {
    stubArchitecture();
    renderWithProviders(<ArchitecturePanel projectId={PROJECT} crawlId={CRAWL} />);

    expect(await screen.findByText('Page families')).toBeInTheDocument();
    const rows = screen.getAllByRole('button', { expanded: false });
    expect(rows[0]).toHaveTextContent('/shop/*');
    expect(rows[0]).toHaveTextContent('2 URLs');
    // Pages stay behind the dropdown until asked for.
    expect(screen.queryByRole('link', { name: 'https://acme.test/shop/bags' })).toBeNull();
  });

  it('reveals a family’s pages as links into the existing page detail', async () => {
    stubArchitecture();
    renderWithProviders(<ArchitecturePanel projectId={PROJECT} crawlId={CRAWL} />);

    await userEvent.click(await screen.findByRole('button', { name: /\/shop\/\*/ }));
    expect(screen.getByRole('link', { name: 'https://acme.test/shop/bags' })).toHaveAttribute(
      'href',
      `/site/crawls/${CRAWL}/pages/${BAGS}`,
    );
    expect(screen.getByRole('link', { name: 'https://acme.test/shop/boots' })).toBeInTheDocument();
    // The family's own facts sit with its pages, not in a separate table.
    expect(screen.getByText('Duplicate metadata')).toBeInTheDocument();
    expect(screen.getByText('50%')).toBeInTheDocument();
  });

  it('renders neither an observed tree nor a site-profile block', async () => {
    stubArchitecture();
    renderWithProviders(<ArchitecturePanel projectId={PROJECT} crawlId={CRAWL} />);

    await screen.findByText('Page families');
    expect(screen.queryByText('Observed architecture')).toBeNull();
    expect(screen.queryByText('Site profile')).toBeNull();
    expect(screen.queryByLabelText('Site type')).toBeNull();
    expect(screen.queryByText('Common structures')).toBeNull();
  });

  it('states a partial coverage limit once and withholds the orphan claim', async () => {
    stubArchitecture({
      coverage_state: 'partial',
      families: [{ ...FAMILIES[1], orphan_count: null }],
      limitations: ['This crawl hit its page budget, so these are the pages CiteLadder observed.'],
    });
    renderWithProviders(<ArchitecturePanel projectId={PROJECT} crawlId={CRAWL} />);

    expect(await screen.findByText('Partial coverage')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('page budget');

    await userEvent.click(screen.getByRole('button', { name: /\/shop\/\*/ }));
    const orphans = screen.getByText('Orphans').closest('div');
    expect(within(orphans!).getByText('Not measured')).toBeInTheDocument();
  });

  it('explains that families are derived after a crawl rather than showing an empty list', async () => {
    stubArchitecture({
      state: 'unavailable',
      crawl_id: null,
      coverage_state: 'unknown',
      page_count: 0,
      page_kind_counts: {},
      families: [],
      nodes: [],
      limitations: ['This crawl has no observed architecture yet.'],
    });
    renderWithProviders(<ArchitecturePanel projectId={PROJECT} crawlId={CRAWL} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This crawl has no observed architecture yet.',
    );
  });
});
