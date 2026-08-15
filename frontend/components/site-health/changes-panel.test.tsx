import { http, HttpResponse } from 'msw';
import { screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';
import { ChangesPanel } from './changes-panel';

const PROJECT = '11111111-1111-4111-8111-111111111111';
const CRAWL_A = '22222222-2222-4222-8222-222222222222';
const CRAWL_B = '33333333-3333-4333-8333-333333333333';
const SNAPSHOT = '44444444-4444-4444-8444-444444444444';
const SITE_URL = '55555555-5555-4555-8555-555555555555';

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => mswServer.resetHandlers());
afterAll(() => mswServer.close());

function response(state: 'available' | 'unavailable' | 'non_comparable', complete = true) {
  return {
    state,
    reason_code: state === 'non_comparable' ? 'analysis_version_mismatch' : null,
    snapshot_id: state === 'unavailable' ? null : SNAPSHOT,
    crawl_a_id: state === 'unavailable' ? null : CRAWL_A,
    crawl_b_id: state === 'unavailable' ? null : CRAWL_B,
    complete_pair: complete,
    analyzer_version: 'site-change-v1',
    page_analyzer_version: 'page-v1',
    extractor_version: 'extract-v1',
    source_analysis_ids: [],
    coverage: {},
    summary: { counts_by_class: { 'critical-regression': 1 } },
    limitations: complete ? [] : ['partial_crawl_shared_urls_only'],
    created_at: state === 'unavailable' ? null : '2026-08-15T00:00:00Z',
  };
}

function handlers(state: 'available' | 'unavailable' | 'non_comparable', complete = true) {
  const base = `/api/v1/projects/${PROJECT}/site-health/changes`;
  mswServer.use(
    http.get(`${base}/summary`, () => HttpResponse.json(response(state, complete))),
    http.get(base, ({ request }) => {
      const url = new URL(request.url);
      if (
        url.searchParams.get('crawl_a_id') !== CRAWL_A ||
        url.searchParams.get('crawl_b_id') !== CRAWL_B
      ) {
        return HttpResponse.json({ detail: 'exact pair required' }, { status: 422 });
      }
      return HttpResponse.json({
        ...response(state, complete),
        items:
          state === 'available'
            ? [
                {
                  id: '66666666-6666-4666-8666-666666666666',
                  site_url_id: SITE_URL,
                  normalized_url: 'https://acme.test/guide',
                  field: 'http_status',
                  change_class: 'critical-regression',
                  before_value: 200,
                  after_value: 503,
                  source_analysis_a_id: CRAWL_A,
                  source_analysis_b_id: CRAWL_B,
                  source_artifact_a_id: CRAWL_A,
                  source_artifact_b_id: CRAWL_B,
                  source_evaluation_a_id: null,
                  source_evaluation_b_id: null,
                  expected: false,
                  implementation_event_id: null,
                  created_at: '2026-08-15T00:00:00Z',
                },
              ]
            : [],
        next_cursor: null,
      });
    }),
  );
}

describe('Website Changes', () => {
  it('renders regression summary and exact before/after evidence', async () => {
    handlers('available');
    renderWithProviders(<ChangesPanel projectId={PROJECT} />);

    expect(await screen.findByTestId('website-changes')).toHaveTextContent('Critical regression');
    expect(screen.getByRole('link', { name: 'acme.test/guide' })).toHaveAttribute(
      'href',
      `/site/crawls/${CRAWL_B}/pages/${SITE_URL}`,
    );
    await userEvent.click(screen.getByText('View evidence'));
    expect(screen.getByText(/Before:/).parentElement).toHaveTextContent('200');
    expect(screen.getByText(/After:/).parentElement).toHaveTextContent('503');
  });

  it('states partial and non-comparable limitations honestly', async () => {
    handlers('available', false);
    const rendered = renderWithProviders(<ChangesPanel projectId={PROJECT} />);
    expect(await screen.findByText(/shared observed URLs only/i)).toBeInTheDocument();
    rendered.unmount();

    handlers('non_comparable');
    renderWithProviders(<ChangesPanel projectId={PROJECT} />);
    expect(await screen.findByText(/analysis version mismatch/i)).toBeInTheDocument();
  });
});
