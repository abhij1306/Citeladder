import { expect, test } from '@playwright/test';

import { stubAuthedShell } from './helpers/app-fixture';

const DISCOVERY_ID = '33333333-3333-4333-8333-333333333333';
const CONVERSATION_ID = '44444444-4444-4444-8444-444444444444';
const PROJECT_ID = '11111111-1111-4111-8111-111111111111';
const CRAWL_ID = '66666666-6666-4666-8666-666666666666';

const catalog = {
  business_types: ['b2b', 'b2c', 'both'],
  price_tiers: ['unknown'],
  required_fields: [],
  optional_fields: [],
  capture_methods: [],
  maximum_competitors: 5,
  industries: ['General', 'Education', 'Professional Services'],
  subindustries: { General: [], Education: [], 'Professional Services': [] },
  prompt_cohorts: ['core', 'brand_diagnostic'],
};

const readyDiscovery = {
  id: DISCOVERY_ID,
  workspace_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
  project_id: null,
  status: 'ready',
  progress: {
    phase: 'preparing_review',
    completed_steps: 3,
    total_steps: 4,
    pages_read: 1,
    competitors_found: 2,
    prompts_prepared: 0,
  },
  input_data: {
    brand_name: 'The Asian School',
    website_url: 'https://www.theasianschool.net/',
    industry: 'Education',
    subindustry: '',
    primary_market: 'IN',
    language_code: 'en',
  },
  profile: {
    description: 'A co-educational day cum boarding school in Dehradun, India.',
    positioning: 'A day and boarding school for families in Dehradun.',
    products_services: ['Education'],
    target_audience: 'Families',
    industry: 'Education',
    business_type: 'b2c',
    price_tier: 'unknown',
    field_confidence: {},
  },
  domains: ['theasianschool.net'],
  competitors: [
    {
      name: 'The Doon School',
      aliases: [],
      domains: ['doonschool.com'],
      qualification: null,
      reasoning: '',
      evidence_urls: [],
      confidence: 0.8,
    },
    {
      name: "Welham Girls' School",
      aliases: [],
      domains: ['welhamgirls.com'],
      qualification: null,
      reasoning: '',
      evidence_urls: [],
      confidence: 0.8,
    },
  ],
  topics: [
    {
      topic_id: '77777777-7777-4777-8777-777777777771',
      name: 'Day Schools',
      description: '',
      source_refs: ['page-1'],
    },
    {
      topic_id: '77777777-7777-4777-8777-777777777772',
      name: 'Boarding Schools',
      description: '',
      source_refs: ['page-1'],
    },
    {
      topic_id: '77777777-7777-4777-8777-777777777773',
      name: 'School Admissions',
      description: '',
      source_refs: ['page-1'],
    },
  ],
  prompt_suggestions: [],
  evidence: [],
  warnings: [],
  gaps: [],
  error_code: '',
  created_at: '2026-08-09T00:00:00Z',
  updated_at: '2026-08-09T00:00:01Z',
};

