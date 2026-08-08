import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const searchParams = { value: new URLSearchParams() };

vi.mock('next/navigation', () => ({
  usePathname: () => '/site',
  useSearchParams: () => searchParams.value,
}));

import { LayerTabs } from './layer-tabs';

const TABS = [
  { id: 'pages', label: 'Pages' },
  { id: 'facts', label: 'Facts' },
] as const;

describe('LayerTabs', () => {
  it('marks the first tab current when none is in the URL', () => {
    searchParams.value = new URLSearchParams();
    render(<LayerTabs tabs={TABS} />);

    expect(screen.getByRole('link', { name: 'Pages' })).toHaveAttribute('aria-current', 'page');
    expect(screen.getByRole('link', { name: 'Facts' })).not.toHaveAttribute('aria-current');
  });

  it('reads the active tab from the URL so refresh keeps it', () => {
    searchParams.value = new URLSearchParams('tab=facts');
    render(<LayerTabs tabs={TABS} />);

    expect(screen.getByRole('link', { name: 'Facts' })).toHaveAttribute('aria-current', 'page');
  });

  it('uses navigation semantics, not tab semantics', () => {
    // These are links that change the route, not tabs over a tabpanel: the
    // roles would promise roving arrow-key focus that URL links do not have.
    searchParams.value = new URLSearchParams();
    render(<LayerTabs tabs={TABS} />);

    expect(screen.queryByRole('tablist')).toBeNull();
    expect(screen.queryAllByRole('tab')).toHaveLength(0);
    expect(screen.getByRole('navigation', { name: 'Sub-surfaces' })).toBeInTheDocument();
  });

  it('links each tab rather than switching in place', () => {
    // Real links keep tabs shareable and back-button-correct.
    searchParams.value = new URLSearchParams();
    render(<LayerTabs tabs={TABS} />);

    expect(screen.getByRole('link', { name: 'Facts' })).toHaveAttribute('href', '/site?tab=facts');
  });

  it('preserves the other query params when switching tab', () => {
    // `/content` hands an insight off to a draft via `?opportunity_id=`;
    // rewriting the whole query string would drop it on the first tab click.
    searchParams.value = new URLSearchParams('opportunity_id=opp-1');
    render(<LayerTabs tabs={TABS} />);

    expect(screen.getByRole('link', { name: 'Facts' })).toHaveAttribute(
      'href',
      '/site?opportunity_id=opp-1&tab=facts',
    );
  });
});
