'use client';

import { useEffect, useMemo, useState } from 'react';
import { usePathname, useSearchParams } from 'next/navigation';
import { useQuery } from '@tanstack/react-query';

import type { EngineFilter } from '@/components/visibility/visibility-toolbar';
import { queryKeys } from '@/lib/api/query-keys';
import { retainPreviousDataForScope } from '@/lib/api/query-client';
import { runsApi } from '@/lib/api/runs';
import { visibilityApi } from '@/lib/api/visibility';
import {
  findActiveRun,
  isEvidenceTab,
  normalizeTab,
  toPromptOptions,
  toRunOptions,
  type VisibilityTab,
} from '@/lib/visibility/dashboard';
import { shouldPollAudit } from '@/lib/runs/status';
import { ACTIVE_RUN_POLL_MS, EVIDENCE_LIMIT } from '@/lib/config/operational';

/** Compatibility exports for existing visibility consumers and tests. */
export { EVIDENCE_LIMIT } from '@/lib/config/operational';
import { rangeToFrom, type TrendGranularity, type TrendRange } from '@/lib/visibility/trends';

/**
 * The Visibility workspace's URL-synced tab + shared filter state.
 *
 * The active tab is mirrored in `?tab=` (invalid values fall back to Overview)
 * so refresh / back / forward preserve it; local state keeps it responsive and
 * re-syncs from the URL on back/forward navigation. Shared filter STATE lives
 * here and persists across tab switches; hidden controls keep their state.
 * Ownership (plan §IA): selected run → Overview + both evidence tabs; logical
 * engine → every tab; prompt → both evidence tabs; date range → Trends + both
 * evidence tabs; granularity → Trends only.
 */
export function useVisibilityFilters() {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const urlTab = normalizeTab(searchParams?.get('tab'));

  const [activeTab, setActiveTab] = useState<VisibilityTab>(urlTab);
  useEffect(() => {
    // Intentional URL→state sync (external navigation is the source of truth).
    // oxlint-disable-next-line react-hooks/set-state-in-effect
    setActiveTab(urlTab);
  }, [urlTab]);

  // Shared filter state (persists across tab switches).
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const [engine, setEngine] = useState<EngineFilter>('all');
  const [promptId, setPromptId] = useState<string | null>(null);
  const [range, setRange] = useState<TrendRange>('90d');
  const [granularity, setGranularity] = useState<TrendGranularity>('run');
  const [cohort, setCohort] = useState<'core' | 'comparison'>('core');

  function selectTab(tab: VisibilityTab) {
    setActiveTab(tab);
    const params = new URLSearchParams(searchParams?.toString() ?? '');
    params.set('tab', tab);
    // Shallow URL bookkeeping, NOT navigation. `router.replace` sent every tab
    // click through the App Router — an RSC round trip plus a re-render of the
    // whole route for a query param the page reads locally, which is what made
    // switching tabs stutter. `history.replaceState` is Next's supported
    // shallow-update path: `useSearchParams` still reflects it, so refresh /
    // back / forward keep working.
    window.history.replaceState(null, '', `${pathname}?${params.toString()}`);
  }

  // A narrowing filter (engine, bounded range, or a specific prompt) is active —
  // used to explain a filtered-empty result vs a genuinely empty history.
  const isFiltered = engine !== 'all' || range !== 'all' || promptId !== null || cohort !== 'core';
  const isTrendFiltered = engine !== 'all' || range !== 'all' || cohort !== 'core';

  function clearEvidenceFilters() {
    setEngine('all');
    setRange('all');
    setPromptId(null);
    setCohort('core');
  }

  return {
    activeTab,
    selectTab,
    selectedRunId,
    setSelectedRunId,
    engine,
    setEngine,
    promptId,
    setPromptId,
    range,
    setRange,
    granularity,
    setGranularity,
    cohort,
    setCohort,
    isFiltered,
    isTrendFiltered,
    clearEvidenceFilters,
  };
}

/**
 * The project's dashboard-ready runs: the audits list, the run-selector
 * options, and the effective run — an explicit selection that still exists,
 * else the latest dashboard-ready run (which is also what the endpoint
 * defaults to when `audit_id` is omitted).
 */
function useRunSelection(projectId: string | null, selectedRunId: string | null) {
  const auditsQuery = useQuery({
    queryKey: queryKeys.runs.list({ project_id: projectId ?? '' }),
    queryFn: ({ signal }) => runsApi.listAudits({ project_id: projectId! }, { signal }),
    enabled: Boolean(projectId),
    // While any run is still progressing, keep the audits list fresh so an
    // in-progress run is visible here (not only on /runs/[runId]) and its
    // snapshot appears the moment it completes. Stops when all runs are
    // terminal.
    refetchInterval: (query) => {
      const audits = query.state.data;
      return audits?.some((audit) => shouldPollAudit(audit.status)) ? ACTIVE_RUN_POLL_MS : false;
    },
  });

  const runOptions = useMemo(() => toRunOptions(auditsQuery.data ?? []), [auditsQuery.data]);
  const activeRun = useMemo(() => findActiveRun(auditsQuery.data ?? []), [auditsQuery.data]);

  const activeRunId = useMemo(() => {
    if (selectedRunId && runOptions.some((run) => run.id === selectedRunId)) {
      return selectedRunId;
    }
    return runOptions[0]?.id ?? null;
  }, [runOptions, selectedRunId]);

  return {
    auditsQuery,
    runOptions,
    activeRun,
    activeRunId,
    hasRuns: runOptions.length > 0,
  };
}

