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
  it('selects the first tab when none is in the URL', () => {
    searchParams.value = new URLSearchParams();
    render(<LayerTabs tabs={TABS} />);

    expect(screen.getByRole('tab', { name: 'Pages' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Facts' })).toHaveAttribute('aria-selected', 'false');
  });

  it('reads the active tab from the URL so refresh keeps it', () => {
    searchParams.value = new URLSearchParams('tab=facts');
    render(<LayerTabs tabs={TABS} />);

    expect(screen.getByRole('tab', { name: 'Facts' })).toHaveAttribute('aria-selected', 'true');
  });

  it('links each tab rather than switching in place', () => {
    // Real links keep tabs shareable and back-button-correct.
    searchParams.value = new URLSearchParams();
    render(<LayerTabs tabs={TABS} />);

    expect(screen.getByRole('tab', { name: 'Facts' })).toHaveAttribute('href', '/site?tab=facts');
  });
});
