import { expect, test } from '@playwright/test';

/**
 * Smoke: the public landing page renders at `/` with no backend running (the
 * session island stays inert when `/auth/me` fails), the hero owns the page's
 * single level-1 heading, and the Proof surface paints.
 *
 * The previous version of this test clicked a theme toggle in the marketing
 * nav. There is no such control — the public surface is a fixed light identity
 * — so it could only ever have failed.
 */
test('landing renders on the Proof surface without a backend', async ({ page }) => {
  const pageErrors: string[] = [];
  page.on('pageerror', (error) => pageErrors.push(String(error)));

  await page.goto('/');

  const h1 = page.getByRole('heading', { level: 1 });
  await expect(h1).toBeVisible();
  await expect(h1).toHaveCount(1);

  await expect(page.locator('.citeladder-root')).toHaveCSS(
    'background-color',
    'rgb(245, 248, 247)',
  );

  // The hero scene is decorative, so its figures must stay out of the
  // accessibility tree while its honesty mark stays visible.
  await expect(page.getByText('Example data').first()).toBeVisible();

  expect(pageErrors, pageErrors.join('\n')).toHaveLength(0);
});
