import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const { pathname } = vi.hoisted(() => ({ pathname: { value: '/visibility' } }));

vi.mock('next/navigation', () => ({
  usePathname: () => pathname.value,
}));

import { PageHeader } from './page-header';

function renderTitle(route: string) {
  pathname.value = route;
  render(<PageHeader />);
  return screen.getByRole('heading', { level: 1 }).textContent;
}

describe('PageHeader', () => {
  it.each([
    ['/visibility', 'Overview'],
    ['/analytics', 'AI Referrals'],
    ['/traffic', 'Traffic'],
    ['/prompts', 'Prompts'],
    ['/opportunities', 'Opportunities'],
    ['/site-health', 'Site health'],
    // §9.3: the route persists, the label is "Facts".
    ['/knowledge-base', 'Facts'],
    ['/prompt-research', 'Prompt research'],
    // The layer routes. `/site` must not be swallowed by `/site-health`.
    ['/site', 'Site'],
    ['/demand', 'Demand'],
    ['/agent', 'Growth Agent'],
    ['/reports', 'Reports'],
  ])('resolves %s to the page title %s', (route, title) => {
    expect(renderTitle(route)).toBe(title);
  });

  it.each([
    ['/traffic/anything', 'Traffic'],
    ['/runs/abc', 'Run detail'],
    ['/runs/abc/executions/def', 'Execution evidence'],
    ['/products/abc', 'Product evidence'],
    ['/site-health/crawls/abc/pages/def', 'Page detail'],
  ])('resolves deeper route %s by longest-prefix match to %s', (route, title) => {
    expect(renderTitle(route)).toBe(title);
  });

  it('falls back to the product name for unknown routes', () => {
    expect(renderTitle('/nope')).toBe('CiteLadder');
  });

  it('renders the summary and actions slots alongside the title', () => {
    pathname.value = '/visibility';
    render(
      <PageHeader
        summary={<span>mentioned in 62% of answers</span>}
        actions={<span>Metrics</span>}
      />,
    );
    expect(screen.getByText('mentioned in 62% of answers')).toBeInTheDocument();
    expect(screen.getByText('Metrics')).toBeInTheDocument();
  });

  it('accepts an explicit title override', () => {
    pathname.value = '/visibility';
    render(<PageHeader title="Custom" />);
    expect(screen.getByRole('heading', { level: 1 }).textContent).toBe('Custom');
  });
});
