import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { StatusStrip } from './status-strip';
import type { PageSummary, SiteCrawl, SiteHealthEntitlement } from '@/lib/api/types';
import { COMPLETE_CLASSIFICATION_PROJECTION } from '@/test/site-health-fixtures';

const CRAWL = '22222222-2222-4222-8222-222222222222';

const entitlement: SiteHealthEntitlement = {
  workspace_id: '33333333-3333-4333-8333-333333333333',
  access_mode: 'full',
  sample_url_limit: 10,
  monitored_url_limit: 50,
  count_disclosure: true,
  resolver_status: 'resolved',
  registry_revision: 'reg-1',
  entitlement_lifecycle_version: 1,
  valid_until: null,
  contributing_grant_ids: [],
  advanced_controls_enabled: false,
};

function page(overrides: Partial<PageSummary> = {}): PageSummary {
  return {
    site_url_id: '11111111-1111-4111-8111-111111111111',
    crawl_id: CRAWL,
    normalized_url: 'https://acme.com/',
    display_url: 'https://acme.com/',
    title: 'Homepage',
    monitored: true,
    analysis_status: 'completed',
    error_code: '',
    issue_count: 3,
    web_fundamentals_score: 46,
    web_fundamentals_coverage: 1,
    web_fundamentals_state: 'measured',
    aeo_readiness_score: 64,
    aeo_measurement_coverage: 0.8,
    aeo_measurement_state: 'measured',
    aeo_measurement_reason: '',
    main_content_indexable: true,
    last_audited: '2026-07-16T00:00:00Z',
    page_kind: 'article',
    inbound_count: 12,
    main_content_inbound_count: 4,
    depth_from_home: 1,
    ...overrides,
  };
}

// The bounded site-facts blob the worker persists (`_crawl_setup` in
// backend/app/workers/site_health_worker.py): robots AI-crawler stance,
// llms.txt probe, sitemap file list. The backend always emits the key.
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

function crawl(overrides: Partial<SiteCrawl> = {}): SiteCrawl {
  return {
    id: CRAWL,
    workspace_id: '33333333-3333-4333-8333-333333333333',
    project_id: '44444444-4444-4444-8444-444444444444',
    profile_id: '55555555-5555-4555-8555-555555555555',
    status: 'running',
    discovery_status: 'completed',
    analysis_status: 'running',
    root_url: 'https://acme.com/',
    sample_mode: false,
    seed: '1',
    inventory_complete: true,
    partial_reason: '',
    visible_url_count: 3,
    analyzed_count: 1,
    failed_count: 0,
    discovery_requested_count: 3,
    analysis_requested_count: 3,
    counters: {
      discovered: 3,
      selected: 3,
      queued: 2,
      running: 0,
      analyzed: 1,
      errors: 0,
      blocked: 0,
      failure_breakdown: { robots_denied: 0, http_4xx: 0, http_5xx: 0, timeout: 0 },
      activity: {
        state: 'working',
        reason: 'active_work',
        queue_depth: 2,
        next_available_at: null,
      },
      by_page_kind: {},
    },
    discovered_count: 3,
    total_url_count: 3,
    has_more_site_urls: false,
    score_summary: {
      web_fundamentals_score: null,
      web_fundamentals_coverage: 0,
      web_fundamentals_state: 'not_measured',
      aeo_readiness_score: null,
      aeo_measurement_coverage: 0,
      aeo_measurement_state: 'not_measured',
      search_eligibility: 'unknown',
      selected_count: 3,
      analyzed_count: 1,
      issue_count: 0,
      scoring_version: 's1',
      ...COMPLETE_CLASSIFICATION_PROJECTION,
      classified_page_count: 1,
      classification_expected_page_count: 1,
      scored_page_kind_set: ['article'],
      scored_page_count_by_kind: { article: 1 },
      by_page_kind: {},
    },
    site_facts: siteFacts,
    extractor_version: 'e1',
    analyzer_version: 'a1',
    rule_version: 'r1',
    scoring_version: 's1',
    error_message: '',
    failure_summary: null,
    created_at: '2026-07-16T00:00:00Z',
    updated_at: '2026-07-16T00:00:00Z',
    started_at: '2026-07-16T00:00:00Z',
    completed_at: null,
    ...overrides,
  };
}

