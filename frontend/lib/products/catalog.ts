export const PRODUCTS_TABS = [
  { id: 'catalog', label: 'Catalog' },
  { id: 'competitors', label: 'Competitors' },
  { id: 'buyer-prompts', label: 'Buyer Prompts' },
  { id: 'ai-shelf', label: 'AI Shelf' },
] as const;

export type ProductsTab = (typeof PRODUCTS_TABS)[number]['id'];

export function normalizeProductsTab(value: string | null): ProductsTab {
  return PRODUCTS_TABS.some((tab) => tab.id === value) ? (value as ProductsTab) : 'catalog';
}
