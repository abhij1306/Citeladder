import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import { ProductsScreen } from './products-screen';

// The screen's tab state is URL-synced (?tab=); stub next/navigation with a
// controllable search-param + a shallow-history spy.
const replaceStateSpy = vi.fn((_data: unknown, _unused: string, url: string) => {
  urlTab = new URL(url, 'http://localhost').searchParams.get('tab');
});
let urlTab: string | null = null;
vi.stubGlobal('history', { ...window.history, replaceState: replaceStateSpy });

vi.mock('next/navigation', () => ({
  usePathname: () => '/products',
  useSearchParams: () => new URLSearchParams(urlTab ? `tab=${urlTab}` : ''),
}));

// Isolate the tab orchestration: the panels are stubbed (their own tests
// cover their contents); the project context resolves a fixed project.
vi.mock('@/lib/project/project-context', () => ({
  useProjectContext: () => ({
    activeProject: { id: '11111111-1111-4111-8111-111111111111' },
    isLoading: false,
  }),
}));

vi.mock('@/lib/products/use-products-screen', async (importOriginal) => {
  const original = await importOriginal<typeof import('@/lib/products/use-products-screen')>();
  return {
    ...original,
    useCatalogQueries: () => ({
      productsQuery: { isLoading: false },
      catalogHealthQuery: { isLoading: false },
    }),
    useProductVisibilityQueries: () => ({
      auditsQuery: { isLoading: false },
      runOptions: [],
      activeRunId: null,
      selectRun: vi.fn(),
      engine: 'all',
      setEngine: vi.fn(),
      engineParam: undefined,
      visibilityQuery: { isLoading: true },
    }),
    useCommerceDiscovery: () => ({
      runsQuery: { isLoading: false, data: [] },
      candidatesQuery: { isLoading: false, data: [] },
      previewMutation: {},
      createMutation: {},
      decisionMutation: {},
      setSelectedRunId: vi.fn(),
    }),
    useMarketIntelligence: () => ({
      comparisonsQuery: { isLoading: false, data: [] },
      createMutation: {},
    }),
  };
});

vi.mock('./catalog-panel', () => ({
  CatalogPanel: () => <div data-testid="catalog-panel">Catalog panel</div>,
}));

vi.mock('./product-visibility-panel', () => ({
  ProductVisibilityPanel: () => <div data-testid="visibility-panel">Visibility panel</div>,
}));

describe('ProductsScreen tabs', () => {
  beforeEach(() => {
    replaceStateSpy.mockClear();
    urlTab = null;
  });

  it('defaults to Discover and renders exactly one panel', () => {
    render(<ProductsScreen />);

    expect(screen.getByRole('tab', { name: 'Discover' })).toHaveAttribute('aria-selected', 'true');
    expect(screen.getByRole('tab', { name: 'Catalog' })).toHaveAttribute('aria-selected', 'false');
    expect(screen.getByRole('tab', { name: 'AI Conversations' })).toHaveAttribute(
      'aria-selected',
      'false',
    );
    expect(screen.getByRole('tab', { name: 'Market Intelligence' })).toHaveAttribute(
      'aria-selected',
      'false',
    );
    expect(screen.getByTestId('commerce-discover-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('catalog-panel')).not.toBeInTheDocument();
    expect(screen.queryByTestId('visibility-panel')).not.toBeInTheDocument();
    expect(screen.getAllByRole('tabpanel')).toHaveLength(1);
  });

  it('switches panels on tab click and mirrors the tab into ?tab=', async () => {
    const user = userEvent.setup();
    render(<ProductsScreen />);

    await user.click(screen.getByRole('tab', { name: 'AI Conversations' }));
    expect(screen.getByTestId('visibility-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('commerce-discover-panel')).not.toBeInTheDocument();
    expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/products?tab=conversations');

    await user.click(screen.getByRole('tab', { name: 'Catalog' }));
    expect(screen.getByTestId('catalog-panel')).toBeInTheDocument();
    expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/products?tab=catalog');
  });

  it('reads the initial tab from ?tab= (invalid values fall back to Discover)', () => {
    urlTab = 'conversations';
    render(<ProductsScreen />);
    expect(screen.getByTestId('visibility-panel')).toBeInTheDocument();
  });

  it('switches to Market Intelligence and mirrors it into ?tab=', async () => {
    const user = userEvent.setup();
    render(<ProductsScreen />);

    await user.click(screen.getByRole('tab', { name: 'Market Intelligence' }));
    expect(screen.getByTestId('commerce-market-panel')).toBeInTheDocument();
    expect(screen.queryByTestId('catalog-panel')).not.toBeInTheDocument();
    expect(replaceStateSpy).toHaveBeenCalledWith(null, '', '/products?tab=market_intelligence');
  });

  it('reads the Market Intelligence tab from ?tab=market_intelligence', () => {
    urlTab = 'market_intelligence';
    render(<ProductsScreen />);
    expect(screen.getByTestId('commerce-market-panel')).toBeInTheDocument();
  });

  it('supports ArrowRight keyboard navigation between tabs', async () => {
    const user = userEvent.setup();
    render(<ProductsScreen />);

    screen.getByRole('tab', { name: 'Discover' }).focus();
    await user.keyboard('{ArrowRight}');
    expect(screen.getByRole('tab', { name: 'Catalog' })).toHaveFocus();
    expect(screen.getByTestId('catalog-panel')).toBeInTheDocument();
  });
});
