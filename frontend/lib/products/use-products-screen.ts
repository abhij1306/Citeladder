'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';

import { commerceApi } from '@/lib/api/commerce';
import { queryKeys } from '@/lib/api/query-keys';
import { normalizeProductsTab, type ProductsTab } from './catalog';

export function useProductsTab() {
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const activeTab = normalizeProductsTab(searchParams?.get('tab'));
  const selectTab = (tab: ProductsTab) => {
    const params = new URLSearchParams(searchParams?.toString() ?? '');
    params.set('tab', tab);
    router.replace(`${pathname}?${params}`, { scroll: false });
  };
  return { activeTab, selectTab };
}

export function useCommerceQueries(projectId: string, tab: ProductsTab) {
  const catalog = useQuery({
    queryKey: queryKeys.commerce.catalog(projectId),
    queryFn: ({ signal }) => commerceApi.catalog(projectId, { signal }),
    enabled: tab === 'catalog' || tab === 'competitors' || tab === 'buyer-prompts',
  });
  const competitors = useQuery({
    queryKey: queryKeys.commerce.competitors(projectId),
    queryFn: ({ signal }) => commerceApi.competitors(projectId, { signal }),
    enabled: tab === 'competitors',
  });
  const buyerPrompts = useQuery({
    queryKey: queryKeys.commerce.buyerPrompts(projectId),
    queryFn: ({ signal }) => commerceApi.buyerPrompts(projectId, { signal }),
    enabled: tab === 'buyer-prompts',
  });
  const shelf = useQuery({
    queryKey: queryKeys.commerce.shelf(projectId),
    queryFn: ({ signal }) => commerceApi.shelf(projectId, undefined, { signal }),
    enabled: tab === 'ai-shelf',
  });
  return { catalog, competitors, buyerPrompts, shelf };
}
