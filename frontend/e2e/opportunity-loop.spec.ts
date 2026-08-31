import { expect, test } from '@playwright/test';

const WORKSPACE = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const PROJECT = '11111111-1111-4111-8111-111111111111';
const OPPORTUNITY = '22222222-2222-4222-8222-222222222222';
const SNAPSHOT = '33333333-3333-4333-8333-333333333333';
const GENERATION = '44444444-4444-4444-8444-444444444444';
const IMPLEMENTATION = '55555555-5555-4555-8555-555555555555';

const project = {
  id: PROJECT,
  workspace_id: WORKSPACE,
  name: 'Acme',
  brand_name: 'Acme',
  website_url: 'https://acme.example',
  industry: 'Software',
  subindustry: 'Analytics',
  primary_market: 'US',
  country_code: 'US',
  language_code: 'en',
  benchmark_mode: 'consumer_like',
  default_repetitions: 3,
  brand: { aliases: [] },
  owned_domains: [],
  unintended_domains: [],
  competitors: [],
  prompt_sets: [],
  created_at: '2026-08-28T00:00:00Z',
  updated_at: '2026-08-28T00:00:00Z',
};

const mix = {
  state: 'available',
  projection_version: 'opportunity-source-mix-1',
  taxonomy_version: 'source-taxonomy-2',
  counts: { earned: 2, owned: 1, competitive_evidence: 1 },
  percentages: { earned: 50, owned: 25, competitive_evidence: 25 },
  observation_count: 4,
  answers_with_sources: 3,
  eligible_analyzed_answers: 4,
  coverage_rate: 0.75,
  limitations: [],
};

const row = {
  id: OPPORTUNITY,
  project_id: PROJECT,
  rule_id: 'earned_source_recurs_beside_gap',
  opportunity_type: 'visibility',
  severity: 'high',
  priority_score: 140,
  title: 'Prepare an earned inclusion for example.org',
  target_key: 'earned-source:editorial:example.org',
  target_prompt_id: null,
  target_url: null,
  target_theme: 'analytics',
  target_label: 'example.org',
  status: 'open',
  system_rank: 1,
  display_rank: 1,
  order_source: 'system',
  priority_factors: { usage_factor: 2, buyer_stage: 'decision' },
  evidence_summary: { count: 2, kinds: ['response_analysis'] },
  created_at: '2026-08-28T00:00:00Z',
  updated_at: '2026-08-28T00:00:00Z',
};

const handoff = {
  opportunity_id: OPPORTUNITY,
  pathway: 'earned',
  source_class: 'editorial',
  canonical_domain: 'example.org',
  suggested_role: 'Earned Media',
  suggested_skill_id: 'article',
  task_seed: 'Prepare an evidence-backed editorial inclusion brief for example.org.',
  target_url: null,
  target_theme: 'analytics',
  representative_citations: [{ url: 'https://example.org/tools', title: 'Analytics tools' }],
  affected_prompt_indices: [0, 1],
  affected_themes: ['analytics'],
  observed_competitors: ['Rival'],
  coverage: { eligible_answers: 4, observed_answers: 2 },
  limitations: ['Human review and outreach are required.'],
  truncated: false,
  source_analysis_ids: [SNAPSHOT],
  snapshot_versions: { source_taxonomy: 'source-taxonomy-2' },
};

function detail(linked: boolean) {
  return {
    ...row,
    remediation: 'Prepare a transparent expert-contribution brief.',
    evidence: { audit_id: SNAPSHOT, source_pattern: { source_class: 'editorial' } },
    source_analysis_ids: [SNAPSHOT],
    source_issue_ids: [],
    source_metric_ids: [SNAPSHOT],
    source_traffic_ids: [],
    analyzer_version: 'opp-analyzer-7',
    rule_version: 'opp-rules-8',
    formula_version: 'opp-formula-3',
    content_handoff: handoff,
    linked_generations: linked
      ? [
          {
            id: GENERATION,
            status: 'succeeded',
            skill_id: 'article',
            created_at: '2026-08-28T00:01:00Z',
          },
        ]
      : [],
    superseded_by_id: null,
    superseded_at: null,
  };
}

