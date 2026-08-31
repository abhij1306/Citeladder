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

function architecture(overrides: Record<string, unknown> = {}) {
  return {
    state: 'available',
    crawl_id: CRAWL,
    coverage_state: 'complete',
    page_count: 3,
    page_kinds: [
      {
        page_kind: 'product',
        page_count: 2,
        median_depth: 1,
        indexable_count: 2,
        duplicate_metadata_count: 1,
        orphan_count: 1,
      },
      {
        page_kind: 'homepage',
        page_count: 1,
        median_depth: 0,
        indexable_count: 1,
        duplicate_metadata_count: 0,
        orphan_count: 0,
      },
    ],
    nodes: [
      {
        site_url_id: HOME,
        url: 'https://acme.test/',
        title: 'Home',
        page_kind: 'homepage',
        parent_site_url_id: null,
        parent_source: 'unknown',
        depth_from_home: 0,
      },
      ...[
        [BAGS, 'https://acme.test/shop/bags'],
        [BOOTS, 'https://acme.test/shop/boots'],
      ].map(([siteUrlId, url]) => ({
        site_url_id: siteUrlId,
        url,
        title: 'Product',
        page_kind: 'product',
        parent_site_url_id: HOME,
        parent_source: 'breadcrumb',
        depth_from_home: 1,
      })),
    ],
    internal_linking: {
      internal_link_count: 8,
      pages_with_incoming_count: 2,
      pages_with_incoming_percentage: 0.6667,
      orphan_page_count: 1,
    },
    structure_depth: {
      measured_page_count: 3,
      unmeasured_page_count: 0,
      buckets: [
        { key: 'depth_0', page_count: 1, percentage: 0.3333 },
        { key: 'depth_1', page_count: 2, percentage: 0.6667 },
        { key: 'depth_2', page_count: 0, percentage: 0 },
        { key: 'depth_3_plus', page_count: 0, percentage: 0 },
      ],
    },
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
  it('groups URLs by one page-kind term and shows persisted summaries', async () => {
    stubArchitecture();
    renderWithProviders(<ArchitecturePanel projectId={PROJECT} crawlId={CRAWL} />);

    expect(await screen.findByRole('heading', { name: 'Page kinds' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Page kind' })).toBeInTheDocument();
    expect(screen.queryByText('Type mix')).toBeNull();
    expect(screen.queryByText('URL pattern')).toBeNull();
    expect(screen.getByText('Internal linking')).toBeInTheDocument();
    expect(screen.getByText('Structure depth')).toBeInTheDocument();
    expect(screen.getByRole('heading', { name: 'Observed hierarchy' })).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Observed hierarchy pages' })).toHaveClass(
      'max-h-96',
      'overflow-y-auto',
    );
    expect(screen.getByText('67%')).toBeInTheDocument();
    expect(screen.getByText('8')).toBeInTheDocument();
    const linking = screen.getByText('Internal linking').closest('section');
    const pageKinds = screen.getByRole('heading', { name: 'Page kinds' }).closest('section');
    expect(
      linking!.compareDocumentPosition(pageKinds!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('renders the persisted parent hierarchy and relationship source', async () => {
    stubArchitecture();
    renderWithProviders(<ArchitecturePanel projectId={PROJECT} crawlId={CRAWL} />);

    const home = await screen.findByRole('link', { name: 'https://acme.test/' });
    const homeBranch = home.closest('li');
    expect(homeBranch).not.toBeNull();
    expect(
      within(homeBranch!).getByRole('link', { name: 'https://acme.test/shop/bags' }),
    ).toBeInTheDocument();
    expect(within(homeBranch!).getAllByText('Breadcrumb')).toHaveLength(2);
  });

  it('reveals all URLs assigned to a page kind', async () => {
    stubArchitecture();
    renderWithProviders(<ArchitecturePanel projectId={PROJECT} crawlId={CRAWL} />);

    const productButton = await screen.findByRole('button', { name: 'Product' });
    await userEvent.click(productButton);
    const bags = screen.getAllByRole('link', { name: 'https://acme.test/shop/bags' });
    expect(bags).toHaveLength(2);
    expect(bags[0]).toHaveAttribute('href', `/site/crawls/${CRAWL}/pages/${BAGS}`);
    expect(screen.getAllByRole('link', { name: 'https://acme.test/shop/boots' })).toHaveLength(2);
  });

  it('withholds orphan counts when coverage is partial', async () => {
    stubArchitecture({
      coverage_state: 'partial',
      page_kinds: [{ ...architecture().page_kinds[0], orphan_count: null }],
      internal_linking: { ...architecture().internal_linking, orphan_page_count: null },
      limitations: ['This crawl hit its page budget, so these are the pages observed.'],
    });
    renderWithProviders(<ArchitecturePanel projectId={PROJECT} crawlId={CRAWL} />);

    expect(await screen.findByText('Partial coverage')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('page budget');
    const orphans = screen.getAllByText('Orphaned pages')[0]!.closest('div');
    expect(within(orphans!).getByText('Count withheld · partial coverage')).toBeInTheDocument();
  });

  it('renders an observed zero only when coverage is complete', async () => {
    stubArchitecture({
      internal_linking: { ...architecture().internal_linking, orphan_page_count: 0 },
    });
    renderWithProviders(<ArchitecturePanel projectId={PROJECT} crawlId={CRAWL} />);

    const orphans = (await screen.findAllByText('Orphaned pages'))[0]!.closest('div');
    expect(within(orphans!).getByText('0')).toBeInTheDocument();
    expect(within(orphans!).queryByText(/withheld/i)).not.toBeInTheDocument();
  });

  it('names unknown coverage instead of calling the orphan count not measured', async () => {
    stubArchitecture({
      coverage_state: 'unknown',
      page_kinds: [{ ...architecture().page_kinds[0], orphan_count: null }],
      internal_linking: { ...architecture().internal_linking, orphan_page_count: null },
    });
    renderWithProviders(<ArchitecturePanel projectId={PROJECT} crawlId={CRAWL} />);

    expect(await screen.findAllByText('Count withheld · coverage unknown')).not.toHaveLength(0);
  });

  it('explains when the persisted projection is unavailable', async () => {
    stubArchitecture({
      state: 'unavailable',
      crawl_id: null,
      coverage_state: 'unknown',
      page_count: 0,
      page_kinds: [],
      nodes: [],
      limitations: ['This crawl has no observed architecture yet.'],
    });
    renderWithProviders(<ArchitecturePanel projectId={PROJECT} crawlId={CRAWL} />);
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'This crawl has no observed architecture yet.',
    );
  });
});