test('onboarding renders inverse type, sequential progress, and a prompt-free review', async ({
  page,
}) => {
  await stubAuthedShell(page, [
    ['**/api/v1/brand-discovery-catalog', catalog],
    ['**/api/v1/brand-discoveries', readyDiscovery],
    [`**/api/v1/brand-discoveries/${DISCOVERY_ID}`, readyDiscovery],
  ]);

  await page.goto('/onboarding');
  const setupHeading = page.getByRole('heading', { name: 'Set up your project' });
  await expect(setupHeading).toBeVisible();
  await expect(setupHeading).toHaveCSS('color', 'rgb(255, 255, 255)');
  const setupBox = await setupHeading.boundingBox();
  expect(setupBox).not.toBeNull();
  const initialHeading = page.getByRole('heading', { name: "Let's get started" });
  const initialHeadingBox = await initialHeading.boundingBox();
  expect(initialHeadingBox).not.toBeNull();
  // The short setup stage begins on the same visual line as the desktop rail
  // title, instead of sitting vertically centred beneath it.
  expect(Math.abs(initialHeadingBox!.y - setupBox!.y)).toBeLessThanOrEqual(12);
  const stageHeadingFontSize = await initialHeading.evaluate(
    (element) => getComputedStyle(element).fontSize,
  );
  const brandStage = await page.locator('main#main').boundingBox();
  expect(brandStage).not.toBeNull();

  await page.getByLabel(/^Brand name/).fill('The Asian School');
  await page.getByLabel(/^Website/).fill('theasianschool.net');
  await page.getByRole('button', { name: 'Continue' }).click();
  const discoveryHeading = page.getByRole('heading', { name: 'Finding what to track' });
  const discoveryHeadingBox = await discoveryHeading.boundingBox();
  expect(discoveryHeadingBox).not.toBeNull();
  expect(Math.abs(discoveryHeadingBox!.y - setupBox!.y)).toBeLessThanOrEqual(12);
  const discoveryStage = await page.locator('main#main').boundingBox();
  expect(discoveryStage).not.toBeNull();

  const progress = page.getByRole('progressbar', { name: /steps complete/ });
  await expect(progress).not.toHaveAttribute('aria-valuenow', '4');
  await expect(progress).toHaveAttribute('aria-valuenow', '4', { timeout: 4_000 });

  await page.getByRole('button', { name: 'Review' }).click();
  await expect(page.getByRole('heading', { name: 'Does this look right?' })).toHaveCSS(
    'font-size',
    stageHeadingFontSize,
  );
  const reviewStage = await page.locator('main#main').boundingBox();
  expect(reviewStage).not.toBeNull();
  expect(reviewStage?.width).toBeCloseTo(brandStage!.width, 0);
  expect(reviewStage?.height).toBeCloseTo(brandStage!.height, 0);
  expect(reviewStage?.width).toBeCloseTo(discoveryStage!.width, 0);
  expect(reviewStage?.height).toBeCloseTo(discoveryStage!.height, 0);
  await expect(page.getByRole('heading', { name: 'Confirm your ICP' })).toBeVisible();
  await expect(page.getByText('theasianschool.net')).toBeVisible();
  await expect(page.getByText('The Doon School')).toBeVisible();
  await expect(page.getByText(/Starting Prompts/i)).toHaveCount(0);
});

test('Overview remains useful before the first visibility audit', async ({ page }) => {
  const unavailable = {
    state: 'not_run',
    observed_at: null,
    freshness: 'unknown',
    coverage: [],
    limitations: [],
  };
  await stubAuthedShell(page, [
    [
      `**/api/v1/projects/${PROJECT_ID}/command-center`,
      {
        project: {
          id: PROJECT_ID,
          name: 'Acme',
          brand_name: 'Acme',
          website_url: 'https://acme.example',
        },
        facts: {
          industry: 'Software',
          description: 'Evidence-led growth intelligence',
          positioning: 'Make every answer traceable',
          products_services: ['Analytics'],
          target_audience: 'Growth teams',
          competitors: [],
        },
        loop: {
          connected: unavailable,
          analyzed: { ...unavailable, state: 'partial', coverage: ['site_health'] },
          acted: unavailable,
          tracked: {
            ...unavailable,
            limitations: ['No visibility audit has run yet.'],
          },
        },
        next_action: {
          kind: 'connect',
          title: 'Connect GSC or GA4',
          href: '/settings?tab=integrations',
          opportunity_id: null,
        },
        track: {
          citation_share: { value: null, delta: null },
          engine_coverage: 0,
          observed_at: null,
          limitations: ['No visibility audit has run yet.'],
        },
        measurement: null,
        state: {
          visibility: { value: null, delta: null },
          share_of_voice: { value: null, delta: null },
          brand_rank: { value: null, delta: null },
        },
        movements: [],
        actions: [],
        action_order_version: 0,
        resolved_actions: { since_audit_id: null, count: 0, titles: [] },
        report_available: false,
        stale: false,
      },
    ],
  ]);

  await page.goto('/projects');
  await expect(page.getByText('Make every answer traceable')).toBeVisible();
  await expect(page.getByText('Connect GSC or GA4')).toBeVisible();
  await expect(page.getByText('Citation share —')).toBeVisible();
  await expect(page.getByRole('button', { name: /Executive PDF/i })).toHaveCount(0);
  // The Product loop station strip was removed from Overview; loop evidence
  // still arrives on the projection but has no station-tile surface.
  await expect(page.getByRole('heading', { name: 'Product loop' })).toHaveCount(0);
});

