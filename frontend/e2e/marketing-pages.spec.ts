import { expect, test } from '@playwright/test';

const MARKETING_PAGES = [
  '/pricing',
  '/enterprise',
  '/demo',
  '/solutions',
  '/blog',
  '/blog/how-we-measure-ai-visibility-deterministically',
  '/compare',
  '/compare/profound',
  '/faq',
];

// Every visitor-reachable route: the ten marketing pages, one blog post and
// one comparison detail, plus the two Proof-surface auth routes.
const PUBLIC_ROUTES = [
  '/',
  ...MARKETING_PAGES,
  '/blog/how-we-measure-ai-visibility-deterministically',
  '/compare/profound',
  '/login',
  '/register',
];

test.describe('marketing routes', () => {
  test('public routes render anonymously with one visible h1', async ({ page }) => {
    for (const path of MARKETING_PAGES) {
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);
      await expect(page.locator('h1:visible')).toHaveCount(1);
    }
  });

  test('published content slugs return 200 and unknown slugs return 404', async ({ page }) => {
    for (const path of [
      '/blog/how-we-measure-ai-visibility-deterministically',
      '/compare/profound',
      '/compare/otterly-ai',
      '/compare/scrunch-ai',
      '/compare/peec-ai',
    ]) {
      const response = await page.goto(path);
      expect(response?.status()).toBe(200);
    }
    for (const path of [
      '/blog/hello-citeladder',
      '/blog/does-not-exist',
      '/compare/does-not-exist',
    ]) {
      const response = await page.goto(path);
      expect(response?.status()).toBe(404);
    }
  });

  test('shared navigation and footer work from a subpage', async ({ page }) => {
    await page.goto('/pricing');
    const resources = page
      .getByRole('navigation', { name: 'Main navigation' })
      .getByRole('link', { name: 'Resources', exact: true });
    await resources.hover();
    await expect(page.locator('#desktop-nav-panel-resources')).toBeVisible();
    await expect(page.locator('#desktop-nav-panel-resources').getByRole('link')).toHaveCount(3);

    const footer = page.getByRole('navigation', { name: 'Footer' });
    await expect(footer.getByRole('link', { name: 'Pricing', exact: true })).toBeVisible();
    await expect(footer.getByRole('link', { name: 'Blog', exact: true })).toBeVisible();
    // The repo is private — no Documentation/GitHub links in the footer.
    await expect(footer.getByRole('link', { name: 'Documentation' })).toHaveCount(0);
    await expect(footer.getByRole('link', { name: 'GitHub' })).toHaveCount(0);
  });

  test('commercial pages carry no GitHub links or MIT-license copy', async ({ page }) => {
    for (const path of ['/pricing', '/enterprise']) {
      await page.goto(path);
      await expect(page.getByRole('link', { name: /github/i })).toHaveCount(0);
      await expect(page.getByText(/MIT License/i)).toHaveCount(0);
    }
  });

  test('marketing subpages render the unified light canvas', async ({ page }) => {
    await page.goto('/pricing');
    // docs/design.md §Colour: the canvas is the shared warm `background`
    // token. Crisp white is `panel` / `elevated`, and the deeper warm neutral
    // is the grouped-region well (`background-alt` / `well`) —
    // neither of those is the canvas.
    await expect(page.locator('.bg-background').first()).toHaveCSS(
      'background-color',
      'rgb(250, 249, 246)',
    );
  });

  test('the logged-out auth screens run the same Prism surface', async ({ page }) => {
    for (const path of ['/login', '/register']) {
      await page.goto(path);
      await expect(page.locator('.bg-panel').first()).toHaveCount(1);
      await expect(page.locator('h1:visible')).toHaveCount(1);
      // Prism is light-only: no toggle survives on the auth shell.
      await expect(page.getByRole('button', { name: 'Toggle color theme' })).toHaveCount(0);
    }
  });

  test('the public surface makes no self-host or open-source claim', async ({ page }) => {
    for (const path of PUBLIC_ROUTES) {
      await page.goto(path);
      await expect(page.locator('body')).not.toHaveText(
        /self-host|self host|open source|Docker Compose|scheduled audits|TODO\(user\)|citeladder\.example/i,
      );
    }
  });
});
