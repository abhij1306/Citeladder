import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ProductsScreen } from './products-screen';

let urlTab: string | null = null;
const replaceStateSpy = vi.fn((_data: unknown, _unused: string, url: string) => {
  urlTab = new URL(url, 'http://localhost').searchParams.get('tab');
});
vi.stubGlobal('history', { ...window.history, replaceState: replaceStateSpy });

vi.mock('next/navigation', () => ({
  usePathname: () => '/products',
  useSearchParams: () => new URLSearchParams(urlTab ? `tab=${urlTab}` : ''),
}));
vi.mock('@/lib/project/project-context', () => ({
  useProjectContext: () => ({
    activeProject: { id: '11111111-1111-4111-8111-111111111111' },
    isLoading: false,
  }),
}));

const enabledCalls = {
  overview: vi.fn(),
  catalog: vi.fn(),
  visibility: vi.fn(),
  competitors: vi.fn(),
  opportunities: vi.fn(),
};
vi.mock('@/lib/products/use-products-screen', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/products/use-products-screen')>();
  return {
    ...original,
    useCommerceOverview: (_id: string, enabled: boolean) => {
      enabledCalls.overview(enabled);
      return {};
    },
    useCatalogQueries: (_id: string, enabled: boolean) => {
      enabledCalls.catalog(enabled);
      return {};
    },
    useProductVisibilityQueries: (_id: string, enabled: boolean) => {
      enabledCalls.visibility(enabled);
      return {};
    },
    useCommerceComparison: (_id: string, enabled: boolean) => {
      enabledCalls.competitors(enabled);
      return {};
    },
    useCommerceOpportunities: (_id: string, enabled: boolean) => {
      enabledCalls.opportunities(enabled);
      return {};
    },
  };
});

vi.mock('./commerce-overview-panel', () => ({
  CommerceOverviewPanel: () => <div data-testid="overview-panel" />,
}));
vi.mock('./catalog-panel', () => ({ CatalogPanel: () => <div data-testid="catalog-panel" /> }));
vi.mock('./ai-visibility-panel', () => ({
  AiVisibilityPanel: () => <div data-testid="visibility-panel" />,
}));
vi.mock('./competitors-panel', () => ({
  CompetitorsPanel: () => <div data-testid="competitors-panel" />,
}));
vi.mock('./commerce-opportunities-panel', () => ({
  CommerceOpportunitiesPanel: () => <div data-testid="opportunities-panel" />,
}));

describe('ProductsScreen tabs', () => {
  beforeEach(() => {
    replaceStateSpy.mockClear();
    Object.values(enabledCalls).forEach((spy) => spy.mockClear());
    urlTab = null;
  });

  it('defaults to Overview and renders the five-tab contract', () => {
    render(<ProductsScreen />);
    expect(screen.getAllByRole('tab')).toHaveLength(5);
    expect(screen.getByRole('tab', { name: 'Overview' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'AI Visibility' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Competitors' })).toBeInTheDocument();
    expect(screen.getByRole('tab', { name: 'Opportunities' })).toBeInTheDocument();
    expect(screen.getByTestId('overview-panel')).toBeInTheDocument();
    expect(screen.getAllByRole('tabpanel')).toHaveLength(1);
  });

  it('mirrors tab selection into the URL', async () => {
    const user = userEvent.setup();
    render(<ProductsScreen />);
    await user.click(screen.getByRole('tab', { name: 'AI Visibility' }));
    expect(screen.getByTestId('visibility-panel')).toBeInTheDocument();
    expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/products?tab=visibility');
  });

  it('reads an initial tab and falls back to Overview for removed values', () => {
    urlTab = 'competitors';
    const { unmount } = render(<ProductsScreen />);
    expect(screen.getByTestId('competitors-panel')).toBeInTheDocument();
    unmount();
    urlTab = 'discover';
    render(<ProductsScreen />);
    expect(screen.getByTestId('overview-panel')).toBeInTheDocument();
  });

  it('enables only the active tab query group', () => {
    urlTab = 'opportunities';
    render(<ProductsScreen />);
    expect(enabledCalls.opportunities).toHaveBeenLastCalledWith(true);
    expect(enabledCalls.overview).toHaveBeenLastCalledWith(false);
    expect(enabledCalls.catalog).toHaveBeenLastCalledWith(false);
    expect(enabledCalls.visibility).toHaveBeenLastCalledWith(false);
    expect(enabledCalls.competitors).toHaveBeenLastCalledWith(false);
  });
});