const generation = {
  id: GENERATION,
  project_id: PROJECT,
  status: 'succeeded',
  output_type: 'website_page',
  skill_id: 'article',
  opportunity_id: OPPORTUNITY,
  skill_version: 'content-v1',
  feedback: null,
  feedback_reason: '',
  feedback_at: null,
  grounding_status: 'included',
  requested_model: 'approved-frontier-model',
  returned_model: 'approved-frontier-model',
  provider: 'approved-provider',
  created_at: '2026-08-28T00:01:00Z',
  updated_at: '2026-08-28T00:02:00Z',
  completed_at: '2026-08-28T00:02:00Z',
  error_code: '',
  prompt_preview: handoff.task_seed,
  prompt: handoff.task_seed,
  grounding_summary: {
    version: 'content-context-v1',
    crawl_page_count: 2,
    crawl_urls: ['https://acme.example/', 'https://acme.example/analytics'],
    crawl_completed_at: '2026-08-28T00:00:00Z',
    brand_fields: ['description'],
    search_connected: true,
    omissions: [],
  },
  finish_reason: 'stop',
  output_truncated: false,
  output_text: '# Editorial inclusion brief\n\nA transparent evidence pack.',
  usage: { total_tokens: 80 },
  latency_ms: 200,
  error_detail: '',
  generator_version: 'content-v1',
};

const verificationResult = {
  state: 'available',
  legs: {
    visibility: { state: 'available' },
    ai_referral_traffic: { state: 'observed_zero' },
    branded_search_demand: { state: 'unavailable' },
  },
  gap_changes: {
    state: 'available',
    no_longer_observed: ['gap:old'],
    persistent: ['gap:same'],
    new: ['gap:new'],
  },
  overlapping_action_ids: [],
  causality_notice: 'Later observations do not prove causality.',
};

