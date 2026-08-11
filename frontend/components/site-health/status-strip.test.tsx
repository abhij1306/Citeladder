import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';

import { StatusStrip } from './status-strip';
import type { PageSummary, SiteCrawl, SiteHealthEntitlement } from '@/lib/api/types';

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
    technical_score: 46,
    aeo_score: 64,
    overall_score: 55,
    last_audited: '2026-07-16T00:00:00Z',
    page_kind: 'article',
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
      by_page_kind: {},
    },
    discovered_count: 3,
    total_url_count: 3,
    has_more_site_urls: false,
    score_summary: {
      overall_score: null,
      technical_score: null,
      aeo_score: null,
      selected_count: 3,
      analyzed_count: 1,
      issue_count: 0,
      scoring_version: 's1',
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
  it('derives "Completed" from the server-aggregated analyzed_count, not a truncated pages window', () => {
    // Only ONE monitored page is present in this (deliberately truncated)
    // `pages` prop, but the crawl-wide score_summary says 1 of 3 is analyzed.
    // The "Completed" count must reflect the authoritative aggregate.
    renderStrip({ pages: [page({ analysis_status: 'completed' })], selectedTotal: 3 });

    const totalLabel = screen.getByText('Total pages');
    expect(totalLabel.parentElement?.textContent).toContain('3');
    const completedLabel = screen.getByText('Completed');
    const completedValue = completedLabel.parentElement?.querySelector('.text-run-completed');
    expect(completedValue?.textContent).toBe('1');
  });

  it('shows — for Queued (not a false 0) while the selected total is unknown', () => {
    // No terminal score_summary yet AND the per-project monitored count has not
    // loaded (selectedTotal=null): the total is genuinely unknown, so Queued
    // must render the em-dash placeholder rather than a misleading 0.
    renderStrip({ crawl: crawl({ score_summary: null, analyzed_count: 0 }), selectedTotal: null });

    const queuedLabel = screen.getByText('Queued');
    expect(queuedLabel.parentElement?.textContent).toContain('—');
    const totalLabel = screen.getByText('Total pages');
    expect(totalLabel.parentElement?.textContent).toContain('—');
  });

  it('shows a real Queued count once the selected total is known', () => {
    renderStrip({
      crawl: crawl({ score_summary: null, analyzed_count: 1, failed_count: 0 }),
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

    expect(screen.getByText(/Could not load the selected-page count/)).toBeInTheDocument();
  });
});

describe('StatusStrip — link-check phase', () => {
  // The regression this covers: every page reports Completed while the crawl
  // stays "running" through its link-check tasks. The old copy still claimed
  // pages were being audited, so a working crawl looked frozen and got
  // cancelled — which in turn skipped the opportunities recompute.
  it('narrates link checking once analysis is terminal but the crawl is still running', () => {
    renderStrip({
      crawl: crawl({ status: 'running', analysis_status: 'completed' }),
      selectedTotal: 3,
    });

    expect(screen.getByText(/checking their links/i)).toBeInTheDocument();
    expect(screen.queryByText(/Auditing selected pages/i)).not.toBeInTheDocument();
  });

  it('shows the live pulse while link checking so still counters do not read as hung', () => {
    renderStrip({
      crawl: crawl({ status: 'running', analysis_status: 'completed' }),
      selectedTotal: 3,
    });

    expect(screen.getByTestId('activity-pulse')).toBeInTheDocument();
  });

  it('keeps the audit copy (and no pulse) while analysis is genuinely still running', () => {
    renderStrip({
      crawl: crawl({ status: 'running', analysis_status: 'running', score_summary: null }),
      selectedTotal: 3,
    });

    expect(screen.getByText(/Auditing selected pages/i)).toBeInTheDocument();
    expect(screen.queryByTestId('activity-pulse')).not.toBeInTheDocument();
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
  it('narrates discovery with provisional Starter copy while scanning', () => {
    renderStrip({
      phase: 'discovering',
      crawl: crawl({
        status: 'running',
        discovery_status: 'running',
        analysis_status: 'pending',
        inventory_complete: false,
        score_summary: null,
      }),
    });

    expect(screen.getByText(/3 pages discovered so far/)).toBeInTheDocument();
  });

  it('freezes behind a starting notice while a fresh crawl create is in flight', () => {
    // The old crawl's phase must not stay in view while a new crawl is being
    // created — a single notice covers the in-flight window.
    renderStrip({ startPending: true, phase: 'selection', crawl: crawl({ status: 'cancelled' }) });

    expect(screen.getByText(/Starting a fresh crawl/)).toBeInTheDocument();
    expect(screen.queryByText(/Discovery cancelled/)).not.toBeInTheDocument();
  });

  it('keeps the strip container mounted in every phase (canonical-screen invariant)', () => {
    const { rerender } = renderStrip({ phase: 'empty', crawl: null });
    const strip = screen.getByTestId('status-strip');

    for (const [phase, c] of [
      ['discovering', crawl({ discovery_status: 'running', score_summary: null })],
      ['selection', crawl({ status: 'cancelled', score_summary: null })],
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
