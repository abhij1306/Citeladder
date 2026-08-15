import { expect, test } from '@playwright/test';

import { hideDevChrome, stubAuthedShell } from '../helpers/app-fixture';

test('Demand Intelligence empty workspace', async ({ page }) => {
  await stubAuthedShell(page);

  await page.goto('/demand');
  await hideDevChrome(page);
  await expect(page.getByRole('heading', { level: 1, name: 'Demand' })).toBeVisible();
  await expect(page.getByText('No Search Demand snapshot exists yet.')).toBeVisible();
  await expect(page).toHaveScreenshot('demand-empty-workspace.png', { fullPage: true });
});

test('Demand Intelligence signals and honest detector states', async ({ page }) => {
  const snapshotId = '22222222-2222-4222-8222-222222222222';
  const signal = (id: string, signalType: string, query: string, position: number) => ({
    id,
    snapshot_id: snapshotId,
    signal_type: signalType,
    state: 'active',
    topic_cluster: query,
    page_url: 'https://acme.example/guide',
    evidence: { target_kind: 'query', target: query },
    metrics: { impressions: 120, clicks: 8, ctr: 0.0667, position },
    coverage: { query_evidence: 'observed' },
    limitations: ['GSC detail rows may omit privacy-filtered queries.'],
    priority_score: 60,
    priority_inputs: {},
    created_at: '2026-08-15T00:00:00Z',
  });
  await stubAuthedShell(page, [
    [
      '**/api/v1/projects/*/demand/latest',
      {
        id: snapshotId,
        project_id: '11111111-1111-4111-8111-111111111111',
        window_start: '2026-07-01',
        window_end: '2026-07-26',
        source_hash: 'a'.repeat(64),
        prior_snapshot_id: null,
        source_artifact_ids: ['artifact'],
        source_metric_row_ids: ['row'],
        coverage: { search: 'observed', query_evidence: 'available' },
        summary: {
          signal_count: 2,
          detectors: {
            striking_distance: { state: 'available' },
            property_relative_ctr_gap: { state: 'unavailable' },
            query_trends: { state: 'insufficient_history' },
          },
        },
        comparison: null,
        formula_version: 'demand-priority-1',
        analyzer_version: 'demand-analyzer-4',
        created_at: '2026-08-15T00:00:00Z',
        signals: [
          signal('33333333-3333-4333-8333-333333333333', 'striking_distance', 'aeo guide', 7.2),
          signal(
            '44444444-4444-4444-8444-444444444444',
            'branded_query_performance',
            'acme guide',
            2.1,
          ),
        ],
      },
    ],
  ]);

  await page.goto('/demand');
  await hideDevChrome(page);
  await expect(page.getByText('Striking distance')).toBeVisible();
  await expect(page.getByText('Branded cohort')).toBeVisible();
  await expect(page.getByText('CTR gap: unavailable.')).toBeVisible();
  await expect(page.getByText('Query trends: insufficient history.')).toBeVisible();
  await expect(page).toHaveScreenshot('demand-signals-and-states.png', { fullPage: true });
});