function renderStrip(props: Partial<Parameters<typeof StatusStrip>[0]> = {}) {
  return render(
    <StatusStrip
      crawl={crawl()}
      phase="analyzing"
      entitlement={entitlement}
      cancelPending={false}
      startPending={false}
      pages={[]}
      selectedTotal={null}
      selectedError={false}
      {...props}
    />,
  );
}

describe('StatusStrip — analysis counters', () => {
  it('derives "Pages analyzed" from the server aggregate, not a truncated pages window', () => {
    // Only ONE monitored page is present in this (deliberately truncated)
    // `pages` prop, but the crawl-wide score_summary says 1 of 3 is analyzed.
    // The analyzed count must reflect the authoritative aggregate.
    renderStrip({ pages: [page({ analysis_status: 'completed' })], selectedTotal: 3 });

    const totalLabel = screen.getByText('Pages selected');
    expect(totalLabel.parentElement?.textContent).toContain('3');
    const completedLabel = screen.getByText('Pages analyzed');
    const completedValue = completedLabel.parentElement?.querySelector('.text-run-completed');
    expect(completedValue?.textContent).toBe('1');
  });

  it('uses the persisted queue projection while the monitored query loads', () => {
    renderStrip({ crawl: crawl({ score_summary: null, analyzed_count: 0 }), selectedTotal: null });

    const queuedLabel = screen.getByText('Queued');
    expect(queuedLabel.parentElement?.textContent).toContain('2');
    const totalLabel = screen.getByText('Pages selected');
    expect(totalLabel.parentElement?.textContent).toContain('3');
  });

  it('shows a real Queued count once the selected total is known', () => {
    renderStrip({
      crawl: crawl({
        score_summary: null,
        analyzed_count: 1,
        failed_count: 0,
        counters: {
          ...crawl().counters,
          selected: 5,
          analyzed: 1,
          running: 1,
          queued: 3,
        },
      }),
      pages: [page({ analysis_status: 'running' })],
      selectedTotal: 5,
    });

    // selected(5) - completed(1) - failed(0) - running(1) = 3 queued.
    const queuedLabel = screen.getByText('Queued');
    const queuedValue = queuedLabel.parentElement?.querySelector('.mono');
    expect(queuedValue?.textContent).toBe('3');
  });

  it('surfaces a monitored-count fetch error instead of silently approximating', () => {
    renderStrip({ crawl: crawl({ score_summary: null }), selectedError: true });

    expect(screen.getByText(/Could not load the monitored-page count/)).toBeInTheDocument();
  });
});

describe('StatusStrip — analysis activity', () => {
  it('keeps the audit copy and live pulse while analysis is genuinely running', () => {
    renderStrip({
      crawl: crawl({ status: 'running', analysis_status: 'running', score_summary: null }),
      selectedTotal: 3,
    });

    expect(screen.getByText(/Auditing monitored pages/i)).toBeInTheDocument();
    expect(screen.getByTestId('activity-pulse')).toBeInTheDocument();
  });

  it('names blocked and failed categories from persisted task evidence', () => {
    renderStrip({
      crawl: crawl({
        score_summary: null,
        counters: {
          ...crawl().counters,
          blocked: 36,
          errors: 3,
          failure_breakdown: { robots_denied: 36, http_4xx: 1, http_5xx: 2, timeout: 0 },
        },
      }),
    });

    expect(screen.getByText('Blocked by robots.txt').parentElement?.textContent).toContain('36');
    expect(screen.getByText('HTTP 4XX').parentElement?.textContent).toContain('1');
    expect(screen.getByText('HTTP 5XX').parentElement?.textContent).toContain('2');
  });

  it('explains a persisted host-gate wait without calling it stalled', () => {
    renderStrip({
      crawl: crawl({
        score_summary: null,
        counters: {
          ...crawl().counters,
          activity: {
            state: 'waiting',
            reason: 'host_gate',
            queue_depth: 4,
            next_available_at: null,
          },
        },
      }),
    });

    expect(screen.getByText(/Waiting for the site host gate/i)).toBeInTheDocument();
  });

  it('prefers the cancelling narration over the link-check copy', () => {
    renderStrip({
      crawl: crawl({ status: 'running', analysis_status: 'completed' }),
      cancelPending: true,
      selectedTotal: 3,
    });

    expect(screen.getByText(/Cancelling/i)).toBeInTheDocument();
    expect(screen.queryByTestId('activity-pulse')).not.toBeInTheDocument();
  });
});

