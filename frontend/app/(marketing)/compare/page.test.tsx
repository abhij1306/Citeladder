import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { CompareDetailView } from '@/components/marketing/pages/compare-detail';
import { COMPETITORS } from '@/lib/marketing-content/compare';

import { DEMO_HREF } from '@/lib/marketing-content/nav';

import Page from './page';

// Plain renders: the compare pages are sync RSC with no client islands, so
// no providers and no MSW. The async [competitor] route wrapper only resolves
// `params` and picks the module entry (covered by e2e's 200/404 cases) — the
// sync CompareDetailView it delegates to is rendered directly here.
// These pages are customer-facing: every row ships with both cells written,
// and no verification-process wording ("Not verified by us" et al.) may
// reach the DOM.
describe('Compare index page (/compare)', () => {
  it('renders exactly one h1 and no h2–h6 containing the product name', () => {
    render(<Page />);

    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(/how citeladder compares/i);

    // Heading-name convention: only the h1 may contain "CiteLadder".
    for (const heading of screen.getAllByRole('heading')) {
      if (heading === h1s[0]) continue;
      expect(heading).not.toHaveTextContent(/citeladder/i);
    }
  });

  it('lists one card per published comparison', () => {
    render(<Page />);

    const grid = screen.getByRole('region', { name: 'Competitors' });
    const links = within(grid).getAllByRole('link');
    expect(links).toHaveLength(COMPETITORS.length);
    for (const competitor of COMPETITORS) {
      expect(
        links.some((link) => link.getAttribute('href') === `/compare/${competitor.slug}`),
        `expected a card linking to /compare/${competitor.slug}`,
      ).toBe(true);
    }
    expect(within(grid).getByText(`${COMPETITORS.length} comparisons`)).toBeInTheDocument();
    // The research-in-progress state is gone now that pages are live.
    expect(within(grid).queryByText(/Comparison research is in progress/i)).toBeNull();
  });

  it('closes with a CTA band linking to the demo funnel', () => {
    render(<Page />);

    const ctaBand = screen.getByRole('region', { name: 'Get started' });
    expect(within(ctaBand).getByRole('link', { name: /book a demo/i })).toHaveAttribute(
      'href',
      DEMO_HREF,
    );
  });
});

describe('CompareDetailView (/compare/[competitor])', () => {
  const competitor = COMPETITORS[0];

  it('renders exactly one h1 and no h2–h6 containing the product name', () => {
    render(<CompareDetailView competitor={competitor} />);

    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(`CiteLadder vs ${competitor.name}.`);

    for (const heading of screen.getAllByRole('heading')) {
      if (heading === h1s[0]) continue;
      expect(heading).not.toHaveTextContent(/citeladder/i);
    }
  });

  it('renders both columns, the freshness badge, and the editorial blocks', () => {
    const { container } = render(<CompareDetailView competitor={competitor} />);

    // Table header: real CiteLadder column, competitor column named for the slug.
    expect(screen.getByRole('columnheader', { name: 'CiteLadder' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: competitor.name })).toBeInTheDocument();

    // Every row ships with BOTH cells written — dimension, ours, theirs.
    for (const row of competitor.rows) {
      expect(screen.getByText(row.dimension)).toBeInTheDocument();
      expect(screen.getByText(row.citeladder)).toBeInTheDocument();
      expect(screen.getByText(row.competitor)).toBeInTheDocument();
    }

    // Header badges: the vendor's tagline and the freshness stamp — never a
    // verification-process badge.
    expect(screen.getByText(competitor.tagline)).toBeInTheDocument();
    expect(screen.getByText(`Last reviewed · ${competitor.lastReviewed}`)).toBeInTheDocument();

    // Editorial blocks: verdict plus the honest "where they fit better".
    const editorial = screen.getByRole('region', { name: 'Verdict and fit' });
    expect(within(editorial).getByText(competitor.verdict)).toBeInTheDocument();
    expect(
      within(editorial).getByRole('heading', { name: `Where ${competitor.name} fits better.` }),
    ).toBeInTheDocument();
    expect(within(editorial).getByText(competitor.betterFit)).toBeInTheDocument();

    // No verification theater may reach the DOM — this is a customer page.
    expect(container.textContent).not.toMatch(/Not verified by us/);
    expect(container.textContent).not.toMatch(/Not independently verified/);
    expect(container.textContent).not.toMatch(/rather show a gap than a guess/i);
    expect(container.textContent).not.toMatch(/TODO\(user\)/);
  });

  it('shows the freshness line under the table', () => {
    render(<CompareDetailView competitor={competitor} />);

    expect(screen.getByText(/Maintained by the CiteLadder team/i)).toBeInTheDocument();
    expect(
      screen.getByText(new RegExp(`Last reviewed\\s+${competitor.lastReviewed}`, 'i')),
    ).toBeInTheDocument();
  });

  it('links back to the comparison index', () => {
    render(<CompareDetailView competitor={competitor} />);

    expect(screen.getByRole('link', { name: /all comparisons/i })).toHaveAttribute(
      'href',
      '/compare',
    );
  });
});
