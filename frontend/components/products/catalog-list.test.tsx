import { fireEvent, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { renderWithProviders } from '@/test/render';

import { CatalogList, catalogEntries } from './catalog-list';

const CATEGORY_ID = '22222222-2222-4222-8222-222222222222';
const PRODUCT_ID = '33333333-3333-4333-8333-333333333333';

const query = (overrides: Record<string, unknown> = {}) =>
  ({
    isPending: false,
    isError: false,
    data: {
      categories: [{ id: CATEGORY_ID, name: 'Instant-Read Thermometers', product_count: 2 }],
      products: [
        {
          id: PRODUCT_ID,
          name: 'TempPro TP620',
          canonical_url: 'https://x.test/p',
          category_ids: [CATEGORY_ID],
        },
      ],
      projection_tasks: {},
    },
    ...overrides,
  }) as never;

describe('CatalogList', () => {
  it('is the target picker: a row click selects, a checkbox does not', () => {
    const onSelect = vi.fn();
    const onToggle = vi.fn();
    renderWithProviders(
      <CatalogList
        query={query()}
        checkedKeys={new Set()}
        onSelect={onSelect}
        onToggle={onToggle}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Instant-Read Thermometers' }));
    expect(onSelect).toHaveBeenCalledWith({ kind: 'category', id: CATEGORY_ID });
    expect(onToggle).not.toHaveBeenCalled();

    // Bulk selection must not move the reader off the target they are reading.
    fireEvent.click(screen.getByRole('checkbox', { name: /Select Instant-Read Thermometers/ }));
    expect(onToggle).toHaveBeenCalledWith([`category:${CATEGORY_ID}`, `product:${PRODUCT_ID}`]);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('announces partial category selection as indeterminate', () => {
    renderWithProviders(
      <CatalogList
        query={query()}
        checkedKeys={new Set([`product:${PRODUCT_ID}`])}
        onSelect={vi.fn()}
        onToggle={vi.fn()}
      />,
    );
    expect(
      screen.getByRole('checkbox', { name: /Select Instant-Read Thermometers/ }),
    ).toHaveAttribute('data-state', 'indeterminate');
  });

  it('keeps categories collapsed until their plus control is used', () => {
    const onToggle = vi.fn();
    renderWithProviders(
      <CatalogList
        query={query()}
        checkedKeys={new Set()}
        onSelect={vi.fn()}
        onToggle={onToggle}
      />,
    );

    expect(screen.queryByRole('button', { name: 'TempPro TP620' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Instant-Read Thermometers' })).toHaveTextContent(
      '2',
    );
    const expand = screen.getByRole('button', { name: 'Expand Instant-Read Thermometers' });
    expect(expand).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(expand);
    expect(
      screen.getByRole('button', { name: 'Collapse Instant-Read Thermometers' }),
    ).toHaveAttribute('aria-expanded', 'true');
    expect(
      screen.getByRole('list', { name: 'Instant-Read Thermometers products' }),
    ).toContainElement(screen.getByRole('button', { name: 'TempPro TP620' }));

    fireEvent.click(screen.getByRole('button', { name: 'Collapse Instant-Read Thermometers' }));
    expect(screen.queryByRole('button', { name: 'TempPro TP620' })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole('checkbox', { name: /Select Instant-Read Thermometers/ }));
    expect(onToggle).toHaveBeenCalledWith([`category:${CATEGORY_ID}`, `product:${PRODUCT_ID}`]);
    expect(screen.queryByText(/^Products$/)).not.toBeInTheDocument();
  });

  it('does not render an expander for a category without products', () => {
    renderWithProviders(
      <CatalogList
        query={query({
          data: {
            categories: [{ id: CATEGORY_ID, name: 'Empty category', product_count: 0 }],
            products: [],
            projection_tasks: {},
          },
        })}
        checkedKeys={new Set()}
        onSelect={vi.fn()}
        onToggle={vi.fn()}
      />,
    );

    expect(screen.getByRole('button', { name: 'Empty category' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Expand Empty category/ })).not.toBeInTheDocument();
  });

  it('filters both groups by the search box', () => {
    renderWithProviders(
      <CatalogList query={query()} checkedKeys={new Set()} onSelect={vi.fn()} onToggle={vi.fn()} />,
    );
    fireEvent.change(screen.getByRole('searchbox', { name: 'Search the catalog' }), {
      target: { value: 'temppro' },
    });

    expect(screen.getByRole('button', { name: 'TempPro TP620' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Instant-Read Thermometers' })).toBeInTheDocument();
  });

  it('keeps the search controls sticky inside the catalog scroller', () => {
    renderWithProviders(
      <CatalogList query={query()} checkedKeys={new Set()} onSelect={vi.fn()} onToggle={vi.fn()} />,
    );

    const controls = screen.getByTestId('catalog-search-controls');
    expect(controls).toHaveClass('sticky', 'top-0', 'z-20', 'bg-panel');
    expect(controls.parentElement?.firstElementChild).toBe(controls);
  });

  it('explains an empty catalog rather than showing an empty list', () => {
    renderWithProviders(
      <CatalogList
        query={query({ data: { categories: [], products: [], projection_tasks: {} } })}
        checkedKeys={new Set()}
        onSelect={vi.fn()}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText(/Run a Site Health crawl or import a CSV/)).toBeInTheDocument();
  });

  it('reports a read failure instead of an empty list', () => {
    renderWithProviders(
      <CatalogList
        query={query({ isError: true, data: undefined })}
        checkedKeys={new Set()}
        onSelect={vi.fn()}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByText('The catalog could not be loaded.')).toBeInTheDocument();
  });
});

describe('catalogEntries', () => {
  it('keys every entry the way the URL spells it', () => {
    const { categories, products } = catalogEntries(query());
    expect(categories[0].key).toBe(`category:${CATEGORY_ID}`);
    expect(products[0].key).toBe(`product:${PRODUCT_ID}`);
    expect(categories[0].children?.[0].key).toBe(`product:${PRODUCT_ID}`);
  });

  it('is empty while the catalog has not loaded', () => {
    expect(catalogEntries(query({ data: undefined }))).toEqual({
      categories: [],
      products: [],
    });
  });
});
