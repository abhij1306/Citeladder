import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';

import { queryKeys } from './query-keys';
import {
  cursorPageSchema,
  inventoryRowSchema,
  monitoredUrlsResponseSchema,
  pageDetailSchema,
  rerunPageResponseSchema,
  siteCrawlSchema,
  siteHealthEntitlementSchema,
  siteHealthErrorSchema,
  siteIssueSchema,
  urlPreviewResponseSchema,
  strictValidate,
} from './schemas';
import { siteHealthApi } from './site-health';
import { mswServer } from '@/test/msw-server';
import { z } from 'zod';

const UUID = '11111111-1111-4111-8111-111111111111';
const UUID2 = '22222222-2222-4222-8222-222222222222';

const entitlement = {
  workspace_id: UUID,
  access_mode: 'full' as const,
  sample_url_limit: 10,
  monitored_url_limit: 50,
  count_disclosure: true,
  resolver_status: 'resolved' as const,
  registry_revision: 'registry-v8',
  entitlement_lifecycle_version: 3,
  valid_until: null,
  contributing_grant_ids: [UUID2],
  advanced_controls_enabled: false,
};

// The real bounded site-facts blob the worker persists (`_crawl_setup` in
// backend/app/workers/site_health_worker.py) — robots AI-crawler stance,
// llms.txt probe, sitemap file list. No discovered totals inside.
const siteFacts = {
  robots: {
    fetched: true,
    url: 'https://example.com/robots.txt',
    status_code: 200,
    ai_crawlers: {
      GPTBot: 'block',
      ClaudeBot: 'allow',
      PerplexityBot: 'allow',
      'Google-Extended': 'allow',
    },
    sitemaps: ['https://example.com/sitemap.xml'],
  },
  llms_txt: { fetched: true, url: 'https://example.com/llms.txt', status_code: 200, present: true },
  sitemap: { fetched: false, files: [] },
};

const crawl = {
  id: UUID,
  workspace_id: UUID,
  project_id: UUID2,
  profile_id: UUID2,
  status: 'running' as const,
  discovery_status: 'running' as const,
  analysis_status: 'pending' as const,
  root_url: 'https://example.com/',
  sample_mode: false,
  seed: '12345',
  inventory_complete: false,
  visible_url_count: 42,
  analyzed_count: 0,
  failed_count: 0,
  discovery_requested_count: 42,
  analysis_requested_count: 0,
  counters: {
    discovered: 42,
    selected: 0,
    queued: 0,
    running: 0,
    analyzed: 0,
    errors: 0,
    blocked: 0,
    by_page_type: {},
  },
  total_url_count: null,
  score_summary: null,
  failure_summary: null,
  site_facts: siteFacts,
  extractor_version: 'x1',
  analyzer_version: 'a1',
  rule_version: 'r1',
  scoring_version: 's1',
  error_message: '',
  created_at: '2026-07-15T00:00:00Z',
  updated_at: '2026-07-15T00:00:00Z',
  started_at: null,
  completed_at: null,
};

const inventoryRow = {
  site_url_id: UUID,
  normalized_url: 'https://example.com/a',
  display_url: 'https://example.com/a',
  title: null,
  content_type: null,
  source: 'link' as const,
  depth: 1,
  monitored: false,
  first_seen_at: null,
  last_seen_at: null,
  issue_count: null,
  technical_score: null,
  aeo_score: null,
  overall_score: null,
  last_audited: null,
  page_type: null,
};

