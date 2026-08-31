import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { PageKindScores } from './page-kind-scores';
import type { SiteCrawl, SiteHealthDashboard, SiteScoreSummary } from '@/lib/api/types';
import { COMPLETE_CLASSIFICATION_PROJECTION } from '@/test/site-health-fixtures';

const PROJECT = '11111111-1111-4111-8111-111111111111';
const CRAWL = '22222222-2222-4222-8222-222222222222';

function summary(overrides: Partial<SiteScoreSummary> = {}): SiteScoreSummary {
  return {
    web_fundamentals_score: 80,
    web_fundamentals_coverage: 1,
    web_fundamentals_state: 'measured',
    aeo_readiness_score: 62,
    aeo_measurement_coverage: 0.8,
    aeo_measurement_state: 'measured',
    search_eligibility: 'eligible',
    selected_count: 10,
    analyzed_count: 4,
    issue_count: 3,
    scoring_version: 's1',
    ...COMPLETE_CLASSIFICATION_PROJECTION,
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
                web_fundamentals_score: 80,
                web_fundamentals_coverage: 1,
                web_fundamentals_state: 'measured',
                aeo_readiness_score: 62,
                aeo_measurement_coverage: 0.8,
                aeo_measurement_state: 'measured',
                aeo_measurement_reason: '',
              },
              homepage: {
                analyzed_count: 1,
                web_fundamentals_score: 90.5,
                web_fundamentals_coverage: 1,
                web_fundamentals_state: 'measured',
                aeo_readiness_score: 70,
                aeo_measurement_coverage: 0.8,
                aeo_measurement_state: 'measured',
                aeo_measurement_reason: '',
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
                web_fundamentals_score: null,
                web_fundamentals_coverage: null,
                web_fundamentals_state: 'not_measured',
                aeo_readiness_score: null,
                aeo_measurement_coverage: null,
                aeo_measurement_state: 'not_measured',
                aeo_measurement_reason: '',
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

  it('shows a non-null limited score with subordinate coverage and preserves excluded state', () => {
    render(
      <PageKindScores
        crawl={null}
        dashboard={dashboard(
          summary({
            by_page_kind: {
              docs: {
                analyzed_count: 2,
                web_fundamentals_score: 46,
                web_fundamentals_coverage: 0.5,
                web_fundamentals_state: 'limited_evidence',
                aeo_readiness_score: null,
                aeo_measurement_coverage: null,
                aeo_measurement_state: 'excluded',
                aeo_measurement_reason: '',
              },
            },
          }),
        )}
      />,
    );

    expect(screen.getByText('46')).toBeInTheDocument();
    expect(screen.getByText('50% measured · Moderate confidence')).toBeInTheDocument();
    expect(screen.getByText('Excluded')).toBeInTheDocument();
  });

  it('surfaces classifier abstentions without converting them into readiness values', () => {
    render(
      <PageKindScores
        crawl={null}
        dashboard={dashboard(
          summary({
            analyzed_count: 10,
            classified_page_count: 6,
            other_page_count: 4,
            classification_expected_page_count: 10,
            classification_coverage: 0.6,
            classification_state: 'partial',
            classification_reason_groups: { no_signals: 4 },
            scored_page_kind_set: ['article'],
            scored_page_count_by_kind: { article: 6 },
            by_page_kind: {
              article: {
                analyzed_count: 6,
                web_fundamentals_score: 80,
                web_fundamentals_coverage: 1,
                web_fundamentals_state: 'measured',
                aeo_readiness_score: 70,
                aeo_measurement_coverage: 0.8,
                aeo_measurement_state: 'measured',
                aeo_measurement_reason: '',
              },
              other: {
                analyzed_count: 4,
                web_fundamentals_score: 90,
                web_fundamentals_coverage: 1,
                web_fundamentals_state: 'measured',
                aeo_readiness_score: null,
                aeo_measurement_coverage: null,
                aeo_measurement_state: 'not_measured',
                aeo_measurement_reason: 'page_purpose_unresolved',
              },
            },
          }),
        )}
      />,
    );

    expect(screen.getByText('Other')).toBeInTheDocument();
    expect(screen.getAllByText('Not measured').length).toBeGreaterThan(0);
    expect(screen.queryByText(/purpose unresolved/i)).not.toBeInTheDocument();
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('falls back to the crawl score summary when the dashboard has none', () => {
    render(
      <PageKindScores
        crawl={crawl(
          summary({
            by_page_kind: {
              about_contact: {
                analyzed_count: 1,
                web_fundamentals_score: 55,
                web_fundamentals_coverage: 1,
                web_fundamentals_state: 'measured',
                aeo_readiness_score: 45,
                aeo_measurement_coverage: 0.8,
                aeo_measurement_state: 'measured',
                aeo_measurement_reason: '',
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
