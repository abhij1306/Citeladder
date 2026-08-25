'use client';

import type { ReactNode } from 'react';

import { PRODUCTS_TABS, type ProductsTab } from '@/lib/products/catalog';

import { NestedTabs } from '@/components/ui/nested-tabs';

/**
 * Accessible three-tab navigation for the Commerce workspace with roving tabindex, `aria-selected`,
 * and Arrow/Home/End keyboard navigation with focus transfer + automatic
 * activation. Only the active panel is rendered, wired to its tab via
 * `aria-controls` / `aria-labelledby`. URL sync (`?tab=`) lives in the
 * parent; this is a controlled view delegating to the shared `NestedTabs`
 * tablist (ids keep the historical `products-tab-*` / `products-panel-*`
 * shape).
 */
export function ProductsTabs({
  activeTab,
  onSelectTab,
  panel,
}: Readonly<{
  activeTab: ProductsTab;
  onSelectTab: (tab: ProductsTab) => void;
  /** The rendered content of the active panel (the parent owns composition). */
  panel: ReactNode;
}>) {
  return (
    <NestedTabs
      tabs={PRODUCTS_TABS}
      activeTab={activeTab}
      onSelectTab={onSelectTab}
      ariaLabel="Commerce views"
      idPrefix="products"
      panel={panel}
    />
  );
}
