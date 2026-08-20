'use client';

import { useEffect, useMemo, useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { keepPreviousData, useQuery } from '@tanstack/react-query';

import { commerceApi } from '@/lib/api/commerce';
import { opportunitiesApi } from '@/lib/api/opportunities';
import { productsApi } from '@/lib/api/products';
import { queryKeys } from '@/lib/api/query-keys';
import { runsApi } from '@/lib/api/runs';
import {
  normalizeProductsTab,
  type ProductEngineFilter,
  type ProductsTab,
} from '@/lib/products/catalog';
import { toRunOptions } from '@/lib/visibility/dashboard';

export function useProductsTab() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const urlTab = normalizeProductsTab(searchParams?.get('tab'));
  const [activeTab, setActiveTab] = useState<ProductsTab>(urlTab);

  useEffect(() => {
    // URL navigation is the source of truth.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setActiveTab(urlTab);
  }, [urlTab]);

  function selectTab(tab: ProductsTab) {
    setActiveTab(tab);
    const params = new URLSearchParams(searchParams?.toString() ?? '');
    params.set('tab', tab);
    window.history.replaceState(null, '', `${pathname}?${params.toString()}`);
  }

  return { activeTab, selectTab };
}

export function useCatalogQueries(projectId: string | null, enabled = true) {
  const productsQuery = useQuery({
    queryKey: queryKeys.products.list(projectId ?? ''),
    queryFn: ({ signal }) => productsApi.list(projectId!, { signal }),
    enabled: Boolean(projectId) && enabled,
  });
  const catalogHealthQuery = useQuery({
    queryKey: queryKeys.commerce.catalogHealth(projectId ?? ''),
    queryFn: ({ signal }) => commerceApi.getCatalogHealth(projectId!, { signal }),
    enabled: Boolean(projectId) && enabled,
  });
  return { productsQuery, catalogHealthQuery };
}

export function useProductVisibilityQueries(projectId: string | null, enabled = true) {
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [engine, setEngine] = useState<ProductEngineFilter>('all');
  const auditsQuery = useQuery({
    queryKey: queryKeys.runs.list({ project_id: projectId ?? '' }),
    queryFn: ({ signal }) => runsApi.listAudits({ project_id: projectId! }, { signal }),
    enabled: Boolean(projectId) && enabled,
  });
  const runOptions = useMemo(() => toRunOptions(auditsQuery.data ?? []), [auditsQuery.data]);
  const activeRunId = useMemo(
    () =>
      selectedRunId && runOptions.some((run) => run.id === selectedRunId) ? selectedRunId : null,
    [runOptions, selectedRunId],
  );
  const engineParam = engine === 'all' ? undefined : engine;
  const visibilityQuery = useQuery({
    queryKey: queryKeys.products.visibility(projectId ?? '', activeRunId ?? undefined, engineParam),
    queryFn: ({ signal }) =>
      productsApi.getProductVisibility(
        projectId!,
        { audit_id: activeRunId ?? undefined, engine: engineParam },
        { signal },
      ),
    enabled: Boolean(projectId) && enabled,
    placeholderData: keepPreviousData,
  });
  return {
    auditsQuery,
    runOptions,
    activeRunId,
    selectRun: setSelectedRunId,
    engine,
    setEngine,
    engineParam,
    visibilityQuery,
  };
}

export function useCommerceOverview(projectId: string | null, enabled = true) {
  const visibilityQuery = useQuery({
    queryKey: queryKeys.products.visibility(projectId ?? ''),
    queryFn: ({ signal }) => productsApi.getProductVisibility(projectId!, undefined, { signal }),
    enabled: Boolean(projectId) && enabled,
  });
  const opportunitiesQuery = useQuery({
    queryKey: queryKeys.opportunities.list(projectId ?? '', { type: 'commerce', limit: 5 }),
    queryFn: ({ signal }) =>
      opportunitiesApi.list(projectId!, { type: 'commerce', limit: 5 }, { signal }),
    enabled: Boolean(projectId) && enabled,
  });
  return { visibilityQuery, opportunitiesQuery };
}

export function useCommerceComparison(projectId: string | null, enabled = true) {
  const comparisonQuery = useQuery({
    queryKey: queryKeys.commerce.comparison(projectId ?? ''),
    queryFn: ({ signal }) => commerceApi.getComparison(projectId!, undefined, { signal }),
    enabled: Boolean(projectId) && enabled,
  });
  return { comparisonQuery };
}

export function useCommerceOpportunities(projectId: string | null, enabled = true) {
  const opportunitiesQuery = useQuery({
    queryKey: queryKeys.opportunities.list(projectId ?? '', { type: 'commerce', limit: 100 }),
    queryFn: ({ signal }) =>
      opportunitiesApi.list(projectId!, { type: 'commerce', limit: 100 }, { signal }),
    enabled: Boolean(projectId) && enabled,
  });
  return { opportunitiesQuery };
}