describe('StatusStrip — lifecycle content', () => {
  it('shows actionable paused copy without leaking a missing value', () => {
    renderStrip({
      phase: 'terminal',
      crawl: crawl({
        status: 'paused',
        analysis_status: 'stopped',
        analyzed_count: 0,
        score_summary: null,
      }),
    });

    expect(screen.getByText(/no completed score yet/i)).toBeInTheDocument();
    expect(screen.getByText(/Run a new crawl/i)).toBeInTheDocument();
    expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
  });

  it('shows paused partial results with an explicit refresh action', () => {
    renderStrip({
      phase: 'dashboard',
      crawl: crawl({ status: 'paused', analysis_status: 'stopped' }),
    });

    expect(screen.getByText(/showing the pages analyzed so far/i)).toBeInTheDocument();
    expect(screen.getByText(/Run a new crawl/i)).toBeInTheDocument();
    expect(screen.queryByText(/undefined/i)).not.toBeInTheDocument();
  });

  it('renders discovery mode from the persisted crawl rather than the current entitlement', () => {
    renderStrip({
      phase: 'discovering',
      entitlement: { ...entitlement, access_mode: 'sample' },
      crawl: crawl({
        status: 'running',
        discovery_status: 'running',
        analysis_status: 'pending',
        inventory_complete: false,
        partial_reason: '',
        sample_mode: false,
        score_summary: null,
      }),
    });

    expect(screen.getByText('Pages discovered')).toBeInTheDocument();
    expect(screen.queryByText('Sample pages discovered')).not.toBeInTheDocument();
    expect(screen.queryByText(/page sample of your site/)).not.toBeInTheDocument();
  });

  it('narrates discovery with provisional Starter copy while scanning', () => {
    renderStrip({
      phase: 'discovering',
      crawl: crawl({
        status: 'running',
        discovery_status: 'running',
        analysis_status: 'pending',
        inventory_complete: false,
        partial_reason: '',
        score_summary: null,
      }),
    });

    expect(screen.getByText(/3 pages discovered so far/)).toBeInTheDocument();
  });

  it('freezes behind a starting notice while a fresh crawl create is in flight', () => {
    // The old crawl's phase must not stay in view while a new crawl is being
    // created — a single notice covers the in-flight window.
    renderStrip({ startPending: true, phase: 'terminal', crawl: crawl({ status: 'cancelled' }) });

    expect(screen.getByText(/Starting a fresh crawl/)).toBeInTheDocument();
    expect(screen.queryByText(/Discovery cancelled/)).not.toBeInTheDocument();
  });

  it('keeps the strip container mounted in every phase (canonical-screen invariant)', () => {
    const { rerender } = renderStrip({ phase: 'empty', crawl: null });
    const strip = screen.getByTestId('status-strip');

    for (const [phase, c] of [
      ['discovering', crawl({ discovery_status: 'running', score_summary: null })],
      ['analyzing', crawl({ score_summary: null })],
      ['dashboard', crawl({ status: 'completed' })],
      ['terminal', crawl({ status: 'failed', score_summary: null })],
    ] as const) {
      rerender(
        <StatusStrip
          crawl={c}
          phase={phase}
          entitlement={entitlement}
          cancelPending={false}
          startPending={false}
          pages={[]}
          selectedTotal={null}
          selectedError={false}
        />,
      );
      expect(screen.getByTestId('status-strip')).toBe(strip);
    }
  });
});
