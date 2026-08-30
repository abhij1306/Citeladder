import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { PageKindScores } from './page-kind-scores';
import type { SiteCrawl, SiteHealthDashboard, SiteScoreSummary } from '@/lib/api/types';

const PROJECT = '11111111-1111-4111-8111-111111111111';
const CRAWL = '22222222-2222-4222-8222-222222222222';

function summary(overrides: Partial<SiteScoreSummary> = {}): SiteScoreSummary {
  return {
    technical_integrity_score: 80,
    technical_integrity_coverage: 1,
    technical_integrity_state: 'measured',
    aeo_readiness_score: 62,
    aeo_measurement_coverage: 0.8,
    aeo_measurement_state: 'measured',
    search_eligibility: 'eligible',
    selected_count: 10,
    analyzed_count: 4,
    issue_count: 3,
    scoring_version: 's1',
    by_page_kind: {},
    ...overrides,
  };
}

function dashboard(scoreSummary: SiteScoreSummary | null): SiteHealthDashboard {
  return {
    project_id: PROJECT,
    crawl: null,
    score_summary: scoreSummary,
    phase: 'dashboard',
    snapshot_id: null,
    quota: { used: 4, limit: 50 },
    root_errors: [],
    phase_runs: { discovery: null, analysis: null },
  };
}

// Bounded site-facts blob the worker persists (`_crawl_setup` in
// backend/app/workers/site_health_worker.py); the backend always emits the key.
const siteFacts = {
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

function crawl(scoreSummary: SiteScoreSummary | null): SiteCrawl {
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
    score_summary: scoreSummary,
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

describe('PageKindScores', () => {
  it('renders nothing before any score summary exists', () => {
    const { container } = render(<PageKindScores crawl={null} dashboard={undefined} />);
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByTestId('page-kind-scores')).not.toBeInTheDocument();
  });

  it('renders the empty state when no page has been classified yet', () => {
    render(<PageKindScores crawl={null} dashboard={dashboard(summary())} />);
    expect(screen.getByTestId('page-kind-scores')).toBeInTheDocument();
    expect(
      screen.getByText('Per-page-kind scores appear once the analysis classifies your pages.'),
    ).toBeInTheDocument();
  });

  it('renders one row per classified type with analyzed count + mean scores', () => {
    render(
      <PageKindScores
        crawl={null}
        dashboard={dashboard(
          summary({
            by_page_kind: {
              article: {
                analyzed_count: 3,
                technical_integrity_score: 80,
                technical_integrity_coverage: 1,
                technical_integrity_state: 'measured',
                aeo_readiness_score: 62,
                aeo_measurement_coverage: 0.8,
                aeo_measurement_state: 'measured',
              },
              homepage: {
                analyzed_count: 1,
                technical_integrity_score: 90.5,
                technical_integrity_coverage: 1,
                technical_integrity_state: 'measured',
                aeo_readiness_score: 70,
                aeo_measurement_coverage: 0.8,
                aeo_measurement_state: 'measured',
              },
            },
          }),
        )}
      />,
    );
    // Humanized type badges.
    expect(screen.getByText('Homepage')).toBeInTheDocument();
    expect(screen.getByText('Article')).toBeInTheDocument();
    // Analyzed counts.
    expect(screen.getByText('3')).toBeInTheDocument();
    expect(screen.getByText('1')).toBeInTheDocument();
    // Mean scores formatted like every other score cell.
    expect(screen.getByText('80')).toBeInTheDocument();
    expect(screen.getByText('90.5')).toBeInTheDocument();
    // PAGE_KINDS display order: Homepage row precedes the Article row.
    const homepage = screen.getByText('Homepage');
    const article = screen.getByText('Article');
    expect(
      homepage.compareDocumentPosition(article) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('renders not measured for a missing mean score, never a fabricated zero', () => {
    render(
      <PageKindScores
        crawl={null}
        dashboard={dashboard(
          summary({
            by_page_kind: {
              docs: {
                analyzed_count: 2,
                technical_integrity_score: null,
                technical_integrity_coverage: null,
                technical_integrity_state: 'not_measured',
                aeo_readiness_score: null,
                aeo_measurement_coverage: null,
                aeo_measurement_state: 'not_measured',
              },
            },
          }),
        )}
      />,
    );
    expect(screen.getByText('Docs')).toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
    expect(screen.getAllByText('Not measured').length).toBeGreaterThan(0);
  });

  it('preserves limited and excluded measurement states', () => {
    render(
      <PageKindScores
        crawl={null}
        dashboard={dashboard(
          summary({
            by_page_kind: {
              docs: {
                analyzed_count: 2,
                technical_integrity_score: null,
                technical_integrity_coverage: 0.5,
                technical_integrity_state: 'limited_evidence',
                aeo_readiness_score: null,
                aeo_measurement_coverage: null,
                aeo_measurement_state: 'excluded',
              },
            },
          }),
        )}
      />,
    );

    expect(screen.getByText('Limited evidence')).toBeInTheDocument();
    expect(screen.getByText('Excluded')).toBeInTheDocument();
  });

  it('surfaces the unclassified share and its scoring treatment', () => {
    render(
      <PageKindScores
        crawl={null}
        dashboard={dashboard(
          summary({
            analyzed_count: 10,
            by_page_kind: {
              article: {
                analyzed_count: 6,
                technical_integrity_score: 80,
                technical_integrity_coverage: 1,
                technical_integrity_state: 'measured',
                aeo_readiness_score: 70,
                aeo_measurement_coverage: 0.8,
                aeo_measurement_state: 'measured',
              },
              other: {
                analyzed_count: 4,
                technical_integrity_score: 90,
                technical_integrity_coverage: 1,
                technical_integrity_state: 'measured',
                aeo_readiness_score: null,
                aeo_measurement_coverage: 0.3,
                aeo_measurement_state: 'limited_evidence',
              },
            },
          }),
        )}
      />,
    );

    expect(
      screen.getByText(
        '4 of 10 analyzed pages could not be classified; their AEO score is not measured.',
      ),
    ).toBeInTheDocument();
  });

  it('falls back to the crawl score summary when the dashboard has none', () => {
    render(
      <PageKindScores
        crawl={crawl(
          summary({
            by_page_kind: {
              about_contact: {
                analyzed_count: 1,
                technical_integrity_score: 55,
                technical_integrity_coverage: 1,
                technical_integrity_state: 'measured',
                aeo_readiness_score: 45,
                aeo_measurement_coverage: 0.8,
                aeo_measurement_state: 'measured',
              },
            },
          }),
        )}
        dashboard={dashboard(null)}
      />,
    );
    expect(screen.getByTestId('page-kind-scores')).toBeInTheDocument();
    expect(screen.getByText('About / Contact')).toBeInTheDocument();
  });
});
