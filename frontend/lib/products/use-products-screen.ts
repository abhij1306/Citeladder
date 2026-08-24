'use client';

import { useEffect, useMemo, useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { commerceApi } from '@/lib/api/commerce';
import { opportunitiesApi } from '@/lib/api/opportunities';
import { productsApi } from '@/lib/api/products';
import { promptsApi } from '@/lib/api/prompts';
import { topicsApi } from '@/lib/api/topics';
import { queryKeys } from '@/lib/api/query-keys';
import { runsApi } from '@/lib/api/runs';
import {
  catalogCategories,
  categoryIdentity,
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
  const productsQuery = useQuery({
    queryKey: queryKeys.products.list(projectId ?? ''),
    queryFn: ({ signal }) => productsApi.list(projectId!, { signal }),
    enabled: Boolean(projectId) && enabled,
  });
  const commerceAudits = useMemo(
    () => (auditsQuery.data ?? []).filter((audit) => audit.audit_scope === 'commerce'),
    [auditsQuery.data],
  );
  const runOptions = useMemo(() => toRunOptions(commerceAudits), [commerceAudits]);
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
    productsQuery,
    runOptions,
    activeRunId,
    selectRun: setSelectedRunId,
    engine,
    setEngine,
    engineParam,
    visibilityQuery,
  };
}

type PromptSet = Awaited<ReturnType<typeof promptsApi.getPromptSet>>;
type Topic = Awaited<ReturnType<typeof topicsApi.create>>;

function requireCommerceGenerationInputs(
  projectId: string | null,
  missingCategorySkus: string[],
  categories: string[],
): asserts projectId is string {
  if (!projectId) throw new Error('Select a project first.');
  if (missingCategorySkus.length) {
    throw new Error(`Add a category for these SKUs: ${missingCategorySkus.join(', ')}`);
  }
  if (!categories.length) throw new Error('Import categorized products first.');
}

async function ensureCommercePromptSet(
  projectId: string,
  promptSet: PromptSet | undefined,
): Promise<PromptSet> {
  if (promptSet) return promptSet;
  return promptsApi.createPromptSet({
    project_id: projectId,
    name: 'Commerce Product Visibility',
    description: 'Category-level product discovery and comparison prompts.',
  });
}

async function ensureCategoryTopic(
  projectId: string,
  topics: Topic[],
  category: string,
): Promise<Topic> {
  const existing = topics.find(
    (item) => categoryIdentity(item.name) === categoryIdentity(category),
  );
  if (existing) return existing;
  const created = await topicsApi.create(projectId, {
    name: category,
    description: 'Uploaded catalog category',
  });
  topics.push(created);
  return created;
}

async function removeCategoryPrompts(promptSetId: string, topicId: string) {
  const current = await promptsApi.getPromptSet(promptSetId);
  await Promise.all(
    current.prompts
      .filter((prompt) => prompt.cohort === 'commerce' && prompt.topic_id === topicId)
      .map((prompt) => promptsApi.deletePrompt(prompt.id)),
  );
}

async function generateCommercePortfolio({
  projectId,
  missingCategorySkus,
  categories,
  commercePromptSet,
  availableTopics,
  regenerate,
}: {
  projectId: string | null;
  missingCategorySkus: string[];
  categories: string[];
  commercePromptSet: PromptSet | undefined;
  availableTopics: Topic[];
  regenerate: boolean;
}) {
  requireCommerceGenerationInputs(projectId, missingCategorySkus, categories);
  const promptSet = await ensureCommercePromptSet(projectId, commercePromptSet);
  const topics = [...availableTopics];
  for (const category of categories) {
    const topic = await ensureCategoryTopic(projectId, topics, category);
    if (regenerate) await removeCategoryPrompts(promptSet.id, topic.id);
    await promptsApi.generate(promptSet.id, {
      count: 2,
      topic_id: topic.id,
      intents: ['discovery', 'comparison'],
      cohort: 'commerce',
    });
  }
  return promptsApi.getPromptSet(promptSet.id);
}