describe('siteHealthEntitlementSchema (quota authority)', () => {
  it('accepts a valid entitlement and exposes monitored_url_limit', () => {
    const parsed = strictValidate(siteHealthEntitlementSchema, entitlement, 'ent');
    expect(parsed.monitored_url_limit).toBe(50);
  });

  it('strips an additive key (tolerant-on-unknown)', () => {
    const parsed = strictValidate(
      siteHealthEntitlementSchema,
      { ...entitlement, hardcoded_50: true },
      'ent',
    );
    expect('hardcoded_50' in parsed).toBe(false);
  });

  it('rejects a missing required field', () => {
    const { monitored_url_limit: _omit, ...rest } = entitlement;
    expect(() => strictValidate(siteHealthEntitlementSchema, rest, 'ent')).toThrow();
  });

  // Site Health carries NO commercial vocabulary. A retired plan-shaped
  // payload must fail rather than parse into a neutral entitlement.
  it('rejects a retired plan-shaped entitlement', () => {
    const { access_mode: _drop, ...planShaped } = entitlement;
    expect(() =>
      strictValidate(siteHealthEntitlementSchema, { ...planShaped, plan_key: 'starter' }, 'ent'),
    ).toThrow();
  });

  it('rejects an unknown resolver status', () => {
    expect(() =>
      strictValidate(
        siteHealthEntitlementSchema,
        { ...entitlement, resolver_status: 'trial' },
        'ent',
      ),
    ).toThrow();
  });

  it('accepts the backend fail-closed access mode', () => {
    const parsed = strictValidate(
      siteHealthEntitlementSchema,
      {
        ...entitlement,
        access_mode: 'unresolved',
        monitored_url_limit: 0,
        count_disclosure: false,
        resolver_status: 'entitlement_unresolved',
        contributing_grant_ids: [],
      },
      'ent',
    );
    expect(parsed.access_mode).toBe('unresolved');
  });
});

describe('URL preview contract', () => {
  beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
  afterEach(() => mswServer.resetHandlers());
  afterAll(() => mswServer.close());
  it('uses the same-origin preview endpoint and preserves exclusion reasons', async () => {
    mswServer.use(
      http.post('/api/v1/site-crawls/url-preview', async ({ request }) => {
        expect(await request.json()).toMatchObject({
          project_id: UUID2,
          content: 'https://example.com/login',
        });
        return HttpResponse.json({
          items: [
            {
              row: 1,
              input: 'https://example.com/login',
              accepted: false,
              canonical_url: null,
              reason_code: 'excluded_auth_path',
              value_kind: 'other',
              priority: 0,
            },
          ],
          truncated: false,
          counts: { excluded_auth_path: 1 },
          policy_version: 'admission-v1',
        });
      }),
    );
    const preview = await siteHealthApi.previewUrls({
      project_id: UUID2,
      content: 'https://example.com/login',
    });
    expect(preview.items[0]?.reason_code).toBe('excluded_auth_path');
    expect(strictValidate(urlPreviewResponseSchema, preview, 'preview').policy_version).toBe(
      'admission-v1',
    );
  });
});

describe('siteCrawlSchema (Free redaction / nullable totals)', () => {
  it('accepts a running crawl with a null total (provisional)', () => {
    const parsed = strictValidate(siteCrawlSchema, crawl, 'crawl');
    expect(parsed.total_url_count).toBeNull();
  });

  it('accepts a Free sample crawl with total_url_count null and no leaked total', () => {
    const sample = { ...crawl, sample_mode: true, inventory_complete: true, total_url_count: null };
    expect(strictValidate(siteCrawlSchema, sample, 'crawl').sample_mode).toBe(true);
  });

  it('strips an unexpected count-bearing key on a crawl (no leaked total)', () => {
    // A leaked total must never reach app state — stripped on parse.
    const parsed = strictValidate(siteCrawlSchema, { ...crawl, hidden_full_total: 9999 }, 'crawl');
    expect('hidden_full_total' in parsed).toBe(false);
  });
});

