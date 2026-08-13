import { expect, test } from '@playwright/test';

import { hideDevChrome, stubAuthedShell } from '../helpers/app-fixture';

test('Demand Intelligence empty workspace', async ({ page }) => {
  await stubAuthedShell(page);

  await page.goto('/demand');
  await hideDevChrome(page);
  await expect(page.getByRole('heading', { level: 1, name: 'Demand' })).toBeVisible();
  await expect(page.getByText('No Demand snapshot exists yet.')).toBeVisible();
  await expect(page).toHaveScreenshot('demand-empty-workspace.png', { fullPage: true });
});