function useCommerceMeasurementQueries(projectId: string | null, enabled: boolean) {
  const queryEnabled = Boolean(projectId) && enabled;
  const productsQuery = useQuery({
    queryKey: queryKeys.products.list(projectId ?? ''),
    queryFn: ({ signal }) => productsApi.list(projectId!, { signal }),
    enabled: queryEnabled,
  });
  const visibilityQuery = useQuery({
    queryKey: queryKeys.products.visibility(projectId ?? ''),
    queryFn: ({ signal }) => productsApi.getProductVisibility(projectId!, undefined, { signal }),
    enabled: queryEnabled,
  });
  const opportunitiesQuery = useQuery({
    queryKey: queryKeys.opportunities.list(projectId ?? '', { type: 'commerce', limit: 5 }),
    queryFn: ({ signal }) =>
      opportunitiesApi.list(projectId!, { type: 'commerce', limit: 5 }, { signal }),
    enabled: queryEnabled,
  });
  return { productsQuery, visibilityQuery, opportunitiesQuery };
}

function useCommerceSetupQueries(projectId: string | null, enabled: boolean) {
  const queryEnabled = Boolean(projectId) && enabled;
  const promptSetsQuery = useQuery({
    queryKey: queryKeys.prompts.sets(projectId ?? ''),
    queryFn: ({ signal }) => promptsApi.listPromptSets(projectId!, { signal }),
    enabled: queryEnabled,
  });
  const topicsQuery = useQuery({
    queryKey: queryKeys.topics.list(projectId ?? ''),
    queryFn: ({ signal }) => topicsApi.list(projectId!, { signal }),
    enabled: queryEnabled,
  });
  const auditsQuery = useQuery({
    queryKey: queryKeys.runs.list({ project_id: projectId ?? '' }),
    queryFn: ({ signal }) => runsApi.listAudits({ project_id: projectId! }, { signal }),
    enabled: queryEnabled,
  });
  return { promptSetsQuery, topicsQuery, auditsQuery };
}

function uncategorizedSkus(products: Awaited<ReturnType<typeof productsApi.list>>) {
  return products
    .filter((product) => !String(product.attributes.category ?? '').trim())
    .map((product) => product.sku);
}

export function useCommerceOverview(projectId: string | null, enabled = true) {
  const queryClient = useQueryClient();
  const { productsQuery, visibilityQuery, opportunitiesQuery } = useCommerceMeasurementQueries(
    projectId,
    enabled,
  );
  const { promptSetsQuery, topicsQuery, auditsQuery } = useCommerceSetupQueries(projectId, enabled);
  const categories = useMemo(
    () => catalogCategories(productsQuery.data ?? []),
    [productsQuery.data],
  );
  const missingCategorySkus = useMemo(
    () => uncategorizedSkus(productsQuery.data ?? []),
    [productsQuery.data],
  );
  const commercePromptSet = (promptSetsQuery.data ?? []).find(
    (set) => set.name === 'Commerce Product Visibility',
  );
  const generatePromptsMutation = useMutation({
    mutationFn: ({ regenerate = false }: { regenerate?: boolean } = {}) =>
      generateCommercePortfolio({
        projectId,
        missingCategorySkus,
        categories,
        commercePromptSet,
        availableTopics: topicsQuery.data ?? [],
        regenerate,
      }),
    onSuccess: async () => {
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: queryKeys.prompts.sets(projectId ?? '') }),
        queryClient.invalidateQueries({ queryKey: queryKeys.topics.list(projectId ?? '') }),
      ]);
    },
  });
  const commerceAudits = (auditsQuery.data ?? []).filter(
    (audit) => audit.audit_scope === 'commerce',
  );
  return {
    productsQuery,
    visibilityQuery,
    opportunitiesQuery,
    promptSetsQuery,
    topicsQuery,
    auditsQuery,
    categories,
    missingCategorySkus,
    commercePromptSet,
    commerceAudits,
    generatePromptsMutation,
  };
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