describe('siteHealthApi.getCrawl site_facts (v2 P2 contract)', () => {
  beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
  afterEach(() => mswServer.resetHandlers());
  afterAll(() => mswServer.close());

  it('validates a real crawl response carrying a populated site_facts', async () => {
    // Regression: the backend ALWAYS serializes `site_facts`, so a strict
    // schema without the field made every crawl read throw
    // "API validation failure in siteHealth.getCrawl".
    mswServer.use(http.get(`/api/v1/site-crawls/${UUID}`, () => HttpResponse.json(crawl)));
    const result = await siteHealthApi.getCrawl(UUID);
    expect(result.site_facts).toEqual(siteFacts);
  });

  it('rejects a crawl response missing site_facts (drift fails loud)', async () => {
    const { site_facts: _omitted, ...withoutSiteFacts } = crawl;
    mswServer.use(
      http.get(`/api/v1/site-crawls/${UUID}`, () => HttpResponse.json(withoutSiteFacts)),
    );
    await expect(siteHealthApi.getCrawl(UUID)).rejects.toThrow(
      /API validation failure in siteHealth\.getCrawl/,
    );
  });
});

describe('siteCrawlSchema site_facts (v2 P2 contract)', () => {
  it('accepts a populated site_facts blob as the worker persists it', () => {
    const parsed = strictValidate(siteCrawlSchema, crawl, 'siteHealth.getCrawl');
    const robots = parsed.site_facts?.robots as { ai_crawlers: Record<string, string> };
    expect(robots.ai_crawlers.GPTBot).toBe('block');
    expect(parsed.site_facts?.llms_txt).toEqual({
      fetched: true,
      url: 'https://example.com/llms.txt',
      status_code: 200,
      present: true,
    });
  });

  it('accepts a null site_facts (crawl setup has not run yet)', () => {
    const parsed = strictValidate(
      siteCrawlSchema,
      { ...crawl, site_facts: null },
      'siteHealth.getCrawl',
    );
    expect(parsed.site_facts).toBeNull();
  });

  it('rejects a crawl payload that omits site_facts (required, never optional)', () => {
    // The backend response model always serializes the key, so a missing key
    // is real drift — keeping it required is what pins that contract.
    const { site_facts: _omitted, ...withoutSiteFacts } = crawl;
    expect(() =>
      strictValidate(siteCrawlSchema, withoutSiteFacts, 'siteHealth.getCrawl'),
    ).toThrow();
  });
});

describe('siteScoreSummarySchema by_page_type (v2 P1)', () => {
  const scoreSummary = {
    overall_score: 71,
    technical_score: 80,
    aeo_score: 62,
    selected_count: 10,
    analyzed_count: 4,
    issue_count: 3,
    scoring_version: 's1',
    by_page_type: {
      homepage: { analyzed_count: 1, technical_score: 90.5, aeo_score: 70, overall_score: 80.2 },
      article: { analyzed_count: 3, technical_score: null, aeo_score: null, overall_score: null },
    },
  };

  it('accepts a score summary with a per-page-type breakdown', () => {
    const parsed = strictValidate(
      siteCrawlSchema,
      { ...crawl, score_summary: scoreSummary },
      'crawl',
    );
    expect(parsed.score_summary?.by_page_type.homepage?.analyzed_count).toBe(1);
    expect(parsed.score_summary?.by_page_type.article?.overall_score).toBeNull();
  });

  it('accepts an empty by_page_type map (nothing classified yet)', () => {
    const parsed = strictValidate(
      siteCrawlSchema,
      { ...crawl, score_summary: { ...scoreSummary, by_page_type: {} } },
      'crawl',
    );
    expect(parsed.score_summary?.by_page_type).toEqual({});
  });

  it('strips an additive key inside a by_page_type bucket (tolerant-on-unknown)', () => {
    const bad = {
      ...scoreSummary,
      by_page_type: {
        homepage: { ...scoreSummary.by_page_type.homepage, discovered_total: 9999 },
      },
    };
    const parsed = strictValidate(siteCrawlSchema, { ...crawl, score_summary: bad }, 'crawl');
    expect(parsed.score_summary?.by_page_type.homepage?.analyzed_count).toBe(1);
    expect('discovered_total' in (parsed.score_summary?.by_page_type.homepage ?? {})).toBe(false);
  });
});

