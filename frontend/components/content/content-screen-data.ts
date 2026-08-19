import { useQuery } from '@tanstack/react-query';
import { useMemo } from 'react';

import { type ContentSkillView, contentApi } from '@/lib/api/content';
import { demandApi } from '@/lib/api/demand';
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
    queryKey: ['demand', projectId, 'latest'],
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

export type { ContentSkillView };
