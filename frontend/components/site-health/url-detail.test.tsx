import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';
import type { PageDetail } from '@/lib/api/types';

// Stub next/navigation (unavailable in jsdom). `push` is asserted by the
// created-new-crawl identity-transition test; `searchParams` is mutable so a
// test can simulate landing on `?rerun=1` after that navigation.
const push = vi.fn();
let searchParamsValue = new URLSearchParams();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ push, replace: vi.fn(), back: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => searchParamsValue,
}));

import { UrlDetail } from './url-detail';

const CRAWL = '44444444-4444-4444-8444-444444444444';
const NEW_CRAWL = '55555555-5555-4555-8555-555555555555';
const TASK_ID = '66666666-6666-4666-8666-666666666666';
const URL_ID = 'cccccccc-1111-4111-8111-111111111111';
const ISSUE_H = 'aaaaaaaa-1111-4111-8111-111111111111';
const ISSUE_L = 'bbbbbbbb-1111-4111-8111-111111111111';

function detail(overrides: Partial<PageDetail> = {}): PageDetail {
  return {
    site_url_id: URL_ID,
    crawl_id: CRAWL,
    normalized_url: 'https://acme.com/',
    display_url: 'https://acme.com/',
    title: 'Best&Less Online',
    analysis_status: 'completed',
    error_code: '',
    field_cwv_available: false,
    technical_score: 46,
    aeo_score: 64,
    overall_score: 58,
    issue_count: 2,
    last_audited: '2026-07-16T00:00:00Z',
    page_kind: 'product',
    // A product page that also carries an FAQ: exactly the hybrid a single
    // exclusive page_kind could not express.
    page_traits: ['has_faq', 'has_variants'],
    // Persisted classifier evidence (v2 P1) — a schema-conflict scenario:
    // the path pattern chose Product while the markup declares Article.
    page_kind_evidence: {
      classifier_version: 'sh-classifier-1',
      classified_by: 'path_pattern',
      schema_suggested_type: 'article',
      confidence: 'medium',
      tier: 'route',
      signals: [
        {
          signal: 'path_pattern',
          page_kind: 'product',
          tier: 'route',
          detail: '^/(products?|p|shop)(/|$)',
        },
        {
          signal: 'structured_data',
          page_kind: 'article',
          tier: 'semantic',
          detail: 'Article',
        },
      ],
    },
    facts: {
      title: 'Best&Less Online',
      meta_description: null,
      canonical_url: null,
      robots_directives: [],
      h1_count: 1,
      heading_count: 4,
      image_count: 3,
      image_missing_alt_count: 0,
      word_count: 500,
      internal_link_count: 10,
      external_link_count: 2,
      structured_data_types: [],
    },
    delivery: {
      field_cwv_available: false,
      status_code: 200,
      ttfb_ms: 840,
      wire_bytes: 40000,
      decoded_bytes: 145408,
      html_bytes: 145408,
      http_version: 'HTTP/2',
      compression: 'gzip',
      cache_control: 'no-cache',
      blocking_resource_count: 0,
    },
    internal_links: {
      inbound_count: 12,
      outbound_count: 30,
      main_content_inbound_count: 4,
      main_content_outbound_count: 9,
      nofollow_inbound_count: 1,
      depth_from_home: 2,
      source_page_count: 7,
      top_inbound: [
        {
          site_url_id: 'dddddddd-1111-4111-8111-111111111111',
          url: 'https://acme.com/collections/bags',
          anchor_count: 3,
          main_content: true,
          nofollow: false,
          rel: [],
        },
      ],
      top_outbound: [],
      formula_version: 'sh-link-metrics-1',
    },
    issues: [
      {
        id: ISSUE_L,
        crawl_id: CRAWL,
        rule_id: 'aeo.faq',
        page_kinds: [],
        dimension: 'aeo',
        category: 'schema',
        severity: 'low',
        finding_class: 'defect',
        title: 'FAQ schema not present',
        description: 'FAQ structured data is not present.',
        remediation: '',
        affected_url_count: 1,
        analyzer_version: 'a1',
        rule_version: 'r1',
        created_at: '2026-07-16T00:00:00Z',
      },
      {
        id: ISSUE_H,
        crawl_id: CRAWL,
        rule_id: 'aeo.website_schema',
        page_kinds: [],
        dimension: 'aeo',
        category: 'schema',
        severity: 'high',
        finding_class: 'defect',
        title: 'WebSite schema is missing',
        description: 'WebSite structured data is not present.',
        remediation: '',
        affected_url_count: 1,
        analyzer_version: 'a1',
        rule_version: 'r1',
        created_at: '2026-07-16T00:00:00Z',
      },
    ],
    evaluations: [],
    artifact_id: null,
    extractor_version: 'e1',
    analyzer_version: 'a1',
    rule_version: 'r1',
    scoring_version: 's1',
    ...overrides,
  };
}

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  mswServer.resetHandlers();
  push.mockClear();
  searchParamsValue = new URLSearchParams();
});
afterAll(() => mswServer.close());

