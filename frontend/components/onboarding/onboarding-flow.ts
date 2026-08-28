'use client';

import { zodResolver } from '@hookform/resolvers/zod';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useRouter, useSearchParams } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';

import { brandDiscoveriesApi, type DiscoveryProfile } from '@/lib/api/brand-discoveries';
import { projectsApi } from '@/lib/api/projects';
import { queryKeys } from '@/lib/api/query-keys';
import {
  brandStepSchema,
  emptyBrandStep,
  normalizeWebsiteUrl,
  type BrandStepValues,
  type ReviewCompetitor,
  type ReviewDomain,
} from '@/lib/onboarding/forms';
import { useBrandDiscovery } from '@/lib/onboarding/use-brand-discovery';
import { useProjectContext } from '@/lib/project/project-context';

import { hasConfirmedIcp } from './icp-confirmation';

export type OnboardingStep = 0 | 1 | 2;

const RETRYABLE_COMPLETION_ERRORS = new Set(['occupancy_limit_exceeded', 'occupancy_unresolved']);

function withBrandKnowledgeDefaults(profile: DiscoveryProfile): DiscoveryProfile {
  const category = profile.category.trim();
  const products = profile.products_services.filter((item) => item.trim());
  return {
    ...profile,
    positioning: profile.positioning.trim() || category,
    target_audience: profile.target_audience.trim() || `Buyers searching for ${category}`,
    products_services: products.length > 0 ? products : [category],
  };
}

function selectedDomains(domains: ReviewDomain[]): string[] {
  return domains.flatMap((item) => (item.selected ? [item.domain] : []));
}

function selectedCompetitors(competitors: ReviewCompetitor[]) {
  return competitors.flatMap((item) =>
    item.selected && item.name.trim()
      ? [{ name: item.name.trim(), aliases: item.aliases, domains: item.domains }]
      : [],
  );
}

function stepQueryValue(step: OnboardingStep): 'brand' | 'discovery' | 'review' {
  return ['brand', 'discovery', 'review'][step] as 'brand' | 'discovery' | 'review';
}

function persistedBrand(input: Record<string, unknown>): BrandStepValues {
  const text = (key: string, fallback = '') =>
    typeof input[key] === 'string' ? (input[key] as string) : fallback;
  return {
    brand_name: text('brand_name'),
    website_url: text('website_url'),
    industry: text('industry'),
    subindustry: text('subindustry'),
    primary_market: text('primary_market', 'US'),
    language_code: text('language_code', 'en'),
  };
}