test('Growth Agent opens as a bounded task workspace with plain-language data used', async ({
  page,
}) => {
  const run = {
    id: CONVERSATION_ID,
    project_id: '11111111-1111-4111-8111-111111111111',
    task_type: 'build_roadmap',
    objective: 'Build an admissions roadmap',
    task_policy_version: 'growth-agent-v2',
    status: 'completed',
    result: {
      summary: 'Prioritize the admissions journey first.',
      observations: ['Admissions has the highest-ranked saved opportunity.'],
      roadmap_items: [
        {
          rank: 1,
          title: 'Improve admissions',
          remediation: 'Answer the next common question.',
          target_url: null,
          priority_score: 90,
          severity: 'high',
        },
      ],
      sources: [
        {
          key: 'opportunities',
          label: 'Opportunities',
          availability: 'available',
          window: null,
          coverage: { count: 1 },
          reason: null,
        },
      ],
      limitations: [],
      artifact_refs: [{ kind: 'opportunity', id: '55555555-5555-4555-8555-555555555555' }],
    },
    provider_adapter: 'deterministic',
    endpoint_host: '',
    model: '',
    instruction_version: 'v2',
    usage: null,
    latency_ms: 12,
    error_code: '',
    error_detail: '',
    attempt_count: 1,
    completed_at: '2026-08-09T00:00:02Z',
    cancelled_at: null,
    created_at: '2026-08-09T00:00:00Z',
    updated_at: '2026-08-09T00:00:00Z',
    attempts: [
      {
        id: '66666666-6666-4666-8666-666666666666',
        run_attempt: 1,
        ordinal: 1,
        tool_name: 'opportunities.read_ranked',
        tool_version: '2.0.0',
        status: 'completed',
        input: {},
        artifact_refs: [{ kind: 'opportunity', id: '55555555-5555-4555-8555-555555555555' }],
        output_hash: 'output-hash',
        omissions: [],
        error_code: '',
        retryable: false,
        latency_ms: 4,
        created_at: '2026-08-09T00:00:01Z',
      },
    ],
  };
  await stubAuthedShell(page, [
    ['**/api/v1/agent/tasks?*', [run]],
    [`**/api/v1/agent/tasks/${CONVERSATION_ID}?*`, run],
  ]);

  await page.goto('/site');
  await page.getByRole('button', { name: 'Agent', exact: true }).click();
  await expect(page.getByRole('dialog', { name: 'Growth Agent' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Build an admissions roadmap' })).toBeVisible();
  await expect(page.getByText('Prioritize the admissions journey first.')).toBeVisible();
  await expect(page.getByLabel('Objective')).toBeVisible();
  await expect(page.getByRole('button', { name: 'Start task' })).toBeVisible();
  await expect(page.getByRole('combobox', { name: 'Task' })).toHaveValue('explain');
  await expect(page.getByText('Data used')).toBeVisible();
  await expect(page.getByText('opportunities.read_ranked')).toHaveCount(0);
  await expect(page.getByText(/conversation/i)).toHaveCount(0);
});

const siteFacts = {
  robots: {
    fetched: true,
    url: 'https://acme.example/robots.txt',
    status_code: 200,
    ai_crawlers: {
      GPTBot: 'allow',
      ClaudeBot: 'allow',
      PerplexityBot: 'allow',
      'Google-Extended': 'allow',
    },
    sitemaps: ['https://acme.example/sitemap.xml'],
  },
  llms_txt: {
    fetched: false,
    url: 'https://acme.example/llms.txt',
    status_code: 404,
    present: false,
  },
  sitemap: { fetched: true, files: ['https://acme.example/sitemap.xml'] },
};

function siteCrawl(analysisStatus: 'running' | 'stopped') {
  const running = analysisStatus === 'running';
  return {
    id: CRAWL_ID,
    workspace_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
    project_id: PROJECT_ID,
    profile_id: '77777777-7777-4777-8777-777777777777',
    status: running ? 'running' : 'paused',
    discovery_status: 'completed',
    analysis_status: analysisStatus,
    root_url: 'https://acme.example/',
    sample_mode: false,
    seed: '1',
    inventory_complete: true,
    visible_url_count: 2,
    analyzed_count: 1,
    failed_count: 0,
    discovery_requested_count: 2,
    analysis_requested_count: 1,
    counters: {
      discovered: 2,
      selected: 1,
      queued: 0,
      running: 0,
      analyzed: 1,
      errors: 0,
      blocked: 0,
      failure_breakdown: { robots_denied: 0, http_4xx: 0, http_5xx: 0, timeout: 0 },
      activity: {
        state: running ? 'working' : 'terminal',
        reason: running ? 'active_work' : 'terminal',
        queue_depth: running ? 1 : 0,
        next_available_at: null,
      },
      by_page_kind: {},
    },
    discovered_count: 2,
    total_url_count: 2,
    has_more_site_urls: false,
    score_summary: null,
    failure_summary: null,
    site_facts: siteFacts,
    extractor_version: 'e1',
    analyzer_version: 'a1',
    rule_version: 'r1',
    scoring_version: 's1',
    error_message: '',
    created_at: '2026-08-10T00:00:00Z',
    updated_at: running ? '2026-08-10T00:01:00Z' : '2026-08-10T00:02:00Z',
    started_at: '2026-08-10T00:00:00Z',
    completed_at: null,
  };
}

test('Site Health keeps its single crawl action and URLs above diagnostics', async ({ page }) => {
  let analysisStatus: 'running' | 'stopped' = 'running';
  const dashboard = () => ({
    project_id: PROJECT_ID,
    crawl: siteCrawl(analysisStatus),
    score_summary: null,
    phase: 'analyzing',
    snapshot_id: null,
    quota: { used: 1, limit: 50 },
    root_errors: [],
    phase_runs: { discovery: null, analysis: null },
  });
  await stubAuthedShell(page, [
    [
      '**/api/v1/entitlements',
      {
        workspace_id: 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa',
        access_mode: 'full',
        sample_url_limit: 10,
        monitored_url_limit: 50,
        count_disclosure: true,
        resolver_status: 'resolved',
        registry_revision: 'registry-v8',
        entitlement_lifecycle_version: 1,
        valid_until: null,
        contributing_grant_ids: [],
        advanced_controls_enabled: true,
      },
    ],
    [
      `**/api/v1/projects/${PROJECT_ID}/monitored-urls`,
      {
        project_id: PROJECT_ID,
        selection_version: 1,
        monitored_urls: [
          {
            site_url_id: '88888888-8888-4888-8888-888888888888',
            normalized_url: 'https://acme.example/',
            display_url: 'https://acme.example/',
            title: 'Acme',
            active: true,
            selection_source: 'user',
            selected_at: '2026-08-10T00:00:00Z',
            deselected_at: null,
          },
        ],
        quota: { used: 1, limit: 50 },
      },
    ],
    [
      `**/api/v1/site-crawls/${CRAWL_ID}/inventory**`,
      {
        items: [
          {
            site_url_id: '88888888-8888-4888-8888-888888888888',
            normalized_url: 'https://acme.example/',
            display_url: 'https://acme.example/',
            title: 'Acme',
            content_type: 'text/html',
            source: 'root',
            depth: 0,
            monitored: true,
            first_seen_at: null,
            last_seen_at: null,
            issue_count: null,
            technical_score: null,
            aeo_score: null,
            overall_score: null,
            last_audited: null,
            page_kind: 'homepage',
          },
        ],
        next_cursor: null,
      },
    ],
    [
      `**/api/v1/site-crawls/${CRAWL_ID}/pages**`,
      { items: [], next_cursor: null, root_errors: [] },
    ],
  ]);
  await page.route(`**/api/v1/projects/${PROJECT_ID}/site-health**`, (route) =>
    route.fulfill({ json: dashboard() }),
  );
  await page.route(`**/api/v1/site-crawls/${CRAWL_ID}/cancel`, async (route) => {
    await new Promise<void>((resolve) => {
      setTimeout(resolve, 300);
    });
    analysisStatus = 'stopped';
    await route.fulfill({ json: siteCrawl('stopped') });
  });

  await page.goto('/site');
  const stopCrawl = page.getByRole('button', { name: 'Stop crawl' });
  await expect(stopCrawl).toBeVisible();
  await expect(page.getByText('Start discovery')).toHaveCount(0);
  await expect(page.getByText('Start analysis')).toHaveCount(0);
  const urlWorkspace = page.getByRole('button', { name: 'Monitored' });
  await expect(urlWorkspace).toBeVisible();
  await expect(page.getByText('Crawler details')).toBeVisible();
  const inventoryTop = await urlWorkspace.evaluate(
    (element) => element.getBoundingClientRect().top,
  );
  const crawlerTop = await page
    .getByText('AI crawler access')
    .evaluate((element) => element.getBoundingClientRect().top);
  expect(inventoryTop).toBeLessThan(crawlerTop);

  await stopCrawl.click();
  await expect(page.getByRole('button', { name: 'Stopping…' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Run new crawl' })).toBeEnabled();
  await expect(page.getByRole('dialog', { name: 'Choose pages to crawl' })).toHaveCount(0);
});
