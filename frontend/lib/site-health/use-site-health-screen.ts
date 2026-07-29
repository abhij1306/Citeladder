'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/lib/api/query-keys';
import { siteHealthMutations, siteHealthQueries } from '@/lib/api/site-health';
import type { SiteCrawl, SiteHealthDashboard, SiteHealthEntitlement } from '@/lib/api/types';
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
  const plan: SiteHealthEntitlement['plan_key'] = entitlementQuery.data?.plan_key ?? 'free';
  // `undefined` / `null` mean "this input has not settled once yet" — the phase
  // resolution below is total over that state instead of resolving against
  // whichever query happened to land first. A FAILED query counts as settled:
  // it has an answer (the fallback), and waiting forever would be worse.
  const crawlInput = dashboardQuery.isPending ? undefined : crawl;
  const planInput = entitlementQuery.isPending ? null : plan;

  // SSE invalidation accelerator (polling stays the baseline). Dropped for a
  // stalled crawl too: if we have given up polling it, holding a reconnecting
  // stream open for it is the same waste by another route.
  useCrawlEvents(crawl?.id, projectId, active && !stalled);

  // Per-page rows for the table + live score preview, scoped to
  // `monitored: true` so only selected rows show. This is a bounded WINDOW
  // (first 200 by URL order) — with env-raised limits the monitored set may be
  // far larger, so the progress COUNTS come from server counters (crawl
  // `analyzed_count` / `failed_count` and the dashboard quota), never from this
  // page fetch. No timer of its own: the crawl-version effect below refreshes
  // it whenever the polled crawl actually moved.
  const pagesQuery = useQuery({
    ...siteHealthQueries.pages(crawl?.id ?? '', { limit: 200, monitored: true }),
    enabled: Boolean(crawl?.id),
  });

  // THE single subscription's fan-out: when the dashboard's poll (or an SSE
  // invalidation) lands a crawl that actually moved, refresh every list derived
  // from it. Keyed on a progress fingerprint rather than object identity, so a
  // refetch that returns an unchanged crawl costs nothing downstream.
  const crawlId = crawl?.id ?? null;
  const crawlVersion = crawl ? crawlProgressVersion(crawl) : null;
  const lastSeenRef = useRef<{ crawlId: string; version: string } | null>(null);
  useEffect(() => {
    if (!crawlId || crawlVersion === null) return;
    const previous = lastSeenRef.current;
    lastSeenRef.current = { crawlId, version: crawlVersion };
    // Nothing to refresh on the first sighting of a crawl (its lists are
    // mounting against it) or when the fingerprint is unchanged.
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
    () => resolveSiteHealthPhase(crawlInput, planInput, monitoredInput),
    [crawlInput, planInput, monitoredInput],
  );

  // Canonical-screen view-model: the same layout stays mounted through the
  // whole discover → select → analyze → scored flow; these two modifiers are
  // all that changes (which header control shows, what the inventory section
  // renders). Derived, never stored — the crawl shape is the single source.
  const primaryAction: PrimaryAction = primaryActionForPhase(phase, active);
  const inventoryMode: InventoryMode = inventoryModeForPhase(phase);
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

  const startCrawl = () => projectId && createMutation.mutate({ project_id: projectId });
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
    startCrawl,
    cancelCrawl,
    runExport,
    exporting,
    exportError,
  };
}