test('earned opportunity handoff links generation and comparable verification', async ({
  page,
}) => {
  let generated = false;
  let declarationBody: Record<string, unknown> | null = null;

  await page.route('**/api/v1/**', (route) =>
    route.fulfill({ status: 404, json: { detail: 'fixture endpoint not stubbed' } }),
  );
  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      json: {
        user: {
          id: '66666666-6666-4666-8666-666666666666',
          email: 'loop@example.com',
          role: 'owner',
          is_active: true,
          created_at: '2026-08-28T00:00:00Z',
          updated_at: '2026-08-28T00:00:00Z',
        },
      },
    }),
  );
  await page.route('**/api/v1/projects', (route) => route.fulfill({ json: [project] }));
  await page.route(`**/api/v1/projects/${PROJECT}/logos/refresh`, (route) =>
    route.fulfill({ json: {} }),
  );
  await page.route(`**/api/v1/projects/${PROJECT}/opportunities/summary`, (route) =>
    route.fulfill({
      json: {
        activation_state: 'ready',
        computed: true,
        run_id: SNAPSHOT,
        audit_id: SNAPSHOT,
        site_crawl_id: null,
        demand_snapshot_id: null,
        demand_source_revision: null,
        coverage: {},
        limitations: [],
        source_mix: mix,
        action_path_mix: mix,
        domain_rollups: [],
        counts_by_type: { visibility: 1 },
        counts_by_severity: { high: 1 },
        counts_by_status: { open: 1 },
        total_count: 1,
        median_priority: 140,
        analyzer_version: 'opp-analyzer-7',
        rule_version: 'opp-rules-8',
        formula_version: 'opp-formula-3',
        computed_at: '2026-08-28T00:00:00Z',
        evidence_updated_at: '2026-08-28T00:00:00Z',
        stale: false,
      },
    }),
  );
  await page.route(`**/api/v1/projects/${PROJECT}/opportunities?*`, (route) =>
    route.fulfill({ json: { items: [row], next_cursor: null } }),
  );
  await page.route(`**/api/v1/opportunities/${OPPORTUNITY}`, (route) =>
    route.fulfill({ json: detail(generated) }),
  );
  await page.route(`**/api/v1/projects/${PROJECT}/opportunities/implementation-events?*`, (route) =>
    route.fulfill({ json: { items: [], next_cursor: null } }),
  );
  await page.route(
    `**/api/v1/projects/${PROJECT}/opportunities/implementation-events`,
    async (route) => {
      if (route.request().method() !== 'POST') {
        return route.fulfill({ json: { items: [], next_cursor: null } });
      }
      declarationBody = (await route.request().postDataJSON()) as Record<string, unknown>;
      return route.fulfill({
        status: 201,
        json: {
          id: IMPLEMENTATION,
          project_id: PROJECT,
          opportunity_id: OPPORTUNITY,
          opportunity_snapshot_id: SNAPSHOT,
          target_site_url_ids: [],
          generation_id: GENERATION,
          declared_implemented_at: '2026-08-28T00:03:00Z',
          expected_checks: [
            {
              kind: 'visibility_metric',
              metric: 'visibility_score',
              direction: 'increase',
              expected_value: 1,
              tolerance: 0,
            },
          ],
          state: 'verified',
          limitations: [],
          verification_events: [
            {
              id: '77777777-7777-4777-8777-777777777777',
              observation_kind: 'verified',
              observed_at: '2026-08-28T00:04:00Z',
              crawl_id: null,
              audit_id: SNAPSHOT,
              source_analysis_ids: [SNAPSHOT],
              source_rule_evaluation_ids: [],
              source_metric_ids: [SNAPSHOT],
              result: verificationResult,
              verifier_version: 'implementation-verifier-2',
              limitations: [],
              created_at: '2026-08-28T00:04:00Z',
            },
          ],
          created_at: '2026-08-28T00:03:00Z',
        },
      });
    },
  );
  await page.route('**/api/v1/content/skills', (route) =>
    route.fulfill({
      json: {
        version: 'content-skills-v2',
        default_skill_id: 'content_page',
        skills: [
          {
            id: 'article',
            label: 'Article',
            channel: 'web',
            description: 'An evidence-led article.',
            structure: ['A clear H1.'],
            tone: 'Expert.',
            length_hint: '900–1400 words.',
          },
        ],
      },
    }),
  );
  await page.route('**/api/v1/content/context-preview?*', (route) =>
    route.fulfill({
      json: {
        crawl_available: true,
        crawl_page_count: 2,
        crawl_completed_at: '2026-08-28T00:00:00Z',
        brand_fields: ['description'],
        search_connected: true,
      },
    }),
  );
  await page.route('**/api/v1/content/generations?*', (route) =>
    route.fulfill({ json: generated ? [generation] : [] }),
  );
  await page.route('**/api/v1/content/generations', async (route) => {
    generated = true;
    return route.fulfill({ status: 201, json: generation });
  });
  await page.route(`**/api/v1/content/generations/${GENERATION}`, (route) =>
    route.fulfill({ json: generation }),
  );

  await page.goto('/opportunities');
  await page.getByRole('button', { name: 'Review recommendation' }).click();
  await page.getByRole('link', { name: 'Prepare earned content' }).click();
  await expect(page).toHaveURL(/\/content/);
  expect(new URL(page.url()).searchParams.get('opportunity_id')).toBe(OPPORTUNITY);
  await expect(page.getByText('Path: Earned')).toBeVisible();
  // Instant navigation may retain the previous route's hidden DOM in its reusable shell.
  await expect(page.getByText(detail(false).remediation).filter({ visible: true })).toHaveCount(0);
  const prompt = page.getByRole('textbox', { name: /describe the website content/i });
  await expect(prompt).toHaveValue(handoff.task_seed);
  await page.getByRole('button', { name: 'Generate' }).click();
  await expect(page.getByRole('heading', { name: 'Editorial inclusion brief' })).toBeVisible();
  await page.getByRole('link', { name: 'Return to opportunity' }).click();
  // Returning through the cached shell restores the open opportunity drawer.
  await expect(page.getByRole('dialog')).toBeVisible();
  await page.getByRole('button', { name: 'I implemented this' }).click();

  await expect(page.getByText('visibility: available')).toBeVisible();
  await expect(page.getByText('ai referral traffic: observed zero')).toBeVisible();
  await expect(page.getByText('Gaps: 1 no longer observed · 1 persistent · 1 new')).toBeVisible();
  expect(declarationBody).toMatchObject({
    opportunity_id: OPPORTUNITY,
    generation_id: GENERATION,
    expected_checks: [],
  });
});
