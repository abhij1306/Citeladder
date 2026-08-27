'use client';

import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';

import { commerceApi } from '@/lib/api/commerce';
import { queryKeys } from '@/lib/api/query-keys';
import type { CommerceTarget } from '@/lib/api/schemas/commerce-suite';
import { catalogPollingInterval } from './catalog-polling';
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

export function useCommerceQueries(
  projectId: string,
  tab: ProductsTab,
  shelfTarget?: CommerceTarget,
) {
  const catalog = useQuery({
    queryKey: queryKeys.commerce.catalog(projectId),
    queryFn: ({ signal }) => commerceApi.catalog(projectId, { signal }),
    enabled:
      Boolean(projectId) &&
      (tab === 'catalog' || tab === 'competitors' || tab === 'buyer-prompts' || tab === 'ai-shelf'),
    refetchInterval: (query) =>
      tab === 'catalog' ? catalogPollingInterval(query.state.data?.projection_tasks) : false,
  });
  const competitors = useQuery({
    queryKey: queryKeys.commerce.competitors(projectId),
    queryFn: ({ signal }) => commerceApi.competitors(projectId, { signal }),
    // No interval: the active-discoveries query owns the in-flight signal and
    // invalidates this list when the last discovery terminalizes.
    enabled: Boolean(projectId) && tab === 'competitors',
  });
  const buyerPrompts = useQuery({
    queryKey: queryKeys.commerce.buyerPrompts(projectId),
    queryFn: ({ signal }) => commerceApi.buyerPrompts(projectId, { signal }),
    enabled: Boolean(projectId) && tab === 'buyer-prompts',
  });
  const shelf = useQuery({
    queryKey: queryKeys.commerce.shelf(projectId, shelfTarget),
    queryFn: ({ signal }) => commerceApi.shelf(projectId, shelfTarget!, undefined, { signal }),
    enabled: Boolean(projectId) && tab === 'ai-shelf' && Boolean(shelfTarget),
  });
  return { catalog, competitors, buyerPrompts, shelf };
}
