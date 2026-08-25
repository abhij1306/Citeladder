'use client';

import { useEffect, useMemo, useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { productsApi } from '@/lib/api/products';
import { promptsApi } from '@/lib/api/prompts';
import { topicsApi } from '@/lib/api/topics';
import { queryKeys } from '@/lib/api/query-keys';
import { runsApi } from '@/lib/api/runs';
import {
  catalogCategories,
  categoryIdentity,
  commercePromptIdsToReplace,
  commercePromptProductName,
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
  return { productsQuery };
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
  setupReady: boolean,
): asserts projectId is string {
  if (!projectId) throw new Error('Select a project first.');
  if (!setupReady) throw new Error('Wait for Commerce setup data to finish loading.');
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
    description: 'Product-named buyer destination and alternatives prompts grouped by category.',
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

function topicPromptsAreComplete(
  prompts: PromptSet['prompts'],
  topicId: string,
  productNames: string[],
) {
  const topicPrompts = prompts.filter(
    (prompt) => prompt.cohort === 'commerce' && prompt.topic_id === topicId,
  );
  return productNames.every((productName) => {
    const intents = new Set(
      topicPrompts
        .filter((prompt) => commercePromptProductName(prompt.text, productNames) === productName)
        .map((prompt) => prompt.intent),
    );
    return intents.has('discovery') && intents.has('comparison');
  });
}

async function generateCommercePortfolio({
  projectId,
  missingCategorySkus,
  categories,
  products,
  commercePromptSet,
  availableTopics,
  regenerate,
  setupReady,
}: {
  projectId: string | null;
  missingCategorySkus: string[];
  categories: string[];
  products: Awaited<ReturnType<typeof productsApi.list>>;
  commercePromptSet: PromptSet | undefined;
  availableTopics: Topic[];
  regenerate: boolean;
  setupReady: boolean;
}) {
  requireCommerceGenerationInputs(projectId, missingCategorySkus, categories, setupReady);
  const promptSet = await ensureCommercePromptSet(projectId, commercePromptSet);
  const topics = [...availableTopics];
  const currentPrompts = (await promptsApi.getPromptSet(promptSet.id)).prompts;
  const replacedPromptIds: string[] = [];
  for (const category of categories) {
    const topic = await ensureCategoryTopic(projectId, topics, category);
    const categoryProducts = products.filter(
      (product) => categoryIdentity(product.attributes.category) === categoryIdentity(category),
    );
    if (
      !regenerate &&
      topicPromptsAreComplete(
        currentPrompts,
        topic.id,
        categoryProducts.map((product) => product.name),
      )
    )
      continue;
    const existingTopicPrompts = currentPrompts.filter(
      (prompt) => prompt.cohort === 'commerce' && prompt.topic_id === topic.id,
    );
    const productNames = categoryProducts.map((product) => product.name);
    const generated = await promptsApi.generate(promptSet.id, {
      count: categoryProducts.length * 2,
      topic_id: topic.id,
      intents: ['discovery', 'comparison'],
      cohort: 'commerce',
    });
    replacedPromptIds.push(
      ...commercePromptIdsToReplace(existingTopicPrompts, generated.generated, productNames),
    );
  }
  await Promise.all(replacedPromptIds.map((promptId) => promptsApi.deletePrompt(promptId)));
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
  return { productsQuery, visibilityQuery };
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
    .filter((product) => !categoryIdentity(product.attributes.category))
    .map((product) => product.sku);
}

export function useCommerceOverview(projectId: string | null, enabled = true) {
  const queryClient = useQueryClient();
  const { productsQuery, visibilityQuery } = useCommerceMeasurementQueries(projectId, enabled);
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
  const setupReady = promptSetsQuery.isSuccess && topicsQuery.isSuccess;
  const generatePromptsMutation = useMutation({
    mutationFn: ({ regenerate = false }: { regenerate?: boolean } = {}) =>
      generateCommercePortfolio({
        projectId,
        missingCategorySkus,
        categories,
        products: productsQuery.data ?? [],
        commercePromptSet,
        availableTopics: topicsQuery.data ?? [],
        regenerate,
        setupReady,
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
    promptSetsQuery,
    topicsQuery,
    auditsQuery,
    categories,
    missingCategorySkus,
    commercePromptSet,
    setupReady,
    commerceAudits,
    generatePromptsMutation,
  };
}
