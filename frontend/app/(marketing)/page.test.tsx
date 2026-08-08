import { http, HttpResponse } from 'msw';
import { afterAll, afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { screen, waitFor, within } from '@testing-library/react';

import { queryKeys } from '@/lib/api/query-keys';
import { DEMO_HREF } from '@/lib/marketing-content/nav';
import { mswServer } from '@/test/msw-server';
import { renderWithProviders } from '@/test/render';

const replace = vi.fn();
vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace, push: vi.fn(), refresh: vi.fn() }),
}));

import Page from './page';

beforeAll(() => mswServer.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  mswServer.resetHandlers();
  replace.mockReset();
});
afterAll(() => mswServer.close());

/** Anonymous visitor: the session check 401s and the island stays inert. */
function stubAnonymous() {
  mswServer.use(
    http.get('/api/v1/auth/me', () =>
      HttpResponse.json({ detail: 'Unauthorized' }, { status: 401 }),
    ),
  );
}

// Landing content only. The shared chrome (aurora/grain backdrop, LandingNav,
// LandingFooter) moved into the (marketing) route-group layout, whose
// next/font import makes direct layout renders impractical in vitest — the
// nav/footer contracts get colocated component tests and the layout
// composition is covered by e2e. The LandingSessionRedirect island itself is
// covered exhaustively in components/marketing/landing-session-redirect.test.tsx.
describe('Landing page (public marketing `/`)', () => {
  it('renders exactly one h1 and keeps the marketing content up after the 401 settles', async () => {
    stubAnonymous();
    const { queryClient } = renderWithProviders(<Page />);

    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(/your buyers stopped googling you/i);

    // No h2-h6 may contain the product name (keeps heading queries unambiguous).
    const headings = screen.getAllByRole('heading');
    for (const heading of headings) {
      if (heading === h1s[0]) continue;
      expect(heading).not.toHaveTextContent(/citeladder/i);
    }

    // The session-check island stays inert for an anonymous visitor: the 401
    // settles, no redirect fires, and the content never leaves the screen.
    await waitFor(() =>
      expect(queryClient.getQueryState(queryKeys.auth.me())?.status).toBe('error'),
    );
    expect(replace).not.toHaveBeenCalled();
    expect(h1s[0]).toBeInTheDocument();
  });

  it('uses the shared primary button for the hero action', () => {
    stubAnonymous();
    const { container } = renderWithProviders(<Page />);

    const hero = container.querySelector('header');
    const cta = hero?.querySelector('a[href="/demo"]');
    expect(cta).toHaveTextContent('Book a demo');
    expect(cta?.querySelector('svg')).not.toBeNull();
  });

  it('exposes the section anchors the shared chrome links to', () => {
    stubAnonymous();
    const { container } = renderWithProviders(<Page />);

    // The nav/footer (rendered by the layout) target these ids — pin them.
    // `#platform` and `#evidence` are back: the platform section returned with
    // the four-layer architecture, and `#evidence` is the provenance chain
    // added by frontend-growth-intelligence.md §8.2.
    for (const hash of [
      '#why',
      '#how-it-works',
      '#platform',
      '#see-it',
      '#evidence',
      '#industry-packs',
      '#get-started',
    ]) {
      expect(container.querySelector(hash)).not.toBeNull();
    }
  });

  it('leads with the loop before the module breakdown', () => {
    stubAnonymous();
    const { container } = renderWithProviders(<Page />);

    // §8.2: the differentiator is evidence → improvement → verification; the
    // module breakdown is HOW, not WHY. If Platform ever drifts back above
    // Workflow, the page argues the wrong thing first.
    const sections = Array.from(container.querySelectorAll('main > section[id]')).map(
      (section) => section.id,
    );

    // Assert both exist first: a missing section yields -1, which would
    // satisfy the ordering comparison for the wrong reason.
    expect(sections).toContain('how-it-works');
    expect(sections).toContain('platform');
    expect(sections.indexOf('how-it-works')).toBeLessThan(sections.indexOf('platform'));
  });

  it('shows the evidence chain and a real insight object', () => {
    stubAnonymous();
    const { container } = renderWithProviders(<Page />);

    const evidence = container.querySelector('#evidence');
    expect(evidence).not.toBeNull();
    // The chain is the claim competitors cannot copy; the insight object is
    // the product's most recognisable artifact.
    expect(evidence).toHaveTextContent(/Artifact/);
    expect(evidence).toHaveTextContent(/Verification/);
    expect(evidence).toHaveTextContent(/Why this matters/);
  });

  it('alternates section bands so no two neighbours share a tone', () => {
    stubAnonymous();
    const { container } = renderWithProviders(<Page />);

    // Section.tsx: "NO TWO ADJACENT BANDS SHARE A TONE". Reordering the page
    // is exactly when that invariant breaks, so it is asserted rather than
    // eyeballed.
    const tones = Array.from(container.querySelectorAll('main > section')).map((section) =>
      section.getAttribute('data-citeladder-section'),
    );

    for (let index = 1; index < tones.length; index += 1) {
      expect(tones[index], `sections ${index - 1} and ${index} share a tone`).not.toBe(
        tones[index - 1],
      );
    }
  });

  it('closes with a FinalCta section pointing at the demo funnel', () => {
    stubAnonymous();
    renderWithProviders(<Page />);

    const finalCta = screen.getByRole('region', { name: 'Get started' });
    // Asserted by DESTINATION, not by label: the funnel is the contract here.
    const cta = within(finalCta).getByRole('link', { name: /book a demo/i });
    expect(cta).toHaveAttribute('href', DEMO_HREF);
  });

  it('keeps the evaluation-gating note and scene artifact ids off the page', () => {
    stubAnonymous();
    renderWithProviders(<Page />);

    expect(screen.queryByText(/limited workspace/i)).toBeNull();
    for (const id of ['09F3C21E', '1A64D0BC', '3E92BA71']) {
      expect(screen.queryByText(id)).toBeNull();
    }
  });

  it('keeps illustrative scene figures out of the page copy', () => {
    stubAnonymous();
    const { container } = renderWithProviders(<Page />);

    // Illustrative figures stay outside the accessible page copy even though
    // the old visible "Example data" header pills are gone.
    expect(screen.queryByText(/example data/i)).toBeNull();
    for (const node of Array.from(container.querySelectorAll('*'))) {
      if (node.children.length > 0 || !/\b(72\.4|1,248|3,091)\b/.test(node.textContent ?? '')) {
        continue;
      }
      expect(
        node.closest('[aria-hidden="true"]'),
        `${node.textContent} is not aria-hidden`,
      ).not.toBeNull();
    }
  });

  it('keeps the first screen text-only and places the workspace directly after it', () => {
    stubAnonymous();
    const { container } = renderWithProviders(<Page />);

    const hero = container.querySelector('header');
    const main = container.querySelector('main');
    expect(hero).not.toBeNull();
    expect(hero).not.toHaveTextContent(/your ai visibility|tracking your brand/i);
    expect(main?.children[0]).toBe(hero);
    // The shift chapter follows the hook; the product canvas comes after it.
    expect(main?.children[1]).toHaveAttribute('id', 'why');
  });

  it('shows the product canvas once, after the hero states the problem', () => {
    stubAnonymous();
    const { container } = renderWithProviders(<Page />);

    // The page used to run the question→verdicts demo TWICE — ambient in the
    // hero and again as the "see it" beat — so the scroll repeated itself.
    // The second beat is now the workspace, opened to its evidence.
    const product = container.querySelector('#see-it');
    expect(product).not.toBeNull();
    expect(product).toHaveTextContent(/every score opens to the answer behind it/i);
    expect(product).not.toHaveTextContent(/example data/i);
  });

  it('uses white panel cards for the shift facts and product demo', () => {
    stubAnonymous();
    const { container } = renderWithProviders(<Page />);

    expect(container.querySelectorAll('#why article.bg-panel')).toHaveLength(3);
    // Tie the assertion to ProductWindow's own stable hook, not any panel.
    const seeIt = container.querySelector('#see-it');
    expect(seeIt?.querySelector('[data-testid="product-window"]')).not.toBeNull();
  });
});