describe('inventoryRowSchema (nullable analysis summaries)', () => {
  it('accepts null analysis summaries before analysis completes', () => {
    const parsed = strictValidate(inventoryRowSchema, inventoryRow, 'row');
    expect(parsed.overall_score).toBeNull();
    expect(parsed.issue_count).toBeNull();
    expect(parsed.page_type).toBeNull();
  });

  it('accepts populated analysis summaries after analysis', () => {
    const analysed = {
      ...inventoryRow,
      issue_count: 3,
      technical_score: 88.5,
      aeo_score: 72,
      overall_score: 80.2,
      last_audited: '2026-07-15T00:00:00Z',
      page_type: 'article',
    };
    const parsed = strictValidate(inventoryRowSchema, analysed, 'row');
    expect(parsed.issue_count).toBe(3);
    expect(parsed.page_type).toBe('article');
  });

  it('accepts the expanded page-type taxonomy emitted by the classifier', () => {
    const parsed = strictValidate(
      inventoryRowSchema,
      { ...inventoryRow, page_type: 'service' },
      'row',
    );
    expect(parsed.page_type).toBe('service');
  });

  it('rejects an unknown page_type vocabulary value', () => {
    expect(() =>
      strictValidate(inventoryRowSchema, { ...inventoryRow, page_type: 'landing_page' }, 'row'),
    ).toThrow();
  });

  it('strips an additive key on an inventory row (tolerant-on-unknown)', () => {
    const parsed = strictValidate(inventoryRowSchema, { ...inventoryRow, sort_rank: 1 }, 'row');
    expect('sort_rank' in parsed).toBe(false);
  });
});

describe('cursorPageSchema', () => {
  const page = cursorPageSchema(inventoryRowSchema);

  it('accepts a page with a null next_cursor (last page)', () => {
    const parsed = strictValidate(page, { items: [inventoryRow], next_cursor: null }, 'page');
    expect(parsed.next_cursor).toBeNull();
  });

  it('accepts a page with a cursor', () => {
    const parsed = strictValidate(page, { items: [], next_cursor: 'opaque==' }, 'page');
    expect(parsed.next_cursor).toBe('opaque==');
  });

  it('strips an offset / page-total field (no count side channel)', () => {
    // No count side channel: a leaked total is stripped from parsed output.
    const parsed = strictValidate(page, { items: [], next_cursor: null, total: 25000 }, 'page');
    expect('total' in parsed).toBe(false);
  });
});

describe('monitoredUrlSchema', () => {
  it('accepts bootstrap selections created during onboarding', () => {
    const parsed = strictValidate(
      monitoredUrlsResponseSchema,
      {
        project_id: UUID,
        selection_version: 1,
        monitored_urls: [
          {
            site_url_id: UUID2,
            normalized_url: 'https://example.com/',
            display_url: 'https://example.com/',
            title: null,
            active: true,
            selection_source: 'bootstrap',
            selected_at: null,
            deselected_at: null,
          },
        ],
        quota: { used: 1, limit: 50 },
      },
      'monitored',
    );
    expect(parsed.monitored_urls[0]?.selection_source).toBe('bootstrap');
  });
});

describe('monitoredUrlsResponseSchema', () => {
  const response = {
    project_id: UUID,
    selection_version: 4,
    monitored_urls: [
      {
        site_url_id: UUID2,
        normalized_url: 'https://example.com/',
        display_url: 'https://example.com/',
        title: 'Home',
        active: true,
        selection_source: 'user' as const,
        selected_at: '2026-07-15T00:00:00Z',
        deselected_at: null,
      },
    ],
    quota: { used: 1, limit: 50 },
  };

  it('accepts a monitored set with quota + version', () => {
    const parsed = strictValidate(monitoredUrlsResponseSchema, response, 'mon');
    expect(parsed.quota.limit).toBe(50);
    expect(parsed.selection_version).toBe(4);
  });

  it('rejects an invalid selection_source', () => {
    const bad = {
      ...response,
      monitored_urls: [{ ...response.monitored_urls[0], selection_source: 'admin' }],
    };
    expect(() => strictValidate(monitoredUrlsResponseSchema, bad, 'mon')).toThrow();
  });
});

