import { expect, test, type Page } from '@playwright/test';

import { FIXTURE_PROJECT, stubAuthedShell } from './helpers/app-fixture';

const WORKSPACE = 'aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa';
const CRAWL = '22222222-2222-4222-8222-222222222222';
const CRAWL_A = '12121212-1212-4212-8212-121212121212';
const PROFILE = '33333333-3333-4333-8333-333333333333';
const SOURCE = '44444444-4444-4444-8444-444444444444';
const TARGET = '55555555-5555-4555-8555-555555555555';
const SNAPSHOT = '66666666-6666-4666-8666-666666666666';

const crawl = {
  id: CRAWL,
  workspace_id: WORKSPACE,
  project_id: FIXTURE_PROJECT.id,
  profile_id: PROFILE,
  status: 'completed',
  discovery_status: 'completed',
  analysis_status: 'completed',
  root_url: 'https://acme.example/',
  sample_mode: false,
  seed: '1',
  inventory_complete: true,
  visible_url_count: 2,
  analyzed_count: 2,
  failed_count: 0,
  discovery_requested_count: 2,
  analysis_requested_count: 2,
  counters: {
    discovered: 2,
    selected: 2,
    queued: 0,
    running: 0,
    analyzed: 2,
    errors: 0,
    blocked: 0,
    failure_breakdown: { robots_denied: 0, http_4xx: 0, http_5xx: 0, timeout: 0 },
    activity: { state: 'terminal', reason: 'terminal', queue_depth: 0, next_available_at: null },
    by_page_kind: { article: 2 },
  },
  discovered_count: 2,
  total_url_count: 2,
  has_more_site_urls: false,
  score_summary: {
    technical_integrity_score: 85,
    technical_integrity_coverage: 1,
    technical_integrity_state: 'measured',
    aeo_readiness_score: 79,
    aeo_measurement_coverage: 0.8,
    aeo_measurement_state: 'measured',
    search_eligibility: 'eligible',
    selected_count: 2,
    analyzed_count: 2,
    issue_count: 2,
    scoring_version: 'score-v1',
    by_page_kind: {},
  },
  failure_summary: null,
  site_facts: {},
  extractor_version: 'extract-v1',
  analyzer_version: 'page-v1',
  rule_version: 'rules-v1',
  partial_reason: '' as const,
  scoring_version: 'score-v1',
  error_message: '',
  created_at: '2026-08-15T00:00:00Z',
  updated_at: '2026-08-15T00:01:00Z',
  started_at: '2026-08-15T00:00:00Z',
  completed_at: '2026-08-15T00:01:00Z',
};

const dimensions = [
  ['answerability', 'Answerability'],
  ['structure', 'Structure'],
  ['evidence', 'Evidence'],
  ['machine-readability', 'Machine readability'],
  ['authority', 'Authority'],
  ['freshness', 'Freshness'],
  ['crawlability', 'Crawlability'],
] as const;
const ruleCounts = [4, 5, 1, 3, 2, 1, 4] as const;

