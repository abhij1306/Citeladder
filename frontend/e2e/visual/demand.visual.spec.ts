import { expect, test } from '@playwright/test';

import { hideDevChrome, stubAuthedShell } from '../helpers/app-fixture';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';

test('Demand Intelligence empty workspace', async ({ page }) => {
  await stubAuthedShell(page, [
    [`**/api/v1/projects/${PROJECT_ID}/demand/snapshots?limit=20`, { items: [] }],
    [`**/api/v1/projects/${PROJECT_ID}/demand/capabilities`, { datasets: [] }],
  ]);

  await page.goto('/demand');
  await hideDevChrome(page);
  await expect(page.getByRole('heading', { level: 1, name: 'Demand' })).toBeVisible();
  await expect(page.getByText('No Demand snapshot exists yet.')).toBeVisible();
  await expect(page).toHaveScreenshot('demand-empty-workspace.png', { fullPage: true });
});
