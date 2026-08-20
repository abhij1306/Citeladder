'use client';

/**
 * State + queries for the `/products` Commerce workspace.
 *
 * `useProductsTab` mirrors the active tab into `?tab=` (Discover is default)
 * so refresh / back / forward preserve it. `useCatalogQueries` loads the
 * catalog + the commerce catalog-health projection. `useProductVisibilityQueries`
 * loads the project's dashboard-ready runs (for the Run selector) and the
 * product visibility projection — defaulting to the latest product audit,
 * sliced by the engine + surface filters via the backend's persisted
 * aggregates. Every hook takes an explicit `enabled` flag so only the ACTIVE
 * tab's queries run.
 */
import { useEffect, useMemo, useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { commerceApi } from '@/lib/api/commerce';
import { queryKeys } from '@/lib/api/query-keys';
import { productsApi } from '@/lib/api/products';
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
    // Intentional URL→state sync (external navigation is the source of truth).
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
    // Only fetch on the Catalog tab — the other tabs never read these.
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
    // Only fetch on the AI Conversations tab — inactive views never read these.
    enabled: Boolean(projectId) && enabled,
  });
  const runOptions = useMemo(() => toRunOptions(auditsQuery.data ?? []), [auditsQuery.data]);

  // An explicit selection that still exists, else the latest (null = the
  // backend resolves the latest product audit itself).
  const activeRunId = useMemo(() => {
    if (selectedRunId && runOptions.some((run) => run.id === selectedRunId)) {
      return selectedRunId;
    }
    return null;
  }, [runOptions, selectedRunId]);

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

/** Durable discovery evidence and candidate review. Acquisition is worker-owned. */
export function useCommerceDiscovery(projectId: string | null, enabled = true) {
  const queryClient = useQueryClient();
  const [selectedRunId, setSelectedRunId] = useState<string | undefined>();
  const runsQuery = useQuery({
    queryKey: queryKeys.commerce.discoveryRuns(projectId ?? ''),
    queryFn: ({ signal }) => commerceApi.listDiscoveryRuns(projectId!, { signal }),
    enabled: Boolean(projectId) && enabled,
  });
  const candidatesQuery = useQuery({
    queryKey: queryKeys.commerce.discoveryCandidates(projectId ?? '', selectedRunId),
    queryFn: ({ signal }) =>
      commerceApi.listDiscoveryCandidates(projectId!, selectedRunId, { signal }),
    enabled: Boolean(projectId) && enabled,
  });
  const refresh = async () => {
    await Promise.all([
      queryClient.invalidateQueries({
        queryKey: queryKeys.commerce.discoveryRuns(projectId ?? ''),
      }),
      queryClient.invalidateQueries({
        queryKey: queryKeys.commerce.discoveryCandidates(projectId ?? ''),
      }),
    ]);
  };
  const previewMutation = useMutation({
    mutationFn: (body: Parameters<typeof commerceApi.previewDiscovery>[1]) =>
      commerceApi.previewDiscovery(projectId!, body),
  });
  const createMutation = useMutation({
    mutationFn: (body: Parameters<typeof commerceApi.createDiscoveryRun>[1]) =>
      commerceApi.createDiscoveryRun(projectId!, body),
    onSuccess: async (run) => {
      setSelectedRunId(run.id);
      await refresh();
    },
  });
  const decisionMutation = useMutation({
    mutationFn: (input: {
      candidateId: string;
      body: Parameters<typeof commerceApi.decideCandidate>[1];
    }) => commerceApi.decideCandidate(input.candidateId, input.body),
    onSuccess: refresh,
  });
  return {
    selectedRunId,
    setSelectedRunId,
    runsQuery,
    candidatesQuery,
    previewMutation,
    createMutation,
    decisionMutation,
  };
}

/** Immutable competitor comparison snapshots and their history. */
export function useMarketIntelligence(projectId: string | null, enabled = true) {
  const queryClient = useQueryClient();
  const comparisonsQuery = useQuery({
    queryKey: queryKeys.commerce.comparisons(projectId ?? ''),
    queryFn: ({ signal }) => commerceApi.listComparisons(projectId!, { signal }),
    enabled: Boolean(projectId) && enabled,
  });
  const createMutation = useMutation({
    mutationFn: (competitorId?: string) => commerceApi.createComparison(projectId!, competitorId),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.commerce.comparisons(projectId ?? '') }),
  });
  return { comparisonsQuery, createMutation };
}