function handlers(pageDetail: PageDetail) {
  return [
    http.get(`/api/v1/site-crawls/${CRAWL}/pages/${URL_ID}`, () => HttpResponse.json(pageDetail)),
    http.get(`/api/v1/site-crawls/${CRAWL}/pages/${URL_ID}/issue-history`, () =>
      HttpResponse.json({ items: [], next_cursor: null }),
    ),
  ];
}

describe('UrlDetail', () => {
  it('renders scores, delivery metrics, and severity-ordered issues', async () => {
    mswServer.use(...handlers(detail()));

    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);

    expect(
      await screen.findByRole('heading', { name: 'Best&Less Online', level: 1 }),
    ).toBeInTheDocument();
    // The header carries the v2 P1 page-kind badge.
    expect(screen.getByText('Page Kind')).toBeInTheDocument();
    expect(screen.getByText('Product')).toBeInTheDocument();
    // Delivery metric: TTFB rendered with ms suffix.
    expect(screen.getByText('840ms')).toBeInTheDocument();
    expect(screen.getByText('200')).toBeInTheDocument();
    // Issues section header shows the count.
    expect(screen.getByText('All Issues (2)')).toBeInTheDocument();

    // High-severity issue is ordered before the low-severity one.
    const high = screen.getByText('WebSite schema is missing');
    const low = screen.getByText('FAQ schema not present');
    expect(high.compareDocumentPosition(low) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it('shows observed traits beside the page kind, so a hybrid page reads as both', async () => {
    // page_kind is exclusive and answers "what is this page for". A trait is
    // additive and answers "what else is on it", so a product page carrying an
    // FAQ shows both rather than being filed as one or the other.
    mswServer.use(...handlers(detail()));
    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);
    expect(await screen.findByText('Also on this page')).toBeInTheDocument();
    expect(screen.getByText('Has an FAQ')).toBeInTheDocument();
    expect(screen.getByText('Has variants')).toBeInTheDocument();
  });

  it('renders no traits row when nothing was observed', async () => {
    // An empty list is a real answer, not a gap that wants a placeholder.
    mswServer.use(...handlers(detail({ page_traits: [] })));
    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);
    expect(await screen.findByText('Page Kind')).toBeInTheDocument();
    expect(screen.queryByText('Also on this page')).not.toBeInTheDocument();
  });

  it('discloses the persisted classifier evidence via the "why this type?" toggle', async () => {
    mswServer.use(...handlers(detail()));
    const user = userEvent.setup();

    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);

    await screen.findByRole('heading', { name: 'Best&Less Online', level: 1 });
    // Collapsed by default: the toggle advertises the schema conflict, the
    // panel is not rendered.
    const toggle = screen.getByRole('button', {
      name: 'Why this page kind? Schema markup disagrees.',
    });
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText('Classified by')).not.toBeInTheDocument();

    await user.click(toggle);

    expect(toggle).toHaveAttribute('aria-expanded', 'true');
    // Verdict facts: winning signal (shown as the verdict AND as the winning
    // signal row), the confidence label, signals count.
    expect(screen.getByText('Classified by')).toBeInTheDocument();
    expect(screen.getAllByText('path_pattern')).toHaveLength(2);
    expect(screen.getByText('Medium — URL family')).toBeInTheDocument();
    expect(screen.getByText('Signals matched')).toBeInTheDocument();
    // The schema conflict is highlighted, naming both types.
    const note = screen.getByRole('note');
    expect(note).toHaveTextContent('Schema markup on this page declares Article');
    expect(note).toHaveTextContent('treated as Product');
    // Ranked signals with their evidence tier; the winner carries "chosen".
    expect(screen.getByText('structured_data')).toBeInTheDocument();
    expect(screen.getAllByText('route')).not.toHaveLength(0);
    expect(screen.getByText('chosen')).toBeInTheDocument();
    expect(screen.getByText('sh-classifier-1')).toBeInTheDocument();

    // Collapsing hides the panel again.
    await user.click(toggle);
    expect(screen.queryByText('Classified by')).not.toBeInTheDocument();
  });

  it('hides the "why this type?" toggle when no classifier evidence was persisted', async () => {
    mswServer.use(...handlers(detail({ page_kind_evidence: null })));

    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);

    await screen.findByRole('heading', { name: 'Best&Less Online', level: 1 });
    // The badge still renders; only the disclosure is withheld.
    expect(screen.getByText('Product')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /why this page kind/i })).not.toBeInTheDocument();
  });

  it('renders the not-measured state for a missing score, never a zero', async () => {
    mswServer.use(
      ...handlers(detail({ technical_score: null, aeo_score: null, overall_score: null })),
    );

    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);

    await screen.findByRole('heading', { name: 'Best&Less Online', level: 1 });
    expect(screen.getAllByText('Not measured').length).toBeGreaterThan(0);
  });

  it('renders the placeholder (not "no-cache") for a missing Cache-Control header', async () => {
    mswServer.use(
      ...handlers(
        detail({
          delivery: {
            field_cwv_available: false,
            status_code: 200,
            ttfb_ms: 840,
            wire_bytes: 40000,
            decoded_bytes: 145408,
            html_bytes: 145408,
            http_version: 'HTTP/2',
            compression: 'gzip',
            cache_control: null,
            blocking_resource_count: 0,
          },
        }),
      ),
    );

    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);

    await screen.findByRole('heading', { name: 'Best&Less Online', level: 1 });
    expect(screen.queryByText('no-cache')).not.toBeInTheDocument();
    expect(screen.getAllByText('Not measured').length).toBeGreaterThan(0);
  });

  it('renders the placeholder (not "0ms") for an unmeasured TTFB (B6)', async () => {
    mswServer.use(
      ...handlers(
        detail({
          delivery: {
            field_cwv_available: false,
            status_code: 200,
            ttfb_ms: 0,
            wire_bytes: 40000,
            decoded_bytes: 145408,
            html_bytes: 145408,
            http_version: 'HTTP/2',
            compression: 'gzip',
            cache_control: 'no-cache',
            blocking_resource_count: 0,
          },
        }),
      ),
    );

    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);

    await screen.findByRole('heading', { name: 'Best&Less Online', level: 1 });
    // A 0 ms reading is an unmeasured hop, never an instant response.
    expect(screen.queryByText('0ms')).not.toBeInTheDocument();
    expect(screen.getAllByText('Not measured').length).toBeGreaterThan(0);
    // Byte counts do NOT share the zero rule — they still render normally.
    expect(screen.getByText('39.1 KB')).toBeInTheDocument();
  });

  it('same-active-crawl rerun: polls in place through completed → pending → running → completed without navigating', async () => {
    // The rerun response points at the SAME crawl/URL (created_new_crawl
    // false), so the component must poll in place — never navigate.
    //
    // Sequence of `analysis_status` snapshots the GET handler serves on
    // each successive request. The first GET (initial render) sees
    // 'completed'. The rerun POST enqueues a fresh task, after which the
    // *next* GETs must walk through 'pending' then 'running' before
    // landing on a new 'completed' — proving polling doesn't stop on the
    // stale cached terminal status right after the mutation resolves.
    const statuses: PageDetail['analysis_status'][] = [
      'completed',
      'pending',
      'running',
      'completed',
    ];
    let getCallCount = 0;

    mswServer.use(
      http.get(`/api/v1/site-crawls/${CRAWL}/pages/${URL_ID}`, async () => {
        const status = statuses[Math.min(getCallCount, statuses.length - 1)];
        getCallCount += 1;
        // Small artificial network delay so the mutation's own
        // `invalidateQueries` refetch (triggered inside `onSuccess`) does
        // not resolve synchronously before the next render — this
        // reproduces the real race where React re-renders with
        // `rerunPolling` newly `true` while the query cache still holds
        // the *previous* terminal snapshot.
        await new Promise((resolve) => {
          setTimeout(resolve, 15);
        });
        return HttpResponse.json(detail({ analysis_status: status }));
      }),
      http.get(`/api/v1/site-crawls/${CRAWL}/pages/${URL_ID}/issue-history`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
      http.post(`/api/v1/site-crawls/${CRAWL}/pages/${URL_ID}/rerun`, () =>
        HttpResponse.json(
          {
            crawl_id: CRAWL,
            site_url_id: URL_ID,
            task_id: TASK_ID,
            created_new_crawl: false,
            analysis_status: 'pending',
          },
          { status: 202 },
        ),
      ),
    );

    const user = userEvent.setup();
    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);

    // Initial fetch observes the prior run's terminal 'completed' snapshot.
    await screen.findByRole('heading', { name: 'Best&Less Online', level: 1 });
    expect(screen.getByRole('button', { name: 'Re-audit this page' })).toBeInTheDocument();
    expect(screen.getByText('Completed')).toBeInTheDocument();

    await user.click(screen.getByRole('button', { name: 'Re-audit this page' }));

    // The status badge must actually be observed to reach 'Running' at
    // some point (not just eventually land back on 'Completed', which the
    // stale pre-rerun cache would already show without ever polling
    // further).
    await waitFor(() => expect(screen.getByText('Running')).toBeInTheDocument(), {
      timeout: 15_000,
    });

    // Polling continues past 'running' until the freshly-enqueued task
    // reaches its own terminal 'completed' snapshot.
    await waitFor(() => expect(screen.getByText('Completed')).toBeInTheDocument(), {
      timeout: 15_000,
    });

    await waitFor(() => expect(getCallCount).toBeGreaterThanOrEqual(statuses.length), {
      timeout: 15_000,
    });

    await waitFor(
      () => expect(screen.getByRole('button', { name: 'Re-audit queued' })).toBeInTheDocument(),
      { timeout: 15_000 },
    );

    // A same-crawl rerun never navigates.
    expect(push).not.toHaveBeenCalled();
  }, 20_000);

  it('created_new_crawl rerun: navigates to the fresh crawl identity detail route with ?rerun=1', async () => {
    mswServer.use(
      ...handlers(detail({ analysis_status: 'completed' })),
      http.post(`/api/v1/site-crawls/${CRAWL}/pages/${URL_ID}/rerun`, () =>
        HttpResponse.json(
          {
            crawl_id: NEW_CRAWL,
            site_url_id: URL_ID,
            task_id: TASK_ID,
            created_new_crawl: true,
            analysis_status: 'pending',
          },
          { status: 202 },
        ),
      ),
    );

    const user = userEvent.setup();
    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);

    await screen.findByRole('heading', { name: 'Best&Less Online', level: 1 });
    await user.click(screen.getByRole('button', { name: 'Re-audit this page' }));

    // The rerun ran in a NEW crawl, so the client routes to that fresh
    // identity's canonical detail route (with ?rerun=1 to auto-start polling
    // on the new mount) rather than continuing to poll the terminal source.
    await waitFor(() =>
      expect(push).toHaveBeenCalledWith(`/site/crawls/${NEW_CRAWL}/pages/${URL_ID}?rerun=1`),
    );
    expect(push).toHaveBeenCalledTimes(1);
  });

  it('shows a helpful alert when rerun is rejected for an unmonitored page', async () => {
    mswServer.use(
      ...handlers(detail({ analysis_status: 'completed' })),
      http.post(`/api/v1/site-crawls/${CRAWL}/pages/${URL_ID}/rerun`, () =>
        HttpResponse.json({ detail: 'rerun_not_allowed' }, { status: 409 }),
      ),
    );

    const user = userEvent.setup();
    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);

    await screen.findByRole('heading', { name: 'Best&Less Online', level: 1 });
    await user.click(screen.getByRole('button', { name: 'Re-audit this page' }));

    // `role="alert"` does not take its accessible name from its contents, so
    // find the alert and assert on its text.
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent(
      'This page is not in your monitored set — add it before re-auditing.',
    );
  });

  it('landing on a fresh rerun crawl with ?rerun=1 begins polling immediately', async () => {
    searchParamsValue = new URLSearchParams('rerun=1');

    const statuses: PageDetail['analysis_status'][] = ['pending', 'running', 'completed'];
    let getCallCount = 0;

    mswServer.use(
      http.get(`/api/v1/site-crawls/${NEW_CRAWL}/pages/${URL_ID}`, () => {
        const status = statuses[Math.min(getCallCount, statuses.length - 1)];
        getCallCount += 1;
        return HttpResponse.json(detail({ crawl_id: NEW_CRAWL, analysis_status: status }));
      }),
      http.get(`/api/v1/site-crawls/${NEW_CRAWL}/pages/${URL_ID}/issue-history`, () =>
        HttpResponse.json({ items: [], next_cursor: null }),
      ),
    );

    renderWithProviders(<UrlDetail crawlId={NEW_CRAWL} siteUrlId={URL_ID} />);

    // No button click: `?rerun=1` seeds polling on mount, so the fresh run's
    // progress advances to its terminal snapshot on its own.
    await screen.findByRole('heading', { name: 'Best&Less Online', level: 1 });
    await waitFor(() => expect(screen.getByText('Completed')).toBeInTheDocument(), {
      timeout: 15_000,
    });
    expect(getCallCount).toBeGreaterThanOrEqual(statuses.length);
  }, 20_000);

  it('renders the internal-links section with linked neighbours', async () => {
    mswServer.use(...handlers(detail()));

    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);

    await screen.findByRole('heading', { name: 'Best&Less Online', level: 1 });
    expect(screen.getByRole('heading', { name: 'Internal Links' })).toBeInTheDocument();
    // Inbound and main-content inbound are different facts and both are shown.
    expect(screen.getByText('Main-content inbound')).toBeInTheDocument();
    expect(screen.getByText('Counted across 7 crawled pages')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'https://acme.com/collections/bags' })).toHaveAttribute(
      'href',
      `/site/crawls/${CRAWL}/pages/dddddddd-1111-4111-8111-111111111111`,
    );
    expect(screen.getByText('This page links to no other crawled page.')).toBeInTheDocument();
  });

  it('omits the internal-links section entirely when the crawl measured none', async () => {
    mswServer.use(...handlers(detail({ internal_links: null })));

    renderWithProviders(<UrlDetail crawlId={CRAWL} siteUrlId={URL_ID} />);

    await screen.findByRole('heading', { name: 'Best&Less Online', level: 1 });
    // Absent, not zeroed: "not measured" and "nothing links here" differ.
    expect(screen.queryByRole('heading', { name: 'Internal Links' })).not.toBeInTheDocument();
  });
});
