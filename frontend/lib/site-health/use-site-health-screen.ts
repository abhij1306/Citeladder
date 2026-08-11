'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { queryKeys } from '@/lib/api/query-keys';
import {
  siteHealthMutations,
  siteHealthQueries,
  type CreateCrawlInput,
} from '@/lib/api/site-health';
import type { SiteCrawl } from '@/lib/api/types';
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
  shouldPollCrawl,
  type InventoryMode,
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
  // THE phase, resolved server-side from the crawl, the entitlement, and the
  // project's monitored set at one instant. `'resolving'` only means the
  // dashboard request has not landed yet — there is no client-side precedence
  // chain racing three independently-loading queries any more.
  const phase: SiteHealthPhase = dashboardQuery.data?.phase ?? 'resolving';

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

  // Per-PROJECT monitored set. Supplies the analysis progress totals and the
  // `selection_version` that guards a phase mutation. It is NO LONGER a phase
  // input: the server counts these rows in the same transaction that resolves
  // the phase, so this query landing late can no longer flip the screen from
  // 'selection' to 'analyzing' after it has already rendered.
  const monitoredQuery = useQuery({
    ...siteHealthQueries.monitored(projectId ?? ''),
    enabled: Boolean(projectId),
  });
  const projectSelectedTotal = useMemo(() => {
    const rows = monitoredQuery.data?.monitored_urls;
    if (!rows) return null;
    return rows.filter((row) => row.active).length;
  }, [monitoredQuery.data]);

  // The live score preview shares the exact first-page query key rendered by
  // ScoredInventory. React Query therefore issues ONE request for both
  // consumers. Discovery does not render or score page analyses, so keeping
  // this disabled until analysis/dashboard avoids fetching a hidden 200-row
  // projection on every progress event.
  const pagesQuery = useQuery({
    ...siteHealthQueries.pages(crawl?.id ?? '', { limit: PAGE_LIMIT, monitored: true }),
    enabled: Boolean(crawl?.id) && (phase === 'analyzing' || phase === 'dashboard'),
  });

  // The one thing still derived from the phase: what the always-mounted
  // inventory section renders. The crawl rides along so a FAILED terminal
  // phase keeps the scored page browser (B3 — the Errors & Blocked tab renders
  // the root-failure block).
  const inventoryMode: InventoryMode = inventoryModeForPhase(phase, crawl);
  // Surface a failed monitored-count fetch rather than silently disabling the
  // analysis view: the count query is best-effort (the counters degrade to the
  // visible window), but the error is exposed so the screen can note it.
  const projectSelectedError = monitoredQuery.isError;

  const createMutation = useMutation({
    ...siteHealthMutations.createCrawl(),
    onSuccess: async () => {
      if (!projectId) return;
      // The create response is a crawl row, while this screen is driven by the
      // backend's crawl + phase projection. Keep the mutation pending until
      // that complete projection refetches; partially replacing only `crawl`
      // would temporarily combine a new run with the previous run's phase.
      await queryClient.invalidateQueries({
        queryKey: queryKeys.siteHealth.dashboard(projectId),
      });
    },
  });
  const cancelMutation = useMutation({
    ...siteHealthMutations.cancelCrawl(),
    onSuccess: async () => {
      if (!projectId) return;
      // Cancellation also changes the server-owned phase. Refresh the whole
      // projection atomically instead of pairing the terminal crawl row with
      // an active phase in the client cache.
      await queryClient.invalidateQueries({
        queryKey: queryKeys.siteHealth.dashboard(projectId),
      });
    },
  });
  const startCrawl = (input?: CreateCrawlInput) =>
    projectId && createMutation.mutate(input ?? { project_id: projectId });
  const cancelCrawl = () => crawl && cancelMutation.mutate(crawl.id);

  // A create is genuinely in flight: the button says "Starting…" and a second
  // click cannot fire a duplicate. Scoped to the create's own project so a
  // sticky mutation from another project (after a project switch) can never
  // disable this screen's control. The mutation stays pending through the
  // server-projection refetch, so there is no post-success duplicate-click
  // gap and no separate client-only `crawlStarting` state.
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
