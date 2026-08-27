import { screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/render';

import { CatalogHeader } from './catalog-header';

const getDashboard = vi.fn();

vi.mock('@/lib/api/site-health', async () => {
  const actual =
    await vi.importActual<typeof import('@/lib/api/site-health')>('@/lib/api/site-health');
  return {
    ...actual,
    siteHealthApi: { ...actual.siteHealthApi, createCrawl: vi.fn() },
    // The header reads the dashboard through the shared query factory, so the
    // factory is the seam — replacing `siteHealthApi` alone leaves the
    // factory's own captured reference in place.
    siteHealthQueries: {
      ...actual.siteHealthQueries,
      dashboard: (projectId: string) => ({
        queryKey: ['site-health', 'dashboard', projectId],
        queryFn: () => getDashboard(),
      }),
    },
  };
});

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';

const crawl = (overrides: Record<string, unknown> = {}) => ({
  crawl: {
    id: '44444444-4444-4444-8444-444444444444',
    status: 'partially_completed',
    analyzed_count: 49,
    visible_url_count: 50,
    total_url_count: 50,
    ...overrides,
  },
});

const catalogQuery = (overrides: Record<string, unknown> = {}) =>
  ({
    isPending: false,
    isError: false,
    refetch: vi.fn(),
    data: {
      products: [{ id: 'p1' }, { id: 'p2' }],
      categories: [{ id: 'c1' }],
      projection_tasks: { succeeded: 10 },
    },
    ...overrides,
  }) as never;

describe('CatalogHeader', () => {
  beforeEach(() => {
    getDashboard.mockReset();
    getDashboard.mockResolvedValue(crawl());
  });

  it('reads the catalog as metrics, not as prose', async () => {
    renderWithProviders(<CatalogHeader projectId={PROJECT_ID} query={catalogQuery()} />);

    expect(screen.getByText('Products').nextSibling).toHaveTextContent('2');
    expect(screen.getByText('Categories').nextSibling).toHaveTextContent('1');
    await waitFor(() => expect(screen.getByText('49/50')).toBeInTheDocument());
    // The mechanism paragraph is gone — the numbers say it.
    expect(screen.queryByText(/project automatically/)).not.toBeInTheDocument();
  });

  it('never prints a progress fraction that reads backwards', async () => {
    // The crawl counters can disagree mid-flight (and did: a sitemap-driven
    // crawl reported a one-page "total" for fifty admitted URLs, which the
    // header rendered as "49/1"). Analyzed pages are proof the inventory is at
    // least that large, so the denominator can never fall below them.
    getDashboard.mockResolvedValue(crawl({ total_url_count: 1, visible_url_count: 1 }));
    renderWithProviders(<CatalogHeader projectId={PROJECT_ID} query={catalogQuery()} />);

    await waitFor(() => expect(screen.getByText('49/49')).toBeInTheDocument());
    expect(screen.queryByText('49/1')).not.toBeInTheDocument();
  });

  it('offers the crawl as the primary action until one exists', async () => {
    getDashboard.mockResolvedValue({ crawl: null });
    renderWithProviders(<CatalogHeader projectId={PROJECT_ID} query={catalogQuery()} />);

    await waitFor(() =>
      expect(screen.getByRole('button', { name: 'Run Site Health crawl' })).toBeInTheDocument(),
    );
    expect(screen.getByText('No crawl yet')).toBeInTheDocument();
    expect(screen.getByText('Pages analyzed').nextSibling).toHaveTextContent('Not measured');
  });
});
