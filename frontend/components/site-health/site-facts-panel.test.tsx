import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { SiteFactsPanel } from './site-facts-panel';
import type { SiteCrawl, SiteHealthDashboard } from '@/lib/api/types';

const PROJECT = '11111111-1111-4111-8111-111111111111';
const CRAWL = '22222222-2222-4222-8222-222222222222';

// Bounded site-facts blob the worker persists (`_crawl_setup` in
// backend/app/workers/site_health_worker.py); variant A — GPTBot blocked.
const variantA = {
  robots: {
    fetched: true,
    url: 'https://acme.com/robots.txt',
    status_code: 200,
    ai_crawlers: {
      GPTBot: 'block',
      ClaudeBot: 'allow',
      PerplexityBot: 'allow',
      'Google-Extended': 'allow',
    },
    sitemaps: ['https://acme.com/sitemap.xml'],
  },
  llms_txt: { fetched: true, url: 'https://acme.com/llms.txt', status_code: 200, present: true },
  sitemap: { fetched: false, files: [] },
};

const robotsUnfetched = {
  ...variantA,
  robots: {
    ...variantA.robots,
    fetched: false,
    status_code: null,
    // Recorded fail-open server-side; the panel must still show Unknown.
    ai_crawlers: {
      GPTBot: 'allow',
      ClaudeBot: 'allow',
      PerplexityBot: 'allow',
      'Google-Extended': 'allow',
    },
  },
  llms_txt: { fetched: true, url: 'https://acme.com/llms.txt', status_code: 404, present: false },
};

/** B2: the site HAS no robots.txt (HTTP 404) — a definitive default-allow. */
const robotsNotFound = {
  ...variantA,
  robots: {
    ...variantA.robots,
    fetched: false,
    status: 'not_found',
    status_code: 404,
    ai_crawlers: {
      GPTBot: 'allow',
      ClaudeBot: 'allow',
      PerplexityBot: 'allow',
      'Google-Extended': 'allow',
    },
  },
  llms_txt: { fetched: true, url: 'https://acme.com/llms.txt', status_code: 404, present: false },
};

const allAllowed = {
  ...variantA,
  robots: {
    ...variantA.robots,
    ai_crawlers: {
      GPTBot: 'allow',
      ClaudeBot: 'allow',
      PerplexityBot: 'allow',
      'Google-Extended': 'allow',
    },
  },
};

function crawl(siteFacts: SiteCrawl['site_facts']): SiteCrawl {
  return {
    id: CRAWL,
    workspace_id: '33333333-3333-4333-8333-333333333333',
    project_id: PROJECT,
    profile_id: '55555555-5555-4555-8555-555555555555',
    status: 'completed',
    discovery_status: 'completed',
    analysis_status: 'completed',
    root_url: 'https://acme.com/',
    sample_mode: false,
    seed: '1',
    inventory_complete: true,
    partial_reason: '',
    visible_url_count: 3,
    analyzed_count: 3,
    failed_count: 0,
    discovery_requested_count: 3,
    analysis_requested_count: 3,
    counters: {
      discovered: 3,
      selected: 3,
      queued: 0,
      running: 0,
      analyzed: 3,
      errors: 0,
      blocked: 0,
      failure_breakdown: { robots_denied: 0, http_4xx: 0, http_5xx: 0, timeout: 0 },
      activity: { state: 'terminal', reason: 'terminal', queue_depth: 0, next_available_at: null },
      by_page_kind: {},
    },
    discovered_count: 3,
    total_url_count: 3,
    has_more_site_urls: false,
    score_summary: null,
    failure_summary: null,
    site_facts: siteFacts,
    extractor_version: 'e1',
    analyzer_version: 'a1',
    rule_version: 'r1',
    scoring_version: 's1',
    error_message: '',
    created_at: '2026-07-16T00:00:00Z',
    updated_at: '2026-07-16T00:00:00Z',
    started_at: '2026-07-16T00:00:00Z',
    completed_at: '2026-07-16T00:05:00Z',
  };
}

function dashboard(crawlValue: SiteCrawl | null): SiteHealthDashboard {
  return {
    project_id: PROJECT,
    crawl: crawlValue,
    score_summary: null,
    phase: 'dashboard',
    snapshot_id: null,
    quota: { used: 4, limit: 50 },
    root_errors: [],
  };
}

