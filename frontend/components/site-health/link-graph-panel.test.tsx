import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { renderWithProviders } from '@/test/render';
import { mswServer } from '@/test/msw-server';
import { LinkGraphPanel } from './link-graph-panel';

const PROJECT = '11111111-1111-4111-8111-111111111111';
const CRAWL = '22222222-2222-4222-8222-222222222222';
const SNAPSHOT = '33333333-3333-4333-8333-333333333333';
const SOURCE = '44444444-4444-4444-8444-444444444444';
const TARGET = '55555555-5555-4555-8555-555555555555';

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

function handlers(state: 'available' | 'incomplete') {
  const base = `/api/v1/projects/${PROJECT}/site-health/link-graph`;
  mswServer.use(
    http.get(base, () =>
      HttpResponse.json({
        state,
        snapshot_id: SNAPSHOT,
        crawl_id: CRAWL,
        root_site_url_id: SOURCE,
        analyzer_version: 'link-graph-v1',
        page_analyzer_version: 'page-v1',
        extractor_version: 'extract-v1',
        source_analysis_ids: [SOURCE, TARGET],
        coverage: {
          complete: state === 'available',
          analyzed_html_node_count: state === 'available' ? 2 : 1,
          selected_url_count: 2,
        },
        limitations: state === 'available' ? [] : ['Observed topology is partial.'],
        summary: { node_count: 2, edge_count: 1, near_orphan_count: 1, weak_authority_count: 1 },
        created_at: '2026-08-15T00:00:00Z',
      }),
    ),
    http.get(`${base}/nodes`, () =>
      HttpResponse.json({
        state,
        snapshot_id: SNAPSHOT,
        crawl_id: CRAWL,
        items: [
          {
            id: '66666666-6666-4666-8666-666666666666',
            site_url_id: SOURCE,
            source_analysis_id: SOURCE,
            normalized_url: 'https://acme.test/guide',
            title: 'CRM guide',
            indexable: true,
            pagerank: 0.8,
            click_depth: 0,
            followed_inbound_count: 1,
            followed_outbound_count: 1,
            near_orphan: false,
            weak_authority: false,
            over_linked: false,
            hub: true,
            suggested_source_ids: [],
          },
          {
            id: '77777777-7777-4777-8777-777777777777',
            site_url_id: TARGET,
            source_analysis_id: TARGET,
            normalized_url: 'https://acme.test/crm',
            title: 'CRM page',
            indexable: true,
            pagerank: 0.2,
            click_depth: 1,
            followed_inbound_count: 1,
            followed_outbound_count: 0,
            near_orphan: state === 'available',
            weak_authority: state === 'available',
            over_linked: false,
            hub: false,
            suggested_source_ids: state === 'available' ? [SOURCE] : [],
          },
        ],
        next_cursor: null,
        limitations: [],
      }),
    ),
    http.get(`${base}/edges`, () =>
      HttpResponse.json({
        state,
        snapshot_id: SNAPSHOT,
        crawl_id: CRAWL,
        items: [
          {
            id: '88888888-8888-4888-8888-888888888888',
            source_site_url_id: SOURCE,
            target_site_url_id: TARGET,
            target_url: 'https://acme.test/crm',
            followed: true,
            occurrence_count: 2,
            followed_occurrence_count: 1,
            nofollow_occurrence_count: 1,
            anchor_texts: ['CRM'],
          },
        ],
        next_cursor: null,
        limitations: [],
      }),
    ),
  );
}

describe('Website Link Graph', () => {
  it('renders the bounded visual, table fallback, and source suggestions', async () => {
    handlers('available');
    renderWithProviders(<LinkGraphPanel projectId={PROJECT} crawlId={CRAWL} />);

    expect(await screen.findByTestId('website-link-graph')).toBeInTheDocument();
    expect(screen.getByLabelText('Internal link graph preview')).toBeInTheDocument();
    expect(screen.getByRole('table')).toHaveTextContent('CRM page');
    expect(screen.getByRole('table')).toHaveTextContent('Near orphan');
    expect(screen.getByRole('table')).toHaveTextContent('CRM guide');
  });

  it('describes partial coverage and suppresses source suggestions', async () => {
    handlers('incomplete');
    renderWithProviders(<LinkGraphPanel projectId={PROJECT} crawlId={CRAWL} />);

    expect(
      await screen.findByText(/descriptive observed topology for a partial crawl/i),
    ).toBeInTheDocument();
    expect(screen.getByText(/Opportunities are suppressed/i)).toBeInTheDocument();
    expect(screen.queryByText('Near orphan')).not.toBeInTheDocument();
  });
});
