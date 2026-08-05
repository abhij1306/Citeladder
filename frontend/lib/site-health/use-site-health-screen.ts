'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/lib/api/query-keys';
import {
  siteHealthMutations,
  siteHealthQueries,
  type CreateCrawlInput,
} from '@/lib/api/site-health';
import type {
  PhaseMutationResponse,
  SiteCrawl,
  SiteHealthDashboard,
  SiteHealthEntitlement,
} from '@/lib/api/types';
import {
  downloadCrawlExport,
  type ExportFormat,
  type ExportView,
} from '@/lib/site-health/download';
import { invalidateCrawlViews } from '@/lib/site-health/invalidate';
import { useCrawlEvents } from '@/lib/site-health/use-crawl-events';
import {
  crawlPollInterval,
  crawlProgressVersion,
  inventoryModeForPhase,
  isCrawlStalled,
  PAGE_LIMIT,
  primaryActionForPhase,
  resolveSiteHealthPhase,
  shouldPollCrawl,
  type InventoryMode,
  type PrimaryAction,
  type SiteHealthPhase,
} from '@/lib/site-health/status';

/**
 * Data orchestration for the Site Health screen (Slice 7).
 *
 * Owns the entitlement / dashboard / pages / discovery-preview / monitored
 * queries, the create/cancel mutations, the export flow, and the phase
 * resolution. Progress is POLLING-FIRST: the credentialed SSE stream is only an
 * invalidation accelerator (a dropped stream never stops progress). Exports are
 * authenticated blob downloads so a non-default workspace's `X-Workspace-Id`
 * is preserved.
 *
 * Polling is ONE subscription. The dashboard query owns the only timer; every
 * other crawl-derived view (pages here, inventory/pages/issues in the sections)
 * refreshes when the crawl's progress fingerprint changes. Five components each
 * running their own 4s timer over the same crawl produced overlapping refetches
 * that resolved out of order, so panels rendered state from different moments.
 */