describe('SiteFactsPanel', () => {
  it('renders the four bot rows in order with GPTBot blocked (variant A)', () => {
    render(<SiteFactsPanel crawl={crawl(variantA)} dashboard={undefined} />);

    expect(screen.getByTestId('site-facts-panel')).toBeInTheDocument();
    // Header summary badge + description.
    expect(screen.getByText('1 of 4 blocked')).toBeInTheDocument();
    expect(screen.getByText('AI crawler access')).toBeInTheDocument();
    expect(
      screen.queryByText('Which AI answer engines your robots.txt allows to crawl this site.'),
    ).not.toBeInTheDocument();
    expect(screen.getByText('Crawler details').closest('details')).not.toHaveAttribute('open');

    // Four stance cells in canonical AI_CRAWLER_BOTS order.
    const grid = screen.getByTestId('site-facts-stance-grid');
    const cells = [
      within(grid).getByTestId('site-facts-stance-gptbot'),
      within(grid).getByTestId('site-facts-stance-claudebot'),
      within(grid).getByTestId('site-facts-stance-perplexitybot'),
      within(grid).getByTestId('site-facts-stance-google-extended'),
    ];
    expect(
      cells[0].compareDocumentPosition(cells[1]) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      cells[1].compareDocumentPosition(cells[2]) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    expect(
      cells[2].compareDocumentPosition(cells[3]) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();

    // GPTBot blocked, the rest allowed — badge inside the right cell.
    expect(within(cells[0]).getByText('GPTBot')).toBeInTheDocument();
    expect(within(cells[0]).getByText('Block')).toBeInTheDocument();
    expect(within(cells[0]).getByText('ChatGPT')).toBeInTheDocument();
    for (const cell of cells.slice(1)) {
      expect(within(cell).getByText('Allow')).toBeInTheDocument();
    }
    expect(within(cells[3]).getByText('Gemini / AI Overviews')).toBeInTheDocument();

    // Blocked alert names the bot and its engine.
    expect(
      screen.getByText(/GPTBot is disallowed in robots\.txt — ChatGPT cannot crawl/),
    ).toBeInTheDocument();

    // Well-known files row: status codes, fetch badges, checked URLs.
    const files = screen.getByTestId('site-facts-well-known-files');
    expect(within(files).getByText('robots.txt')).toBeInTheDocument();
    expect(within(files).getByText('llms.txt')).toBeInTheDocument();
    expect(within(files).getAllByText('200')).toHaveLength(2);
    expect(within(files).getByText('Fetched')).toBeInTheDocument();
    expect(within(files).getByText('Present')).toBeInTheDocument();
    expect(within(files).getByText('https://acme.com/robots.txt')).toBeInTheDocument();
    expect(within(files).getByText('https://acme.com/llms.txt')).toBeInTheDocument();
  });

  it('renders nothing when site_facts is null (absent mockup omits the panel)', () => {
    const { container } = render(
      <SiteFactsPanel crawl={crawl(null)} dashboard={dashboard(null)} />,
    );
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId('site-facts-panel')).not.toBeInTheDocument();
  });

  it('renders nothing when the blob is malformed', () => {
    const { container } = render(
      <SiteFactsPanel crawl={crawl({ robots: 'nope' })} dashboard={undefined} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it('shows unknown stance for all bots when robots.txt could not be fetched (B2)', () => {
    render(<SiteFactsPanel crawl={crawl(robotsUnfetched)} dashboard={undefined} />);

    expect(screen.getByText('Stance unknown')).toBeInTheDocument();
    expect(screen.getAllByText('Unknown')).toHaveLength(6);
    expect(screen.queryByText('Block')).not.toBeInTheDocument();
    expect(screen.queryByText('Allow')).not.toBeInTheDocument();
    expect(screen.getByText(/robots\.txt could not be fetched/)).toBeInTheDocument();

    const files = screen.getByTestId('site-facts-well-known-files');
    expect(within(files).getByText('Not fetched')).toBeInTheDocument();
    expect(within(files).getByText('Absent')).toBeInTheDocument();
    expect(within(files).getByText('404')).toBeInTheDocument();
    expect(within(files).getByText('Unknown')).toBeInTheDocument(); // no robots status
  });

  it('shows a definitive all-allowed stance when the site has NO robots.txt (B2 not_found)', () => {
    // A 404 robots.txt is not a fetch failure: the fail-open default IS the
    // answer, so the panel says so instead of crying "unknown".
    render(<SiteFactsPanel crawl={crawl(robotsNotFound)} dashboard={undefined} />);

    expect(screen.getByText('All 4 allowed')).toBeInTheDocument();
    expect(screen.getAllByText('Allow')).toHaveLength(4);
    expect(screen.queryByText('Stance unknown')).not.toBeInTheDocument();
    expect(screen.getByText(/No robots\.txt — crawling proceeds fail-open/)).toBeInTheDocument();

    const files = screen.getByTestId('site-facts-well-known-files');
    expect(within(files).getByText('Not found')).toBeInTheDocument();
    // robots.txt AND llms.txt both answered 404 in this fixture.
    expect(within(files).getAllByText('404')).toHaveLength(2);
  });

  it('shows the all-allowed summary with no alert (variant B)', () => {
    render(<SiteFactsPanel crawl={crawl(allAllowed)} dashboard={undefined} />);
    expect(screen.getByText('All 4 allowed')).toBeInTheDocument();
    expect(screen.getAllByText('Allow')).toHaveLength(4);
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('prefers the dashboard crawl site_facts over the crawl prop fallback', () => {
    render(
      <SiteFactsPanel crawl={crawl(robotsUnfetched)} dashboard={dashboard(crawl(variantA))} />,
    );
    expect(screen.getByText('1 of 4 blocked')).toBeInTheDocument();
    expect(screen.queryByText('Stance unknown')).not.toBeInTheDocument();
  });

  it('falls back to the crawl prop when the dashboard has no crawl', () => {
    render(<SiteFactsPanel crawl={crawl(variantA)} dashboard={dashboard(null)} />);
    expect(screen.getByTestId('site-facts-panel')).toBeInTheDocument();
    expect(screen.getByText('1 of 4 blocked')).toBeInTheDocument();
  });
});