/**
 * The shared execution-evidence queries for the two evidence tabs. ONE
 * identical cache key drives both tabs, so switching between Mentions &
 * Citations and Query Fanout reuses the cache instead of refetching.
 * `audit_id` + date bound intersect server-side.
 *
 * Prompt options for the evidence prompt selector must NOT collapse when a
 * prompt is selected, so they are derived from a parallel evidence query that
 * keeps the run/engine/date scope but omits `prompt_id`. When no prompt is
 * selected that key is identical to the main evidence query, so it reuses the
 * cache and issues no extra request; only a selected prompt filter triggers a
 * second (unfiltered-by-prompt) fetch to keep the list stable.
 */
function useEvidenceQueries(
  projectId: string | null,
  enabled: boolean,
  scope: Readonly<{
    activeRunId: string | null;
    promptId: string | null;
    engineParam: string | undefined;
    fromParam: string | undefined;
    cohort: 'core' | 'comparison';
  }>,
) {
  const { activeRunId, promptId, engineParam, fromParam, cohort } = scope;
  const evidenceParams = {
    audit_id: activeRunId ?? undefined,
    prompt_id: promptId ?? undefined,
    engine: engineParam,
    from: fromParam,
    limit: EVIDENCE_LIMIT,
    cohort,
  };
  const keyFilters = {
    audit_id: activeRunId ?? null,
    engine: engineParam ?? null,
    from: fromParam ?? null,
    limit: EVIDENCE_LIMIT,
    cohort,
  };

  const evidenceQuery = useQuery({
    queryKey: queryKeys.visibility.evidence(projectId ?? '', {
      ...keyFilters,
      prompt_id: promptId ?? null,
    }),
    queryFn: ({ signal }) =>
      visibilityApi.getVisibilityEvidence(projectId!, evidenceParams, { signal }),
    enabled,
    placeholderData: (previousData, previousQuery) =>
      retainPreviousDataForScope(projectId!, previousData, previousQuery),
  });

  const promptOptionsQuery = useQuery({
    queryKey: queryKeys.visibility.evidence(projectId ?? '', {
      ...keyFilters,
      prompt_id: null,
    }),
    queryFn: ({ signal }) =>
      visibilityApi.getVisibilityEvidence(
        projectId!,
        { ...evidenceParams, prompt_id: undefined },
        { signal },
      ),
    enabled,
    placeholderData: (previousData, previousQuery) =>
      retainPreviousDataForScope(projectId!, previousData, previousQuery),
  });
  const promptOptions = useMemo(
    () => toPromptOptions(promptOptionsQuery.data?.items ?? []),
    [promptOptionsQuery.data],
  );

  return { evidenceQuery, promptOptions };
}

/**
 * The Visibility workspace's per-tab queries. Only the relevant query runs per
 * tab: the selected-run projection and trend series for Trends, and the shared
 * execution-evidence query (one identical cache key) for either
 * evidence tab — so switching between the two evidence tabs reuses the cache.
 */
export function useVisibilityQueries(
  projectId: string | null,
  filters: ReturnType<typeof useVisibilityFilters>,
) {
  const runs = useRunSelection(projectId, filters.selectedRunId);
  const scope = useQueryScope(filters);
  const trendsEnabled = Boolean(projectId) && runs.hasRuns && filters.activeTab === 'trends';
  const visibilityQuery = useVisibilityProjection(
    projectId,
    runs.activeRunId,
    scope.cohort,
    trendsEnabled,
  );
  const trendQuery = useTrendQuery(projectId, scope, trendsEnabled);
  const evidence = useEvidenceQueries(
    projectId,
    Boolean(projectId) && runs.hasRuns && isEvidenceTab(filters.activeTab),
    { activeRunId: runs.activeRunId, promptId: filters.promptId, ...scope },
  );
  return { ...runs, visibilityQuery, trendQuery, ...evidence };
}

function useQueryScope(filters: ReturnType<typeof useVisibilityFilters>) {
  const engineParam = filters.engine === 'all' ? undefined : filters.engine;
  const fromParam = useMemo(() => rangeToFrom(filters.range), [filters.range]);
  return { engineParam, fromParam, granularity: filters.granularity, cohort: filters.cohort };
}

function useVisibilityProjection(
  projectId: string | null,
  activeRunId: string | null,
  cohort: 'core' | 'comparison',
  enabled: boolean,
) {
  return useQuery({
    queryKey: [...queryKeys.visibility.project(projectId ?? '', activeRunId ?? undefined), cohort],
    queryFn: ({ signal }) =>
      visibilityApi.getProjectVisibility(
        projectId!,
        { audit_id: activeRunId ?? undefined, cohort },
        { signal },
      ),
    enabled,
  });
}

function useTrendQuery(
  projectId: string | null,
  scope: ReturnType<typeof useQueryScope>,
  enabled: boolean,
) {
  return useQuery({
    queryKey: queryKeys.visibility.trends(projectId ?? '', {
      engine: scope.engineParam ?? null,
      from: scope.fromParam ?? null,
      granularity: scope.granularity,
      cohort: scope.cohort,
    }),
    queryFn: ({ signal }) =>
      visibilityApi.getVisibilityTrends(
        projectId!,
        {
          engine: scope.engineParam,
          from: scope.fromParam,
          granularity: scope.granularity,
          cohort: scope.cohort,
        },
        { signal },
      ),
    enabled,
    placeholderData: (previousData, previousQuery) =>
      retainPreviousDataForScope(projectId!, previousData, previousQuery),
  });
}