async function stubWebsite(page: Page) {
  await stubAuthedShell(page, [
    [
      '**/api/v1/entitlements',
      {
        workspace_id: WORKSPACE,
        access_mode: 'full',
        sample_url_limit: 10,
        monitored_url_limit: 50,
        count_disclosure: true,
        resolver_status: 'resolved',
        registry_revision: 'registry-v1',
        entitlement_lifecycle_version: 1,
        valid_until: null,
        contributing_grant_ids: [],
        advanced_controls_enabled: false,
      },
    ],
    [
      `**/api/v1/projects/${FIXTURE_PROJECT.id}/site-health`,
      {
        project_id: FIXTURE_PROJECT.id,
        crawl,
        score_summary: crawl.score_summary,
        phase: 'dashboard',
        snapshot_id: SNAPSHOT,
        quota: { used: 2, limit: 50 },
        root_errors: [],
        phase_runs: { discovery: null, analysis: null },
      },
    ],
    [
      new RegExp(`/api/v1/projects/${FIXTURE_PROJECT.id}/site-health/aeo-readiness(?:\\?.*)?$`),
      {
        state: 'measured',
        crawl_id: CRAWL,
        score: 79,
        coverage: 1,
        profile_version: 'site-health-profile-1',
        schema_contract_version: 'site-health-schema-contract-1',
        scoring_version: 'score-v1',
        presentation_version: 'site-health-presentation-1',
        analyzer_version: 'page-v1',
        source_analysis_ids: [SOURCE, TARGET],
        analysis_count: 2,
        affected_page_count: 1,
        limitations: [],
        dimensions: dimensions.map(([key, label], index) => {
          const ruleIds = Array.from({ length: ruleCounts[index] }, (_, ruleIndex) =>
            index === 0 && ruleIndex === 0 ? 'aeo.answer_first' : `aeo.rule_${index}_${ruleIndex}`,
          );
          const ruleId = ruleIds[0];
          const missingCount = index ? 0 : 1;
          const notApplicableCount = index === 1 ? 1 : 0;
          return {
            key,
            label,
            description: `What ${label.toLowerCase()} means, in one plain sentence.`,
            dimension_applicability: 'applicable',
            dimension_measurement_state: 'measured',
            score: index ? 100 : 50,
            reason: '',
            checkpoint_ids: ruleIds,
            determinate_checkpoint_ids: ruleIds,
            checkpoint_families: [key],
            earned_points: index ? ruleCounts[index] : ruleCounts[index] - 1,
            determinate_points: ruleCounts[index],
            expected_points: ruleCounts[index],
            satisfied_count: ruleCounts[index] * 2 - missingCount - notApplicableCount,
            partial_count: 0,
            missing_count: missingCount,
            unknown_count: 0,
            unavailable_count: 0,
            conflicting_count: 0,
            not_applicable_count: notApplicableCount,
            error_count: 0,
            coverage: 1,
            checked_page_count: 2,
            failing_page_count: missingCount,
            checks: [
              {
                rule_id: ruleId,
                title: index ? `${label} check` : 'Answer is not stated first',
                remediation: 'Move the direct answer into the opening paragraph.',
                satisfied_count: 2 - missingCount - notApplicableCount,
                partial_count: 0,
                missing_count: missingCount,
                unknown_count: 0,
                unavailable_count: 0,
                conflicting_count: 0,
                not_applicable_count: notApplicableCount,
                error_count: 0,
                failing_page_count: missingCount,
                checkpoint_family: key,
                readiness_weight: 1,
                content_addressable: true,
              },
            ],
            evidence_pages: index
              ? []
              : [
                  {
                    site_url_id: TARGET,
                    source_analysis_id: TARGET,
                    normalized_url: 'https://acme.example/case-study',
                    failed_checks: [
                      {
                        rule_id: 'aeo.answer_first',
                        title: 'Answer is not stated first',
                        observed_evidence: { observed: 'missing' },
                        expected_capability: 'State the answer first.',
                        remediation: 'Move the direct answer into the opening paragraph.',
                        content_addressable: true,
                      },
                    ],
                  },
                ],
            evidence_truncated: false,
          };
        }),
      },
    ],
    [
      new RegExp(`/api/v1/projects/${FIXTURE_PROJECT.id}/site-health/architecture(?:\\?.*)?$`),
      {
        state: 'available',
        crawl_id: CRAWL,
        coverage_state: 'complete',
        page_count: 2,
        page_kinds: [
          {
            page_kind: 'article',
            page_count: 2,
            median_depth: 1,
            indexable_count: 2,
            duplicate_metadata_count: 0,
            orphan_count: 0,
          },
        ],
        nodes: [
          {
            site_url_id: TARGET,
            url: 'https://acme.example/case-study',
            title: 'Case study',
            page_kind: 'article',
            parent_site_url_id: null,
            parent_source: 'unknown',
            depth_from_home: 1,
          },
          {
            site_url_id: SOURCE,
            url: 'https://acme.example/guide',
            title: 'Guide',
            page_kind: 'article',
            parent_site_url_id: null,
            parent_source: 'unknown',
            depth_from_home: 1,
          },
        ],
        internal_linking: {
          internal_link_count: 4,
          pages_with_incoming_count: 2,
          pages_with_incoming_percentage: 1,
          orphan_page_count: 0,
        },
        structure_depth: {
          measured_page_count: 2,
          unmeasured_page_count: 0,
          buckets: [
            { key: 'depth_0', page_count: 0, percentage: 0 },
            { key: 'depth_1', page_count: 2, percentage: 1 },
            { key: 'depth_2', page_count: 0, percentage: 0 },
            { key: 'depth_3_plus', page_count: 0, percentage: 0 },
          ],
        },
        architecture_formula_version: 'sh-architecture-1',
        limitations: [],
      },
    ],
    [
      `**/api/v1/projects/${FIXTURE_PROJECT.id}/site-health/changes/summary`,
      {
        state: 'available',
        reason_code: null,
        snapshot_id: SNAPSHOT,
        crawl_a_id: CRAWL_A,
        crawl_b_id: CRAWL,
        complete_pair: true,
        analyzer_version: 'site-change-v1',
        page_analyzer_version: 'page-v1',
        extractor_version: 'extract-v1',
        source_analysis_ids: [SOURCE, TARGET],
        coverage: { shared_pages: 2 },
        summary: { total: 1, counts_by_class: { 'critical-regression': 1 } },
        limitations: [],
        created_at: '2026-08-15T00:01:00Z',
      },
    ],
    [
      new RegExp(
        `/api/v1/projects/${FIXTURE_PROJECT.id}/site-health/changes\\?` +
          `crawl_a_id=${CRAWL_A}&crawl_b_id=${CRAWL}&limit=50$`,
      ),
      {
        state: 'available',
        reason_code: null,
        snapshot_id: SNAPSHOT,
        crawl_a_id: CRAWL_A,
        crawl_b_id: CRAWL,
        complete_pair: true,
        analyzer_version: 'site-change-v1',
        page_analyzer_version: 'page-v1',
        extractor_version: 'extract-v1',
        source_analysis_ids: [SOURCE, TARGET],
        coverage: { shared_pages: 2 },
        summary: { total: 1, counts_by_class: { 'critical-regression': 1 } },
        limitations: [],
        created_at: '2026-08-15T00:01:00Z',
        next_cursor: null,
        items: [
          {
            id: '10101010-1010-4010-8010-101010101010',
            site_url_id: TARGET,
            normalized_url: 'https://acme.example/case-study',
            field: 'http_status',
            change_class: 'critical-regression',
            before_value: 200,
            after_value: 503,
            source_analysis_a_id: SOURCE,
            source_analysis_b_id: TARGET,
            source_artifact_a_id: SOURCE,
            source_artifact_b_id: TARGET,
            source_evaluation_a_id: null,
            source_evaluation_b_id: null,
            expected: false,
            implementation_event_id: null,
            created_at: '2026-08-15T00:01:00Z',
          },
        ],
      },
    ],
  ]);
}

