import { expect, test } from '@playwright/test';
import path from 'node:path';

import { hideDevChrome, stubAuthedShell } from '../helpers/app-fixture';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';

const actions = [
  ['Add first-party citations to comparison pages', 'critical', 96.2, 'Comparison prompts'],
  ['Strengthen warranty evidence', 'high', 88.4, 'Warranty queries'],
  ['Resolve thin buying-guide pages', 'high', 81.7, '3 monitored URLs'],
  ['Clarify the returns policy for answer engines', 'medium', 73.1, 'Service prompts'],
].map(([title, severity, priority, target], index) => ({
  id: `22222222-2222-4222-8222-22222222222${index}`,
  project_id: PROJECT_ID,
  rule_id: `rule_${index}`,
  opportunity_type: index === 2 ? 'site' : 'visibility',
  severity,
  priority_score: priority,
  title,
  target_key: `target:${index}`,
  target_prompt_id: null,
  target_url: null,
  target_theme: null,
  target_label: target,
  status: 'open',
  system_rank: index + 1,
  display_rank: index + 1,
  order_source: 'system',
  priority_factors: { impact: priority, evidence_count: index + 2 },
  evidence_summary: { count: index + 2, kinds: ['analysis', 'citation'] },
  created_at: '2026-08-04T08:00:00Z',
  updated_at: '2026-08-04T08:00:00Z',
}));

const commandCenter = {
  project: {
    id: PROJECT_ID,
    name: 'Wanderlust Gear — US Backpacks',
    brand_name: 'Wanderlust Gear Co.',
    website_url: 'https://wanderlustgear.com',
  },
  measurement: {
    audit_id: '33333333-3333-4333-8333-333333333333',
    completed_at: '2026-08-04T08:30:00Z',
    measurement_mode: 'pulse',
    benchmark_mode: 'controlled_localized',
    logical_engines: ['chatgpt', 'claude', 'gemini'],
    comparable_audit_id: '44444444-4444-4444-8444-444444444444',
  },
  state: {
    visibility: { value: 72.4, delta: 8.2 },
    share_of_voice: { value: 46.8, delta: 5.4 },
    brand_rank: { value: 2, delta: -1 },
  },
  movements: [
    { label: 'visibility', direction: 'positive', current: 72.4, previous: 64.2, delta: 8.2 },
    { label: 'share of voice', direction: 'positive', current: 46.8, previous: 41.4, delta: 5.4 },
    { label: 'brand rank', direction: 'positive', current: 2, previous: 3, delta: 1 },
    { label: 'competitor gap', direction: 'positive', current: 6.1, previous: 1.8, delta: 4.3 },
  ],
  actions,
  action_order_version: 0,
  resolved_actions: {
    since_audit_id: '44444444-4444-4444-8444-444444444444',
    count: 3,
    titles: ['Added author evidence', 'Fixed broken citations', 'Expanded product schema'],
  },
  report_available: true,
  stale: false,
};

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'light' });
});

test('homepage remains credible without motion', async ({ page }) => {
  await page.goto('/');
  await hideDevChrome(page);
  await expect(page).toHaveScreenshot('homepage.png', { fullPage: true });
});

test('landing content is visible when motion is enabled', async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'no-preference', colorScheme: 'light' });
  await page.goto('/');
  await hideDevChrome(page);
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible();
  const operatingLoop = page.getByRole('heading', {
    name: /move from state to evidence to action to improvement/i,
  });
  await operatingLoop.scrollIntoViewIfNeeded();
  await expect(operatingLoop).toBeVisible();
});

test('public subpages inherit the atmospheric hero', async ({ page }) => {
  await page.goto('/pricing');
  await hideDevChrome(page);
  const hero = page.locator('main header, [role="main"] header, header').filter({
    has: page.getByRole('heading', { level: 1 }),
  });
  await expect(hero).toHaveScreenshot('pricing-hero.png');
});

test('auth uses the unified identity', async ({ page }) => {
  await page.goto('/login');
  await hideDevChrome(page);
  await expect(page).toHaveScreenshot('login.png', { fullPage: true });
});

test('command center communicates state, movement, action, and proof', async ({
  page,
}, testInfo) => {
  await stubAuthedShell(page, [[`**/api/v1/projects/${PROJECT_ID}/command-center`, commandCenter]]);
  await page.goto('/projects');
  await hideDevChrome(page);
  await expect(page.getByRole('heading', { name: 'Command center' })).toBeVisible();
  await expect(page).toHaveScreenshot('command-center.png', { fullPage: true });

  if (['desktop-wide', 'tablet-portrait', 'mobile'].includes(testInfo.project.name)) {
    const output = path.resolve(
      process.cwd(),
      '..',
      'artifacts',
      'design-review',
      `command-center-${testInfo.project.name}.png`,
    );
    await page.screenshot({ path: output, fullPage: true, animations: 'disabled' });
  }
});
