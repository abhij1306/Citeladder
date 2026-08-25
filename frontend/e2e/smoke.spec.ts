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

  // docs/design.md §Colour is the authority: the page canvas is the luminous
  // pearl-paper `background` token, while crisp white is `panel` / `elevated`,
  // the surface that sits ON the canvas. This asserted the panel colour for the
  // canvas, and no CI job ran it, so the drift went unnoticed.
  await expect(page.locator('.bg-background').first()).toHaveCSS(
    'background-color',
    'rgb(248, 250, 252)',
  );

  await expect(page.getByRole('img', { name: /ChatGPT, Grok, Gemini/i })).toBeVisible();

  expect(pageErrors, pageErrors.join('\n')).toHaveLength(0);
});
