import { describe, expect, it } from 'vitest';

import { normalizeProductsTab, PRODUCTS_TABS } from './catalog';

describe('Commerce tabs', () => {
  it('ships exactly the four replacement views and defaults to Catalog', () => {
    expect(PRODUCTS_TABS.map((tab) => tab.id)).toEqual([
      'catalog',
      'competitors',
      'buyer-prompts',
      'ai-shelf',
    ]);
    expect(normalizeProductsTab(null)).toBe('catalog');
    expect(normalizeProductsTab('overview')).toBe('catalog');
    expect(normalizeProductsTab('ai-shelf')).toBe('ai-shelf');
  });
});