export function useSiteHealthScreen(projectId: string | null) {
  const queryClient = useQueryClient();
  const [exportError, setExportError] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const entitlementQuery = useQuery(siteHealthQueries.entitlements());

  const dashboardQuery = useQuery({
    ...siteHealthQueries.dashboard(projectId ?? ''),
    enabled: Boolean(projectId),
    // Backed off by crawl age, and stops entirely on a crawl that has gone
    // silent — an active-forever crawl must not pin the tab to a 4s poll of
    // five queries indefinitely.
    refetchInterval: (query) => {
      const polled = query.state.data?.crawl;
      return polled ? crawlPollInterval(polled) : false;
    },
  });

  const crawl: SiteCrawl | null = dashboardQuery.data?.crawl ?? null;
  const active = crawl ? shouldPollCrawl(crawl) : false;
  // An active crawl the client has stopped polling: surfaced so the screen can
  // say so explicitly rather than showing a progress state that never advances.
  const stalled = isCrawlStalled(crawl);
  /**
   * The neutral access mode, or null when the entitlement is not usable.
   *
   * FAIL CLOSED — there is deliberately no `?? 'sample'` fallback here. An
   * entitlement that is pending, errored, or `entitlement_unresolved` yields
   * null, which resolves the phase to `'resolving'` and enables no crawl or
   * selection action. Defaulting would let an unresolved account act as if it
   * had been granted the minimum, which is a grant we never verified.
   */
  const entitlement: SiteHealthEntitlement | null =
    entitlementQuery.data?.resolver_status === 'resolved' ? entitlementQuery.data : null;
  const accessMode = entitlement?.access_mode ?? null;
  // `undefined` / `null` mean "this input has not settled once yet" — the phase
  // resolution below is total over that state instead of resolving against
  // whichever query happened to land first.
  const crawlInput = dashboardQuery.isPending ? undefined : crawl;
  const accessModeInput = entitlementQuery.isPending ? null : accessMode;

  // SSE invalidation accelerator (polling stays the baseline). Dropped for a
  // stalled crawl too: if we have given up polling it, holding a reconnecting
  // stream open for it is the same waste by another route.
  useCrawlEvents(crawl?.id, projectId, active && !stalled);

  // Refresh crawl-derived lists only when persisted progress changes. The
  // first sighting mounts its own queries, and unchanged dashboard polls do no
  // downstream work.
  const crawlId = crawl?.id ?? null;
  const crawlVersion = crawl ? crawlProgressVersion(crawl) : null;
  const lastSeenRef = useRef<{ crawlId: string; version: string } | null>(null);
  useEffect(() => {
    if (!crawlId || crawlVersion === null) return;
    const previous = lastSeenRef.current;
    lastSeenRef.current = { crawlId, version: crawlVersion };
    if (previous?.crawlId !== crawlId || previous.version === crawlVersion) return;
    invalidateCrawlViews(queryClient, crawlId);
  }, [crawlId, crawlVersion, queryClient]);

  // Per-PROJECT monitored set. Feeds BOTH the phase resolution (an active
  // crawl with a committed monitored set is an analysis run from creation —
  // its analyze tasks are seeded before `analysis_status` leaves 'pending')
  // and the analysis progress totals. The dashboard quota `used` is
  // workspace-wide, so a multi-project workspace would overcount this crawl's
  // queue — count this project's active monitored rows instead. Selection
  // commits write this cache directly (`useMonitoredSelection`), so a commit
  // moves the phase forward without waiting for a refetch.
  const monitoredQuery = useQuery({
    ...siteHealthQueries.monitored(projectId ?? ''),
    enabled: Boolean(projectId),
  });
  const projectSelectedTotal = useMemo(() => {
    const rows = monitoredQuery.data?.monitored_urls;
    if (!rows) return null;
    return rows.filter((row) => row.active).length;
  }, [monitoredQuery.data]);
  // The third phase input. Unsettled until the query has an answer — this is
  // the one that used to land LAST and flip the phase from 'selection' to
  // 'analyzing' after the screen had already rendered.
  const monitoredInput = monitoredQuery.isPending ? null : (projectSelectedTotal ?? 0) > 0;

  const phase: SiteHealthPhase = useMemo(
    () => resolveSiteHealthPhase(crawlInput, accessModeInput, monitoredInput),
    [crawlInput, accessModeInput, monitoredInput],
  );

  // The live score preview shares the exact first-page query key rendered by
  // ScoredInventory. React Query therefore issues ONE request for both
  // consumers. Discovery does not render or score page analyses, so keeping
  // this disabled until analysis/dashboard avoids fetching a hidden 200-row
  // projection on every progress event.
  const pagesQuery = useQuery({
    ...siteHealthQueries.pages(crawl?.id ?? '', { limit: PAGE_LIMIT, monitored: true }),
    enabled: Boolean(crawl?.id) && (phase === 'analyzing' || phase === 'dashboard'),
  });

  // Canonical-screen view-model: the same layout stays mounted through the
  // whole discover → select → analyze → scored flow; these two modifiers are
  // all that changes (which header control shows, what the inventory section
  // renders). Derived, never stored — the crawl shape is the single source.
  const primaryAction: PrimaryAction = primaryActionForPhase(phase, active);
  // The crawl rides along so a FAILED terminal phase keeps the scored page
  // browser (B3 — the Errors & Blocked tab renders the root-failure block).
  const inventoryMode: InventoryMode = inventoryModeForPhase(phase, crawl);
  // Surface a failed monitored-count fetch rather than silently disabling the
  // analysis view: the count query is best-effort (the counters degrade to the
  // visible window), but the error is exposed so the screen can note it.
  const projectSelectedError = monitoredQuery.isError;

  const createMutation = useMutation({
    ...siteHealthMutations.createCrawl(),
    onSuccess: (created) => {
      if (!projectId) return;
      // Hand the screen its NEW crawl in the same tick the create resolves.
      // Without this the dashboard kept returning the PREVIOUS crawl until a
      // refetch landed, so the phase re-resolved against a stale (often
      // terminal) crawl and bounced the UI back to the selection list right
      // after "Start analysis" — the bug the `crawlStarting` flag and a
      // `createMutation.reset()` effect used to mask. Fixing the input retires
      // both. Same-shape write as the cancel mutation below.
      queryClient.setQueryData<SiteHealthDashboard>(
        queryKeys.siteHealth.dashboard(projectId),
        (prev) => (prev ? { ...prev, crawl: created } : prev),
      );
      queryClient.invalidateQueries({ queryKey: queryKeys.siteHealth.dashboard(projectId) });
    },
  });
  const cancelMutation = useMutation({
    ...siteHealthMutations.cancelCrawl(),
    onSuccess: (updated) => {
      if (projectId) {
        queryClient.setQueryData(queryKeys.siteHealth.dashboard(projectId), {
          ...dashboardQuery.data,
          crawl: updated,
        });
        queryClient.invalidateQueries({ queryKey: queryKeys.siteHealth.dashboard(projectId) });
      }
    },
  });
  const applyPhaseResult = (result: PhaseMutationResponse) => {
    if (!projectId) return;
    queryClient.setQueryData<SiteHealthDashboard>(
      queryKeys.siteHealth.dashboard(projectId),
      (previous) =>
        previous
          ? {
              ...previous,
              crawl: result.crawl,
              phase_runs: result.created_new_crawl
                ? { discovery: null, analysis: null }
                : result.phase_run
                  ? {
                      ...previous.phase_runs,
                      [result.phase_run.phase]: result.phase_run,
                    }
                  : previous.phase_runs,
            }
          : previous,
    );
    void queryClient.invalidateQueries({
      queryKey: queryKeys.siteHealth.monitored(projectId),
    });
  };
  const startDiscoveryMutation = useMutation({
    ...siteHealthMutations.startDiscovery(),
    onSuccess: applyPhaseResult,
  });
  const stopDiscoveryMutation = useMutation({
    ...siteHealthMutations.stopDiscovery(),
    onSuccess: applyPhaseResult,
  });
  const startAnalysisMutation = useMutation({
    ...siteHealthMutations.startAnalysis(),
    onSuccess: applyPhaseResult,
  });
  const stopAnalysisMutation = useMutation({
    ...siteHealthMutations.stopAnalysis(),
    onSuccess: applyPhaseResult,
  });

  const startCrawl = (input?: CreateCrawlInput) =>
    projectId && createMutation.mutate(input ?? { project_id: projectId });
  const cancelCrawl = () => crawl && cancelMutation.mutate(crawl.id);

  // A create is genuinely in flight: the button says "Starting…" and a second
  // click cannot fire a duplicate. Scoped to the create's own project so a
  // sticky mutation from another project (after a project switch) can never
  // disable this screen's control. This is ONLY the request window — the
  // post-success gap that `crawlStarting` also covered no longer exists, since
  // `onSuccess` writes the new crawl straight into the dashboard cache.
  const startPending =
    createMutation.isPending && createMutation.variables?.project_id === projectId;

  const runExport = async (format: ExportFormat, view: ExportView) => {
    if (!crawl) return;
    setExportError(null);
    setExporting(true);
    try {
      await downloadCrawlExport(crawl.id, format, view);
    } catch {
      setExportError('Export failed. Please try again.');
    } finally {
      setExporting(false);
    }
  };

  return {
    entitlementQuery,
    dashboardQuery,
    pagesQuery,
    monitoredQuery,
    crawl,
    active,
    stalled,
    phase,
    primaryAction,
    inventoryMode,
    projectSelectedTotal,
    projectSelectedError,
    startPending,
    createMutation,
    cancelMutation,
    startDiscoveryMutation,
    stopDiscoveryMutation,
    startAnalysisMutation,
    stopAnalysisMutation,
    startCrawl,
    cancelCrawl,
    runExport,
    exporting,
    exportError,
  };
}
