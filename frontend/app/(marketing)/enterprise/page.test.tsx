import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { DEMO_HREF } from '@/lib/marketing-content/nav';

import Page from './page';

// Plain render — the page is a sync RSC with no client islands, so it needs
// no providers and no MSW.
describe('Enterprise page (public marketing `/enterprise`)', () => {
  it('renders exactly one h1 and no product-name subheadings', () => {
    render(<Page />);

    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(/enterprise-grade evidence/i);

    // No h2-h6 may contain the product name (keeps heading queries unambiguous).
    for (const heading of screen.getAllByRole('heading')) {
      if (heading === h1s[0]) continue;
      expect(heading).not.toHaveTextContent(/citeladder/i);
    }
  });

  it('renders the trustworthy-operations grid grounded in the README', () => {
    render(<Page />);

    const ops = screen.getByRole('region', { name: 'Enterprise capabilities' });
    // Three cards, not four: the old "Traceable by design" card restated the
    // evidence card's provenance claim, so the page argued the same point twice.
    expect(within(ops).getAllByRole('heading', { level: 3 })).toHaveLength(3);
    // README "Built for trustworthy operations" bullets, rendered verbatim-ish.
    expect(within(ops).getByText(/UUID identifiers throughout/i)).toBeInTheDocument();
    expect(within(ops).getAllByText(/Immutable artifacts/i).length).toBeGreaterThan(0);
    expect(within(ops).getByText(/FOR UPDATE SKIP LOCKED/i)).toBeInTheDocument();
    expect(
      within(ops).getByText(/backend topology never reaches the client bundle/i),
    ).toBeInTheDocument();
    expect(within(ops).getByText(/Zod \+ Pydantic/i)).toBeInTheDocument();
  });

  it('renders no GitHub/MIT links, no self-host copy, and points the hero ghost at /pricing', () => {
    const { container } = render(<Page />);

    // The repo is private — no GitHub or MIT-license links anywhere.
    expect(screen.queryByRole('link', { name: /github|MIT license/i })).toBeNull();

    // The self-host deployment section is gone — CiteLadder ships as managed
    // cloud only, so no self-host copy may reach the page.
    expect(screen.queryByRole('region', { name: 'Deployment options' })).toBeNull();
    expect(container.textContent).not.toMatch(/self-host|Docker Compose/i);

    // The architecture proof survives inside the capabilities section.
    const flow = screen.getByRole('region', { name: 'Platform data flow' });
    expect(within(flow).getByText('PostgreSQL')).toBeInTheDocument();

    // The hero ghost CTA now routes to the pricing page.
    expect(screen.getByRole('link', { name: /compare plans/i })).toHaveAttribute(
      'href',
      '/pricing',
    );
  });

  it('names what each enterprise dial measures instead of repeating "Custom"', () => {
    render(<Page />);

    const limits = screen.getByRole('region', { name: 'Custom limits' });
    for (const label of [
      'Monthly audit runs',
      'Monitored URLs',
      'Projects & seats',
      'Evidence retention',
    ]) {
      expect(within(limits).getByText(label)).toBeInTheDocument();
    }

    // Each dial carries its own UNIT — the information a buyer needs to size a
    // plan. The page previously answered all six with the bare word "Custom",
    // which read as six identical facts; sizing is now stated once, up front.
    expect(within(limits).getByText('prompt × engine × repetition')).toBeInTheDocument();
    expect(within(limits).getByText(/sized to your volumes/i)).toBeInTheDocument();
    expect(within(limits).queryByText('Custom')).not.toBeInTheDocument();
  });

  it('renders the contact CTA with a real destination, never href="#"', () => {
    render(<Page />);

    // Both actions route through the stable internal demo funnel.
    const cta = screen.getByRole('region', { name: 'Contact sales' });
    const contacts = screen.getAllByRole('link', { name: /book a demo/i });
    expect(contacts.length).toBeGreaterThan(0);
    for (const contact of contacts) {
      expect(contact.getAttribute('href')).not.toBe('#');
    }
    expect(screen.getAllByRole('link', { name: /book a demo/i })[0]).toHaveAttribute(
      'href',
      DEMO_HREF,
    );
    expect(within(cta).getByRole('link', { name: /book a demo/i })).toHaveAttribute(
      'href',
      DEMO_HREF,
    );
  });
});
