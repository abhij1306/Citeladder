import { render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { FAQ_GROUPS } from '@/lib/marketing-content/faq';

import Page from './page';

const TOTAL_ITEMS = FAQ_GROUPS.reduce((sum, group) => sum + group.items.length, 0);

// Plain render — the page is a sync RSC with no client islands, so it needs
// no providers and no MSW. The shared chrome (nav/footer) lives in the
// (marketing) route-group layout and is covered by colocated component tests.
describe('FAQ page (public marketing `/faq`)', () => {
  it('renders exactly one h1 and keeps the product name out of h2–h6', () => {
    render(<Page />);

    const h1s = screen.getAllByRole('heading', { level: 1 });
    expect(h1s).toHaveLength(1);
    expect(h1s[0]).toHaveTextContent(/frequently asked questions/i);

    // No h2-h6 may contain the product name (keeps heading queries unambiguous).
    for (const heading of screen.getAllByRole('heading')) {
      if (heading === h1s[0]) continue;
      expect(heading).not.toHaveTextContent(/citeladder/i);
    }
  });

  it('renders the four module groups as labelled sections with h2 headings', () => {
    render(<Page />);

    expect(FAQ_GROUPS.map((group) => group.heading)).toEqual([
      'Product',
      'Privacy & keys',
      'Site health',
      'Account & billing',
    ]);
    for (const group of FAQ_GROUPS) {
      const section = screen.getByRole('region', { name: group.heading });
      expect(within(section).getByRole('heading', { level: 2 })).toHaveTextContent(group.heading);
      expect(within(section).getByText(`${group.items.length} answers`)).toBeInTheDocument();
    }
    // The open-source group is gone — the repo is private.
    expect(screen.queryByRole('region', { name: 'Open source' })).toBeNull();
  });

  it('renders the group rail with an anchor link + item count per group', () => {
    const { container } = render(<Page />);

    const toc = screen.getByRole('navigation', { name: 'FAQ groups' });
    const links = within(toc).getAllByRole('link');
    expect(links).toHaveLength(FAQ_GROUPS.length);

    for (const [index, group] of FAQ_GROUPS.entries()) {
      // Accessible name is "<heading> <count>", e.g. "Privacy & keys 3".
      expect(links[index]).toHaveTextContent(group.heading);
      expect(links[index]).toHaveTextContent(String(group.items.length));
      // Each rail anchor resolves to the matching group section on the page.
      const href = links[index].getAttribute('href');
      expect(href).toMatch(/^#faq-/);
      if (!href) throw new Error('rail link missing href');
      expect(container.ownerDocument.getElementById(href.slice(1))).not.toBeNull();
    }
  });

  it('renders every module item as a native details/summary accordion row', () => {
    const { container } = render(<Page />);

    // One <details>/<summary> pair per module item — zero client JS.
    expect(container.querySelectorAll('details')).toHaveLength(TOTAL_ITEMS);
    expect(container.querySelectorAll('summary')).toHaveLength(TOTAL_ITEMS);
    expect(screen.queryByRole('button')).not.toBeInTheDocument();

    // Every question and answer string from the module is rendered. Answers
    // may be split into inline links/todo-tag pills, so match on the full
    // textContent of the answer paragraph.
    for (const group of FAQ_GROUPS) {
      for (const item of group.items) {
        expect(screen.getByText(item.q)).toBeInTheDocument();
        expect(
          screen.getAllByText((_, el) => el?.tagName === 'P' && el.textContent === item.a).length,
        ).toBeGreaterThan(0);
      }
    }
  });

  it('points to the catalog instead of quoting a price under Account & billing', () => {
    const { container } = render(<Page />);

    const billing = screen.getByRole('region', { name: 'Account & billing' });
    // Prices are region-resolved per visitor and published by the catalog, so
    // an amount hard-coded here would be wrong for most readers and stale for
    // the rest. The FAQ routes to /pricing rather than restating a number.
    expect(within(billing).getAllByText(/\/pricing/).length).toBeGreaterThan(0);
    expect(container.textContent).not.toMatch(/\$49/);
    expect(container.textContent).not.toMatch(/Free plan|no card/i);
    expect(within(billing).getByText(/India.*INR.*GST/)).toBeInTheDocument();
    // The BYOK-therefore-flat-fee reasoning is stated, not implied.
    expect(within(billing).getByText(/never marked up by/i)).toBeInTheDocument();
    // No unfinished placeholder may reach the page.
    expect(container.textContent).not.toMatch(/TODO\(user\)/);
  });

  it('states the no-markup billing rule under Account & billing', () => {
    render(<Page />);

    const billing = screen.getByRole('region', { name: 'Account & billing' });
    expect(within(billing).getByText('Do you mark up model usage?')).toBeInTheDocument();
    expect(within(billing).getByText(/never passes through us/i)).toBeInTheDocument();
  });

  it('names Perplexity, Copilot and AI Overview only as referral sources', () => {
    render(<Page />);

    // The one allowed mention of non-audited engines: the AI-referral
    // classification answer, framed as detected referral traffic sources.
    const product = screen.getByRole('region', { name: 'Product' });
    const answer = within(product).getByText(/not audited engines/i);
    expect(answer).toHaveTextContent(/Perplexity/);
    expect(answer).toHaveTextContent(/Microsoft Copilot/);
    expect(answer).toHaveTextContent(/Google AI Overview/);
    expect(answer).toHaveTextContent(/referral/);
  });

  it('emits FAQPage JSON-LD that parses and covers every module item', () => {
    const { container } = render(<Page />);

    const script = container.querySelector('script[type="application/ld+json"]');
    expect(script).not.toBeNull();
    expect(script).not.toHaveAttribute('id');
    const data = JSON.parse(script?.textContent ?? '') as Record<string, unknown>;
    expect(data['@context']).toBe('https://schema.org');
    expect(data['@type']).toBe('FAQPage');

    const mainEntity = data.mainEntity as { '@type': string; name: string }[];
    expect(mainEntity).toHaveLength(TOTAL_ITEMS);
    expect(mainEntity[0]?.['@type']).toBe('Question');
    expect(mainEntity[0]?.name).toBe(FAQ_GROUPS[0]?.items[0]?.q);
  });
});
