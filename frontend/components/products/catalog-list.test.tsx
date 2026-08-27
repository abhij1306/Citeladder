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
      products: [{ id: PRODUCT_ID, name: 'TempPro TP620', canonical_url: 'https://x.test/p' }],
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

    fireEvent.click(screen.getByRole('button', { name: /Instant-Read Thermometers/ }));
    expect(onSelect).toHaveBeenCalledWith({ kind: 'category', id: CATEGORY_ID });
    expect(onToggle).not.toHaveBeenCalled();

    // Bulk selection must not move the reader off the target they are reading.
    fireEvent.click(screen.getByRole('checkbox', { name: /Select Instant-Read Thermometers/ }));
    expect(onToggle).toHaveBeenCalledWith(`category:${CATEGORY_ID}`);
    expect(onSelect).toHaveBeenCalledTimes(1);
  });

  it('filters both groups by the search box', () => {
    renderWithProviders(
      <CatalogList query={query()} checkedKeys={new Set()} onSelect={vi.fn()} onToggle={vi.fn()} />,
    );
    fireEvent.change(screen.getByRole('textbox', { name: 'Search the catalog' }), {
      target: { value: 'temppro' },
    });

    expect(screen.getByRole('button', { name: /TempPro TP620/ })).toBeInTheDocument();
    expect(
      screen.queryByRole('button', { name: /Instant-Read Thermometers/ }),
    ).not.toBeInTheDocument();
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
  });

  it('is empty while the catalog has not loaded', () => {
    expect(catalogEntries(query({ data: undefined }))).toEqual({
      categories: [],
      products: [],
    });
  });
});
