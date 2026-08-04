import { describe, expect, it, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { DEMO_HREF } from '@/lib/marketing-content/nav';

import Page from './page';

// The catalog island owns every network read; this test covers only the SYNC
// server shell around it, so it renders directly with no providers and no MSW.
// Plan/price/comparison assertions live in `pricing-catalog.test.tsx`, which
// has a real catalog fixture to assert against.
vi.mock('@/components/marketing/pricing/pricing-catalog', () => ({
  PricingCatalog: () => <div data-testid="pricing-catalog-island" />,
}));

describe('Pricing page (public marketing `/pricing`)', () => {
  it('renders exactly one h1 and keeps the product name out of h2-h6', () => {
    render(<Page />);

    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(/pay for the evidence layer/i);

    for (const heading of screen.getAllByRole('heading')) {
      if (heading === h1s[0]) continue;
      expect(heading).not.toHaveTextContent(/citeladder/i);
    }
  });

  it('renders the static shell and delegates plans to the catalog island', () => {
    render(<Page />);

    expect(screen.getByTestId('pricing-catalog-island')).toBeInTheDocument();
    // No plan card may be server-rendered: a price in this HTML would be a
    // price the server guessed rather than one the catalog resolved.
    expect(document.querySelectorAll('[data-tier]')).toHaveLength(0);
    expect(document.querySelectorAll('[data-price]')).toHaveLength(0);
  });

  it('carries no retired commercial claim in the static shell', () => {
    const { container } = render(<Page />);
    const text = container.textContent ?? '';

    expect(text).not.toMatch(/\$49/);
    expect(text).not.toMatch(/\bFree\b/);
    expect(text).not.toMatch(/Every plan runs on your own keys/);
    expect(text).not.toMatch(/TODO\(user\)/);
  });

  it('states the BYOK trust claims in the hero', () => {
    render(<Page />);

    expect(screen.getAllByText(/bring your own api keys/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/encrypted at rest/i).length).toBeGreaterThan(0);
    expect(screen.getAllByText(/no llm-as-judge scoring/i).length).toBeGreaterThan(0);
  });

  it('closes with the demo-first CTA and a route into the FAQ', () => {
    render(<Page />);

    const finalCta = screen.getByRole('region', { name: 'Get started' });
    expect(within(finalCta).getByRole('link', { name: /book a demo/i })).toHaveAttribute(
      'href',
      DEMO_HREF,
    );
    expect(within(finalCta).getByRole('link', { name: /read the faq/i })).toHaveAttribute(
      'href',
      '/faq',
    );
  });
});