describe('pageDetailSchema (field_cwv_available literal false)', () => {
  const detail = {
    site_url_id: UUID,
    crawl_id: UUID2,
    normalized_url: 'https://example.com/',
    display_url: 'https://example.com/',
    title: 'Home',
    analysis_status: 'completed' as const,
    error_code: '',
    field_cwv_available: false as const,
    technical_score: 90,
    aeo_score: 80,
    overall_score: 85,
    issue_count: 2,
    last_audited: '2026-07-15T00:00:00Z',
    page_type: 'homepage',
    // T5 contract: the backend page-detail serializer always carries this key
    // (null until the URL has an analysis) — the fixture must include it.
    page_type_evidence: null,
    facts: {
      title: 'Home',
      meta_description: null,
      canonical_url: null,
      robots_directives: [],
      h1_count: 1,
      heading_count: 5,
      image_count: 3,
      image_missing_alt_count: 0,
      word_count: 500,
      internal_link_count: 10,
      external_link_count: 2,
      structured_data_types: ['Organization'],
    },
    delivery: {
      field_cwv_available: false as const,
      status_code: 200,
      ttfb_ms: 120,
      wire_bytes: 4096,
      decoded_bytes: 8192,
      html_bytes: 8192,
      http_version: 'HTTP/2',
      compression: 'gzip',
      cache_control: 'max-age=3600',
      blocking_resource_count: 1,
    },
    issues: [],
    evaluations: [],
    link_references: [],
    artifact_id: UUID,
    extractor_version: 'x1',
    analyzer_version: 'a1',
    rule_version: 'r1',
    scoring_version: 's1',
  };

  it('accepts a full page detail with field_cwv_available false', () => {
    expect(strictValidate(pageDetailSchema, detail, 'page').field_cwv_available).toBe(false);
  });

  it('rejects field_cwv_available true (crawler never fabricates field CWV)', () => {
    expect(() =>
      strictValidate(pageDetailSchema, { ...detail, field_cwv_available: true }, 'page'),
    ).toThrow();
  });

  it('strips a leaked LCP field (crawler never fabricates field CWV)', () => {
    const parsed = strictValidate(pageDetailSchema, { ...detail, lcp_ms: 1200 }, 'page');
    expect('lcp_ms' in parsed).toBe(false);
  });
});

describe('rerunPageResponseSchema (rerun identity/status)', () => {
  const base = {
    crawl_id: UUID,
    site_url_id: UUID2,
    task_id: UUID,
    created_new_crawl: true,
    analysis_status: 'pending' as const,
  };

  it('accepts a fresh-crawl rerun response', () => {
    const parsed = strictValidate(rerunPageResponseSchema, base, 'rerun');
    expect(parsed.created_new_crawl).toBe(true);
    expect(parsed.crawl_id).toBe(UUID);
  });

  it('accepts a same-active-crawl rerun response', () => {
    const parsed = strictValidate(
      rerunPageResponseSchema,
      { ...base, created_new_crawl: false, analysis_status: 'running' },
      'rerun',
    );
    expect(parsed.created_new_crawl).toBe(false);
  });

  it('rejects an unknown analysis_status', () => {
    expect(() =>
      strictValidate(rerunPageResponseSchema, { ...base, analysis_status: 'queued' }, 'rerun'),
    ).toThrow();
  });

  it('strips an additive field (tolerant-on-unknown)', () => {
    const parsed = strictValidate(
      rerunPageResponseSchema,
      { ...base, new_crawl_id: UUID },
      'rerun',
    );
    expect('new_crawl_id' in parsed).toBe(false);
  });
});