test('AEO Readiness browser proof: seven named dimensions and page-grouped evidence', async ({
  page,
}) => {
  await stubWebsite(page);
  await page.goto('/site');
  await page.getByRole('tab', { name: 'AEO Readiness' }).click();

  const panel = page.getByTestId('aeo-readiness');
  await expect(panel).toBeVisible();
  for (const [, label] of dimensions) await expect(panel).toContainText(label);
  for (const heading of ['Determinate', 'Expected', 'N/A', 'Errors', 'Coverage', 'State']) {
    await expect(panel.getByRole('columnheader', { name: heading })).toBeVisible();
  }
  await expect(panel).not.toContainText('Answer is not stated first');
  await expect(panel).not.toContainText('aeo.answer_first');

  await page.getByRole('button', { name: 'View details for Answerability' }).click();
  const evidence = page.getByRole('dialog');
  await expect(evidence).toContainText('1 page failed at least one check');
  await expect(evidence).toContainText('acme.example/case-study');
  // Checks are named the way the catalog names them, never by rule id.
  await expect(evidence).toContainText('Answer is not stated first');
  await expect(evidence).not.toContainText('aeo.answer_first');
});

test('Architecture browser proof: page kinds expand to their URLs', async ({ page }) => {
  await stubWebsite(page);
  await page.goto('/site');
  await page.getByRole('tab', { name: 'Architecture' }).click();

  const panel = page.getByTestId('site-architecture');
  await expect(panel).toBeVisible();
  await expect(panel).toContainText('Article');
  const pageKindLedger = panel.getByRole('table');
  // The hierarchy is always visible; the separate page-kind URL list stays
  // behind its disclosure until the row is opened.
  await expect(pageKindLedger).not.toContainText('https://acme.example/case-study');
  await page.getByRole('button', { name: 'Article' }).click();
  await expect(pageKindLedger).toContainText('https://acme.example/case-study');
  await expect(panel.getByRole('heading', { name: 'Observed hierarchy' })).toBeVisible();
});

test('Website Changes browser proof: summary and exact before-after evidence', async ({ page }) => {
  await stubWebsite(page);
  await page.goto('/site');
  await page.getByRole('tab', { name: 'Changes' }).click();

  await expect(page.getByTestId('website-changes')).toBeVisible();
  await expect(page.getByRole('table')).toContainText('Critical regression');
  await page.getByText('View evidence').click();
  await expect(page.getByText(/Before:/).locator('..')).toContainText('200');
  await expect(page.getByText(/After:/).locator('..')).toContainText('503');
});