export function useOnboardingFlow() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { setActiveProjectId } = useProjectContext();
  const isAdditional = searchParams?.get('new') === '1';
  const initialDiscoveryId = searchParams?.get('discovery') ?? null;
  const [step, setStep] = useState<OnboardingStep>(() =>
    initialDiscoveryId && searchParams?.get('step') === 'review' ? 2 : initialDiscoveryId ? 1 : 0,
  );
  const [resumeDiscoveryId, setResumeDiscoveryId] = useState<string | null>(initialDiscoveryId);
  const [brand, setBrand] = useState<BrandStepValues | null>(null);
  const [domains, setDomains] = useState<ReviewDomain[]>([]);
  const [competitors, setCompetitors] = useState<ReviewCompetitor[]>([]);
  const [profile, setProfile] = useState<DiscoveryProfile | null>(null);
  const form = useForm<BrandStepValues>({
    resolver: zodResolver(brandStepSchema),
    defaultValues: emptyBrandStep,
  });
  const discovery = useBrandDiscovery(
    step >= 1 && brand
      ? {
          brand_name: brand.brand_name.trim(),
          website_url: normalizeWebsiteUrl(brand.website_url),
          industry: brand.industry,
          subindustry: brand.subindustry,
          primary_market: brand.primary_market,
          language_code: brand.language_code,
        }
      : null,
    resumeDiscoveryId,
  );
  const catalog = useQuery({
    queryKey: ['brand-discovery-catalog'],
    queryFn: ({ signal }) => brandDiscoveriesApi.catalog({ signal }),
    staleTime: Number.POSITIVE_INFINITY,
  });
  const maximumCompetitors = catalog.data?.maximum_competitors;
  const discoveryState = discovery.discovery;
  const completionRetryable =
    discoveryState?.status === 'failed' &&
    RETRYABLE_COMPLETION_ERRORS.has(discoveryState.error_code);

  useEffect(() => {
    if (!brand && discoveryState) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- hydrate the persisted draft once.
      setBrand(persistedBrand(discoveryState.input_data));
    }
  }, [brand, discoveryState]);

  useEffect(() => {
    const discoveryId = discoveryState?.id ?? resumeDiscoveryId;
    if (!discoveryId) return;
    if (resumeDiscoveryId !== discoveryId) {
      // eslint-disable-next-line react-hooks/set-state-in-effect -- mirror the persisted discovery id.
      setResumeDiscoveryId(discoveryId);
    }
    const params = new URLSearchParams(searchParams?.toString() ?? '');
    params.set('discovery', discoveryId);
    params.set('step', stepQueryValue(step));
    const next = params.toString();
    if (next !== searchParams?.toString()) router.replace(`/onboarding?${next}`, { scroll: false });
  }, [discoveryState?.id, resumeDiscoveryId, router, searchParams, step]);

  useEffect(() => {
    if (discoveryState?.status !== 'ready' && !completionRetryable) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- seed an editable persisted draft.
    setDomains((current) =>
      current.length
        ? current
        : discoveryState.domains.map((domain, index) => ({
            id: `domain:${index}:${domain}`,
            domain,
            selected: true,
          })),
    );
    setProfile((current) => current ?? discoveryState.profile);
  }, [completionRetryable, discoveryState]);

  useEffect(() => {
    if (
      maximumCompetitors === undefined ||
      (discoveryState?.status !== 'ready' && !completionRetryable)
    )
      return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- seed an editable persisted draft.
    setCompetitors((current) =>
      current.length
        ? current
        : discoveryState.competitors.map((competitor, index) => ({
            ...competitor,
            id: `competitor:${index}:${competitor.name}`,
            selected: index < maximumCompetitors,
          })),
    );
  }, [completionRetryable, discoveryState, maximumCompetitors]);

  const openProject = useCallback(
    async (projectId: string) => {
      setActiveProjectId(projectId);
      void projectsApi
        .refreshProjectLogos(projectId)
        .then(() => queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() }))
        .catch(() => undefined);
      await queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() });
      router.replace('/projects');
    },
    [queryClient, router, setActiveProjectId],
  );

  const complete = useMutation({
    mutationFn: async () => {
      if (!brand || !discoveryState || !hasConfirmedIcp(profile)) {
        throw new Error('Confirm the required ICP fields before creating the project.');
      }
      return brandDiscoveriesApi.complete(
        discoveryState.id,
        {
          name: brand.brand_name.trim(),
          profile: withBrandKnowledgeDefaults(profile),
          domains: selectedDomains(domains),
          competitors: selectedCompetitors(competitors),
        },
        `complete:${discoveryState.id}`,
      );
    },
    // The request only ACCEPTS the completion; the portfolio is generated on a
    // worker because it takes minutes and the client abandons a request after
    // 30s. A replayed completion already carries its project id and skips
    // straight through; otherwise the discovery poll below finishes the job.
    onSuccess: async (result) => {
      if (result.project_id) await openProject(result.project_id);
      else await queryClient.invalidateQueries({ queryKey: ['brand-discovery'] });
    },
  });

  const completedProjectId =
    discoveryState?.status === 'project_created' ? discoveryState.project_id : null;
  const completionFailed = discoveryState?.status === 'failed' && !completionRetryable;
  useEffect(() => {
    if (!completedProjectId) return;
    void openProject(completedProjectId);
  }, [completedProjectId, openProject]);

  const submitBrand = form.handleSubmit((values) => {
    const rediscovers =
      discoveryState?.status === 'failed' ||
      (brand !== null && JSON.stringify(brand) !== JSON.stringify(values));
    if (rediscovers) {
      setDomains([]);
      setCompetitors([]);
      setProfile(null);
      setResumeDiscoveryId(null);
    }
    setBrand(values);
    setStep(1);
  });

  const toggle = useCallback(
    <T extends { selected: boolean }>(setter: React.Dispatch<React.SetStateAction<T[]>>) =>
      (index: number) =>
        setter((current) =>
          current.map((item, itemIndex) =>
            itemIndex === index ? { ...item, selected: !item.selected } : item,
          ),
        ),
    [],
  );

  return {
    brand,
    catalog,
    competitors,
    complete,
    completionFailed,
    completionRetryable,
    // True from the click until the worker lands the project. The request
    // itself resolves in milliseconds now, so `complete.isPending` alone would
    // re-enable the button the moment the job was ACCEPTED -- inviting the
    // very second click this whole change exists to remove. `isSuccess`
    // without a project id is "accepted, still generating", and it bridges the
    // gap before the discovery poll first reports `completing`; the polled
    // status is what holds it across a RELOAD, where the mutation is fresh and
    // knows nothing about the job already running.
    //
    isCompleting:
      !completionFailed &&
      (complete.isPending ||
        (complete.isSuccess && discoveryState?.status !== 'failed' && !completedProjectId) ||
        discoveryState?.status === 'completing'),
    discovery,
    domains,
    form,
    hasSelectedDomain: domains.some((item) => item.selected),
    isAdditional,
    maximumCompetitors,
    profile,
    setCompetitors,
    setDomains,
    setProfile,
    setStep,
    step,
    submitBrand,
    toggle,
  };
}