describe('siteIssueSchema + siteHealthErrorSchema', () => {
  it('accepts a valid issue row', () => {
    const issue = {
      id: UUID,
      crawl_id: UUID2,
      rule_id: 'meta.title.missing',
      dimension: 'aeo' as const,
      category: 'metadata',
      severity: 'high' as const,
      title: 'Missing title',
      remediation: 'Add a <title>.',
      affected_url_count: 4,
      analyzer_version: 'a1',
      rule_version: 'r1',
      created_at: '2026-07-15T00:00:00Z',
    };
    expect(strictValidate(siteIssueSchema, issue, 'issue').severity).toBe('high');
  });

  it('accepts a quota error carrying limit + currently_used', () => {
    const err = {
      code: 'site_health_quota_exceeded' as const,
      message: 'over',
      limit: 50,
      currently_used: 50,
    };
    expect(strictValidate(siteHealthErrorSchema, err, 'err').limit).toBe(50);
  });

  it('accepts a stale-selection error carrying versions', () => {
    const err = {
      code: 'stale_selection_version' as const,
      message: 'stale',
      expected_selection_version: 3,
      current_selection_version: 5,
    };
    expect(strictValidate(siteHealthErrorSchema, err, 'err').current_selection_version).toBe(5);
  });

  it('rejects an unknown error code', () => {
    expect(() =>
      strictValidate(siteHealthErrorSchema, { code: 'kaboom', message: 'x' }, 'err'),
    ).toThrow();
  });
});

describe('query key isolation (project / crawl / filter)', () => {
  it('isolates entitlements from everything else', () => {
    expect(queryKeys.siteHealth.entitlements(null)).toEqual([
      'site-health',
      'entitlements',
      'default',
    ]);
  });

  it('isolates entitlements by workspace id', () => {
    expect(queryKeys.siteHealth.entitlements('ws-1')).not.toEqual(
      queryKeys.siteHealth.entitlements('ws-2'),
    );
  });

  it('isolates inventory by crawl', () => {
    expect(queryKeys.siteHealth.inventory('c1')).not.toEqual(queryKeys.siteHealth.inventory('c2'));
  });

  it('isolates inventory by filter', () => {
    const a = queryKeys.siteHealth.inventory('c1', { query: 'foo' });
    const b = queryKeys.siteHealth.inventory('c1', { query: 'bar' });
    expect(a).not.toEqual(b);
  });

  it('isolates dashboard by project and crawl', () => {
    expect(queryKeys.siteHealth.dashboard('p1')).toEqual([
      'site-health',
      'dashboard',
      'p1',
      'latest',
    ]);
    expect(queryKeys.siteHealth.dashboard('p1', 'c1')).not.toEqual(
      queryKeys.siteHealth.dashboard('p1'),
    );
  });

  it('isolates issues by crawl and filter', () => {
    const a = queryKeys.siteHealth.issues('c1', { severity: 'high' });
    const b = queryKeys.siteHealth.issues('c1', { severity: 'low' });
    const c = queryKeys.siteHealth.issues('c2', { severity: 'high' });
    expect(a).not.toEqual(b);
    expect(a).not.toEqual(c);
  });

  it('keeps monitored keyed per project', () => {
    expect(queryKeys.siteHealth.monitored('p1')).not.toEqual(queryKeys.siteHealth.monitored('p2'));
  });
});

// Sanity: cursorPageSchema is generic and composes with any item schema.
describe('cursorPageSchema generics', () => {
  it('composes with a trivial item schema', () => {
    const page = cursorPageSchema(z.strictObject({ x: z.number() }));
    expect(strictValidate(page, { items: [{ x: 1 }], next_cursor: null }, 'p').items[0].x).toBe(1);
  });
});
