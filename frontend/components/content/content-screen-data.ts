import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import {
  type ContentSkillView,
  contentApi,
  type SiteHealthReferenceInput,
} from '@/lib/api/content';
import { demandApi } from '@/lib/api/demand';
import { opportunitiesQueries } from '@/lib/api/opportunities';
import { siteHealthApi } from '@/lib/api/site-health';
import { queryKeys } from '@/lib/api/query-keys';
import { ApiError, httpErrorStatus } from '@/lib/api/errors';
import { buildDemandBrief } from '@/lib/demand/content-brief';
import { useActiveProject } from '@/lib/project/project-context';

/** Map an action failure to its specific user-facing message when possible. */
export function actionErrorMessage(error: unknown): string {
  if (httpErrorStatus(error) === 409) {
    const body = error instanceof ApiError ? error.body : '';
    if (body.includes('provider_not_configured')) {
      return 'Content generation is not configured — a provider API key is missing.';
    }
    if (body.includes('cancel_not_allowed')) {
      return 'This generation already finished, so it can no longer be cancelled.';
    }
    if (body.includes('idempotency_conflict')) {
      return 'A different request was already submitted with this key. Please try again.';
    }
  }
  return 'Something went wrong while generating your content. You can try again.';
}

/** The server-owned skill catalog. Static config, so it never refetches. */
export function useSkillCatalog() {
  return useQuery({
    queryKey: queryKeys.content.skills(),
    queryFn: ({ signal }) => contentApi.listSkills({ signal }),
    staleTime: Infinity,
  });
}

const IDLE_BRIEF = {
  brief: null as ReturnType<typeof buildDemandBrief> | null,
  loading: false,
  notFound: false,
  failed: false,
} as const;

/** Rebuilds a demand brief from the live snapshot identified in the URL. */
export function useDemandBrief(projectId: string, demandSignalId?: string | null) {
  const snapshot = useQuery({
    queryKey: queryKeys.demand.latest(projectId),
    queryFn: ({ signal }) => demandApi.getLatest(projectId, { signal }),
    enabled: Boolean(demandSignalId),
  });
  const activeProject = useActiveProject();
  const signals = snapshot.data?.signals;
  const brandName = activeProject?.brand_name;

  return useMemo(() => {
    if (!demandSignalId) return IDLE_BRIEF;
    if (snapshot.isLoading) return { ...IDLE_BRIEF, loading: true };
    if (snapshot.isError || !signals) return { ...IDLE_BRIEF, failed: true };

    const match = signals.find((item) => item.id === demandSignalId);
    if (!match) return { ...IDLE_BRIEF, notFound: true };
    return {
      ...IDLE_BRIEF,
      brief: buildDemandBrief(match, brandName ? { brand_name: brandName } : null),
    };
  }, [brandName, demandSignalId, signals, snapshot.isError, snapshot.isLoading]);
}

/**
 * What would ground a draft for this project right now, so the composer can
 * say so before Generate rather than after. Cheap enough to refetch on a
 * project switch, stale-tolerant enough not to poll.
 */
export function useContentContextPreview(projectId: string) {
  return useQuery({
    queryKey: queryKeys.content.contextPreview(projectId),
    queryFn: ({ signal }) => contentApi.getContextPreview(projectId, { signal }),
    staleTime: 60_000,
  });
}

export function useSiteHealthHandoff(reference?: SiteHealthReferenceInput) {
  return useQuery({
    queryKey: reference
      ? queryKeys.siteHealth.contentHandoff(
          reference.project_id,
          reference.crawl_id,
          reference.site_url_id,
          reference.source_analysis_id,
          reference.dimension,
          reference.checkpoint_ids,
        )
      : queryKeys.siteHealth.contentHandoffUnavailable(),
    queryFn: ({ signal }) => {
      if (!reference) throw new Error('Site Health reference is required');
      return siteHealthApi.getContentHandoff(
        {
          projectId: reference.project_id,
          crawlId: reference.crawl_id,
          siteUrlId: reference.site_url_id,
          sourceAnalysisId: reference.source_analysis_id,
          dimension: reference.dimension,
          checkpointIds: reference.checkpoint_ids,
        },
        { signal },
      );
    },
    enabled: Boolean(reference),
  });
}

/** The opportunity behind a `?opportunity_id=` arrival, in its own words. */
export type ContentOpportunityContext = {
  id: string;
  title: string;
  target: string;
  pathway: 'owned' | 'earned';
  canonicalDomain: string | null;
  taskSeed: string;
  suggestedSkillId: string;
  limitations: string[];
  citations: Array<Record<string, unknown>>;
};

export function useOpportunityContext(
  opportunityId?: string | null,
): ContentOpportunityContext | null {
  const query = useQuery({
    ...opportunitiesQueries.detail(opportunityId ?? ''),
    enabled: Boolean(opportunityId),
  });
  const data = query.data;
  return useMemo(() => {
    if (!data) return null;
    return {
      id: data.id,
      title: data.title,
      target: data.target_url ?? data.target_theme ?? '',
      pathway: data.content_handoff.pathway,
      canonicalDomain: data.content_handoff.canonical_domain,
      taskSeed: data.content_handoff.task_seed,
      suggestedSkillId: data.content_handoff.suggested_skill_id,
      limitations: data.content_handoff.limitations,
      citations: data.content_handoff.representative_citations,
    };
  }, [data]);
}

export type { ContentSkillView };
