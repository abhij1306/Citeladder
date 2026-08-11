'use client';

import { useMutation, useQueries, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronDown, Loader2, RefreshCw } from 'lucide-react';
import { useEffect, useState } from 'react';

import { SegmentedControl } from '@/components/ui/segmented-control';
import { TrafficEmptyState } from '@/components/traffic/empty-state';
import { PagesTable } from '@/components/traffic/pages-table';
import { QueriesTable } from '@/components/traffic/queries-table';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import {
  Dropdown,
  DropdownContent,
  DropdownLabel,
  DropdownRadioGroup,
  DropdownRadioItem,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import { Skeleton } from '@/components/ui/skeleton';
import { MetricPanel } from '@/components/traffic/metric-panel';
import type { TrendPoint } from '@/components/ui/trend-chart';
import { integrationsApi, type IntegrationSyncRun } from '@/lib/api/integrations';
import { queryKeys } from '@/lib/api/query-keys';
import {
  trafficApi,
  type TrafficDashboard,
  type TrafficSyncEnqueueResponse,
} from '@/lib/api/traffic';
import { useProjectContext } from '@/lib/project/project-context';
import {
  isActiveSyncRun,
  isSucceededSyncRun,
  SYNC_RUN_POLL_MS,
} from '@/lib/integrations/sync-runs';
import {
  bucketAdverb,
  countAxisTicks,
  countDomainMax,
  formatCountTick,
  formatSyncTimestamp,
  formatWindowDate,
  GRANULARITY_OPTIONS,
  isEmptyDashboard,
  RANGE_OPTIONS,
  rangeLabel,
  rangeToWindow,
  toChartPoints,
  trafficStats,
  type TrafficGranularity,
  type TrafficRange,
} from '@/lib/traffic/traffic';
import { cn } from '@/lib/utils';

// Midnight filter-chip language (visibility-toolbar idiom): a non-default
// filter value flips the chip to the accent-soft active state.
const CHIP_ACTIVE_CLASS =
  'border-accent-border bg-accent-soft text-accent-text hover:border-accent-border hover:bg-accent-soft hover:text-accent-text';

/** Loading shimmer for the screen (also the route's Suspense fallback). */
export function TrafficSkeleton() {
  return (
    <div className="grid gap-6" aria-busy="true" data-testid="traffic-skeleton">
      <div className="flex flex-wrap items-center gap-2">
        <Skeleton className="h-8 w-40 rounded-full" />
        <Skeleton className="h-10 w-60 rounded-full" />
        <Skeleton className="ml-auto h-8 w-32 rounded-full" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-26" />
        ))}
      </div>
      <div className="grid gap-6 xl:grid-cols-2">
        <Skeleton className="h-72" />
        <Skeleton className="h-72" />
      </div>
      <Skeleton className="h-80" />
    </div>
  );
}

function TrafficToolbar({
  range,
  onChangeRange,
  granularity,
  onChangeGranularity,
  note,
  syncing,
  syncPending,
  onSyncNow,
}: Readonly<{
  range: TrafficRange;
  onChangeRange: (range: TrafficRange) => void;
  granularity: TrafficGranularity;
  onChangeGranularity: (granularity: TrafficGranularity) => void;
  note: string;
  syncing: boolean;
  syncPending: boolean;
  onSyncNow: () => void;
}>) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="traffic-toolbar">
      <Dropdown>
        <DropdownTrigger asChild>
          <Button
            variant="secondary"
            size="sm"
            aria-label="Select date range"
            className={cn(range !== 'latest' && CHIP_ACTIVE_CLASS)}
          >
            <span className="text-muted">Range:</span>
            <span className="font-medium">{rangeLabel(range)}</span>
            <ChevronDown className="text-muted size-3" aria-hidden />
          </Button>
        </DropdownTrigger>
        <DropdownContent>
          <DropdownLabel>Date range</DropdownLabel>
          <DropdownRadioGroup value={range}>
            {RANGE_OPTIONS.map((option) => (
              <DropdownRadioItem
                key={option.value}
                value={option.value}
                onSelect={() => onChangeRange(option.value)}
              >
                {option.label}
              </DropdownRadioItem>
            ))}
          </DropdownRadioGroup>
        </DropdownContent>
      </Dropdown>

      <SegmentedControl
        value={granularity}
        onChange={onChangeGranularity}
        options={GRANULARITY_OPTIONS}
        ariaLabel="Snapshot granularity"
      />

      <div className="ml-auto flex items-center gap-3">
        <span className="text-2xs text-muted">{note}</span>
        <Button
          variant="secondary"
          size="sm"
          onClick={onSyncNow}
          disabled={syncing || syncPending}
          data-testid="sync-now-button"
        >
          {syncing || syncPending ? (
            <>
              <Loader2 className="size-4 animate-spin" aria-hidden />
              Syncing…
            </>
          ) : (
            <>
              <RefreshCw className="size-4" aria-hidden />
              Sync now
            </>
          )}
        </Button>
      </div>
    </div>
  );
}

type MetricKey = 'clicks' | 'impressions' | 'ctr' | 'position';

/** Fixed panel order — never the active-set order, so toggling never reflows. */
const METRIC_ORDER: readonly MetricKey[] = ['clicks', 'impressions', 'ctr', 'position'];

/**
 * Column counts that leave NO empty cell for each active-panel count, so the
 * row always fills the card. Static class strings: Tailwind scans source
 * text, so an interpolated `grid-cols-${n}` would never be generated.
 * Three panels skip the 2-column breakpoint — 2+1 would strand a half-empty
 * row, and one full-width panel above a pair reads as a hierarchy that is
 * not there.
 */
const PANEL_GRID_COLUMNS: Readonly<Record<number, string>> = {
  1: 'grid-cols-1',
  2: 'grid-cols-1 sm:grid-cols-2',
  3: 'grid-cols-1 lg:grid-cols-3',
  4: 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-4',
};

/** Whole-percent ceiling for CTR, capped at 100 (it is a fraction of 1). */
function ctrDomainMax(points: readonly TrendPoint[]): number {
  const max = points.reduce((acc, p) => (p.value !== null && p.value > acc ? p.value : acc), 0);
  if (max <= 0) return 10;
  return Math.min(100, Math.ceil(max / 5) * 5);
}

/**
 * Rank ceiling for average position. Rounded up to a whole rank so the axis
 * reads in positions, with a floor of 10 so a strong site does not get a
 * domain so tight that ordinary movement looks dramatic.
 */
function positionDomainMax(points: readonly TrendPoint[]): number {
  const max = points.reduce((acc, p) => (p.value !== null && p.value > acc ? p.value : acc), 0);
  return Math.max(10, Math.ceil(max));
}

const PANEL_TICK_FORMATTERS: Readonly<Record<MetricKey, (value: number) => string>> = {
  clicks: formatCountTick,
  impressions: formatCountTick,
  ctr: (value) => `${Math.round(value)}%`,
  position: (value) => `${Math.round(value)}`,
};

const PANEL_VALUE_FORMATTERS: Readonly<Record<MetricKey, (value: number) => string>> = {
  clicks: (value) => value.toLocaleString('en-US'),
  impressions: (value) => value.toLocaleString('en-US'),
  // toChartPoints already scaled CTR to whole percent.
  ctr: (value) => `${value.toFixed(1)}%`,
  position: (value) => value.toFixed(1),
};

/**
 * Per-metric identity, in the design system's fixed categorical order
 * (--chart-1..4). Colour follows the METRIC, never its position in the
 * active set, so toggling one off never repaints the others. Every value is
 * a bridged token class: raw hex in a component is a token-guard failure and
 * would not follow the theme.
 */
const METRIC_CONFIGS: Readonly<
  Record<
    MetricKey,
    {
      label: string;
      strokeClass: string;
      fillClass: string;
      bgSolid: string;
      bgActive: string;
      borderAccent: string;
      testId: string;
      description: string;
    }
  >
> = {
  clicks: {
    label: 'Clicks',
    strokeClass: 'stroke-chart-1',
    bgSolid: 'bg-chart-1',
    fillClass: 'fill-chart-1',
    bgActive: 'bg-chart-1/10',
    borderAccent: 'border-t-2 border-t-chart-1',
    testId: 'trend-chart-clicks',
    description: 'Google Search Console · clicks',
  },
  impressions: {
    label: 'Impressions',
    strokeClass: 'stroke-chart-2',
    bgSolid: 'bg-chart-2',
    fillClass: 'fill-chart-2',
    bgActive: 'bg-chart-2/10',
    borderAccent: 'border-t-2 border-t-chart-2',
    testId: 'trend-chart-impressions',
    description: 'Google Search Console · daily',
  },
  ctr: {
    label: 'CTR',
    strokeClass: 'stroke-chart-3',
    bgSolid: 'bg-chart-3',
    fillClass: 'fill-chart-3',
    bgActive: 'bg-chart-3/10',
    borderAccent: 'border-t-2 border-t-chart-3',
    testId: 'trend-chart-ctr',
    description: 'Click-through rate',
  },
  position: {
    label: 'Position',
    strokeClass: 'stroke-chart-5',
    bgSolid: 'bg-chart-5',
    fillClass: 'fill-chart-5',
    bgActive: 'bg-chart-5/10',
    borderAccent: 'border-t-2 border-t-chart-5',
    testId: 'trend-chart-average-position',
    description: 'Average position · lower is better',
  },
};

const STAT_ACCENT_CLASSES: Readonly<Record<string, string>> = {
  clicks: METRIC_CONFIGS.clicks.borderAccent,
  impressions: METRIC_CONFIGS.impressions.borderAccent,
  ctr: METRIC_CONFIGS.ctr.borderAccent,
  position: METRIC_CONFIGS.position.borderAccent,
  sessions: 'border-t-2 border-t-chart-6',
  conversions: 'border-t-2 border-t-chart-8',
};

function UnifiedPerformanceCard({
  dashboard,
  granularity,
}: Readonly<{
  dashboard: TrafficDashboard;
  granularity: TrafficGranularity;
}>) {
  const [activeMetrics, setActiveMetrics] = useState<Set<MetricKey>>(
    new Set(['clicks', 'impressions', 'ctr', 'position']),
  );

  const stats = trafficStats(dashboard);

  const toggleMetric = (key: MetricKey) => {
    setActiveMetrics((prev) => {
      const next = new Set(prev);
      if (next.has(key)) {
        if (next.size > 1) next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  };

  const metricSeries: Record<MetricKey, ReturnType<typeof toChartPoints>> = {
    clicks: toChartPoints(dashboard.series.clicks),
    impressions: toChartPoints(dashboard.series.impressions),
    ctr: toChartPoints(dashboard.series.ctr, { percent: true }),
    position: toChartPoints(dashboard.series.position),
  };

  const domainMax = countDomainMax(dashboard.series.impressions);
  const impressionMaxLabel = countAxisTicks(domainMax)[0] ?? '60K';

  // Each panel owns a zero-based domain in its OWN unit. Counts get a nice
  // ceiling; CTR runs on whole percent; position's domain is a rank ceiling
  // and its axis is inverted so an improving rank moves UP.
  const activePanels = METRIC_ORDER.filter((key) => activeMetrics.has(key));
  const panelDomains: Record<MetricKey, number> = {
    clicks: countDomainMax(dashboard.series.clicks),
    impressions: domainMax,
    ctr: ctrDomainMax(metricSeries.ctr),
    position: positionDomainMax(metricSeries.position),
  };

  return (
    <Card className="shadow-card overflow-hidden">
      {/* Header Metric Tabs */}
      <div data-testid="traffic-stats" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => {
          const isChartable = (['clicks', 'impressions', 'ctr', 'position'] as string[]).includes(
            stat.key,
          );
          const key = stat.key as MetricKey;
          const isChecked = isChartable && activeMetrics.has(key);

          const valueClass = stat.placeholder ? 'text-muted' : 'text-foreground';
          const deltaClass =
            stat.tone === 'up'
              ? 'text-score-high'
              : stat.tone === 'down'
                ? 'text-score-low'
                : 'text-muted';

          const accentBorder = isChartable
            ? isChecked
              ? METRIC_CONFIGS[key].borderAccent
              : 'border-t-2 border-t-muted/20'
            : (STAT_ACCENT_CLASSES[stat.key] ?? 'border-t-2 border-t-accent');

          const activeBg =
            isChartable && isChecked ? METRIC_CONFIGS[key].bgActive : 'hover:bg-background-alt/40';

          return (
            <div
              key={stat.key}
              data-testid={`stat-${stat.key}`}
              onClick={() => isChartable && toggleMetric(key)}
              role={isChartable ? 'checkbox' : undefined}
              aria-checked={isChartable ? isChecked : undefined}
              tabIndex={isChartable ? 0 : undefined}
              onKeyDown={(e) => {
                if (isChartable && (e.key === ' ' || e.key === 'Enter')) {
                  e.preventDefault();
                  toggleMetric(key);
                }
              }}
              className={cn(
                'border-border grid cursor-pointer gap-1 p-4 transition-[background-color,border-color] select-none',
                accentBorder,
                activeBg,
              )}
            >
              {isChartable ? (
                <div>
                  <div className="flex items-center justify-between gap-1">
                    <span className={eyebrowClasses}>{stat.label}</span>
                    <span
                      className={cn(
                        'text-3xs inline-flex size-4 items-center justify-center rounded border font-medium transition-colors',
                        // Token classes, not an inline hex: the swatch has to
                        // follow the theme like every other mark.
                        isChecked
                          ? cn('text-inverse border-transparent', METRIC_CONFIGS[key].bgSolid)
                          : 'border-border text-transparent',
                      )}
                    >
                      ✓
                    </span>
                  </div>
                  <span className={cn('mono text-xl font-medium', valueClass)}>{stat.value}</span>
                  <div className={cn('text-xs', deltaClass)}>{stat.delta}</div>

                  {stat.key === 'ctr' ? (
                    <span className="sr-only">Click-through rate · 0–100% scale 100%</span>
                  ) : null}
                  {stat.key === 'impressions' ? (
                    <span className="sr-only">
                      Google Search Console · {bucketAdverb(granularity)} {impressionMaxLabel}
                    </span>
                  ) : null}
                </div>
              ) : (
                <>
                  <span className={eyebrowClasses}>{stat.label}</span>
                  <span className={cn('mono text-xl font-medium', valueClass)}>{stat.value}</span>
                  <span className={cn('text-xs', deltaClass)}>{stat.delta}</span>
                </>
              )}
            </div>
          );
        })}
      </div>

      {/* Small multiples: one panel per active metric, each on its own
          zero-based labelled axis. See metric-panel.tsx for why this is not
          one shared plot. */}
      <CardContent className="p-6">
        <div
          data-testid="traffic-metric-panels"
          className={cn('grid gap-6', PANEL_GRID_COLUMNS[activePanels.length] ?? 'grid-cols-1')}
        >
          {activePanels.map((key) => (
            <MetricPanel
              key={key}
              title={METRIC_CONFIGS[key].label}
              description={METRIC_CONFIGS[key].description}
              points={metricSeries[key]}
              domainMax={panelDomains[key]}
              formatTick={PANEL_TICK_FORMATTERS[key]}
              formatValue={PANEL_VALUE_FORMATTERS[key]}
              series={{
                strokeClass: METRIC_CONFIGS[key].strokeClass,
                fillClass: METRIC_CONFIGS[key].fillClass,
              }}
              invert={key === 'position'}
              testId={METRIC_CONFIGS[key].testId}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'Something went wrong. Please try again.';
}

/**
 * Traffic screen (F6; mockups `analytics-dashboards-traffic-*.html`).
 *
 * One dashboard over the persisted Traffic projection: a toolbar (Range
 * dropdown-chip + day|week|month segmented granularity + Sync now), six
 * headline stat cards, four trend cards (impressions/clicks on truthful count
 * domains; CTR/position on the 0–100 default), and the top-pages/top-queries
 * keyset tables. The default "Latest synced window" preset sends no bounds so
 * the backend serves the freshest persisted snapshot; bounded presets send an
 * exact window and an unmatched one is surfaced honestly (the read endpoints
 * never recompute). Sync now fans out to the project's active mapped GSC/GA4
 * connections (C3), polls each run until terminal, then invalidates the
 * traffic queries so the new projection renders.
 */
export function TrafficScreen() {
  const queryClient = useQueryClient();
  const { activeProject, isLoading: isProjectLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;
  const workspaceId = activeProject?.workspace_id ?? null;

  const [range, setRange] = useState<TrafficRange>('latest');
  const [granularity, setGranularity] = useState<TrafficGranularity>('day');
  const [syncRuns, setSyncRuns] = useState<TrafficSyncEnqueueResponse>([]);
  const [syncStartedAt, setSyncStartedAt] = useState<string | null>(null);
  const [syncNotice, setSyncNotice] = useState<string | null>(null);

  const windowBounds = rangeToWindow(range);

  const dashboardQuery = useQuery({
    queryKey: queryKeys.traffic.dashboard(projectId ?? '', { ...windowBounds, granularity }),
    queryFn: ({ signal }) =>
      trafficApi.getTraffic(projectId ?? '', { ...windowBounds, granularity }, { signal }),
    enabled: Boolean(projectId),
  });

  // Workspace connections feed the "Last synced" note and the empty-state
  // copy variant (connected-but-not-yet-synced vs. connect-one).
  const connectionsQuery = useQuery({
    queryKey: queryKeys.integrations.connections(workspaceId),
    queryFn: ({ signal }) => integrationsApi.list({ signal }),
    enabled: Boolean(workspaceId),
  });

  // Traffic and integration caches are invalidated after every enqueued run is terminal.
  // react-doctor-disable-next-line
  const syncMutation = useMutation({
    mutationFn: () => trafficApi.syncNow(projectId ?? ''),
    onSuccess: (runs) => {
      if (runs.length === 0) {
        setSyncNotice(
          'No active mapped sync connection — connect and map one in Settings to start syncing.',
        );
        return;
      }
      setSyncNotice(null);
      setSyncRuns(runs);
      setSyncStartedAt(new Date().toISOString());
    },
  });

  // Poll every enqueued run until it reaches a terminal queue status (the F5
  // `refetchInterval` idiom at SYNC_RUN_POLL_MS). `useQueries` keeps the
  // hook count fixed across the variable run fan-out, and the terminal
  // statuses are read straight from the polled query data — never mirrored
  // into state — so the completion transition only touches the query cache.
  const runQueries = useQueries({
    queries: syncRuns.map((run) => ({
      queryKey: queryKeys.integrations.sync(run.connection_id, run.sync_run_id),
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        integrationsApi.getSync(run.connection_id, run.sync_run_id, { signal }),
      refetchInterval: (query: { state: { data?: IntegrationSyncRun } }) => {
        const polled = query.state.data;
        if (!polled) return SYNC_RUN_POLL_MS;
        return isActiveSyncRun(polled.status) ? SYNC_RUN_POLL_MS : false;
      },
    })),
  });

  const runsEnqueued = syncRuns.length > 0;
  const allTerminal =
    runsEnqueued &&
    runQueries.every((query) => query.data !== undefined && !isActiveSyncRun(query.data.status));
  const syncing = runsEnqueued && !allTerminal;
  const syncOutcome = !allTerminal
    ? null
    : runQueries.every((query) => query.data && isSucceededSyncRun(query.data.status))
      ? 'succeeded'
      : 'failed';

  // Every queued run is terminal: the new projection is (being) persisted —
  // invalidate the traffic queries (and the connections' last-synced note).
  // (F5 idiom: the terminal transition only invalidates — the outcome banner
  // above is derived from the polled statuses, no state mirror.)
  useEffect(() => {
    if (!allTerminal) return;
    void queryClient.invalidateQueries({ queryKey: queryKeys.traffic.all });
    void queryClient.invalidateQueries({ queryKey: queryKeys.integrations.all });
  }, [allTerminal, queryClient]);

  const connections = connectionsQuery.data ?? [];
  const lastSynced = connections.reduce<string | null>((acc, connection) => {
    if (!connection.last_synced_at) return acc;
    return acc === null || connection.last_synced_at > acc ? connection.last_synced_at : acc;
  }, null);

  const toolbarNote =
    syncing && syncStartedAt
      ? `Started ${formatSyncTimestamp(syncStartedAt)}`
      : lastSynced
        ? `Last synced ${formatSyncTimestamp(lastSynced)}`
        : 'Never synced';

  if (isProjectLoading || (Boolean(projectId) && dashboardQuery.isLoading)) {
    return <TrafficSkeleton />;
  }

  if (!projectId) {
    return <Alert tone="info">Select or create a project to see its traffic.</Alert>;
  }

  if (dashboardQuery.isError) {
    return (
      <Alert tone="danger">Could not load traffic data. Check your connection and try again.</Alert>
    );
  }

  const dashboard = dashboardQuery.data as TrafficDashboard;
  const empty = isEmptyDashboard(dashboard);

  const syncBanner = syncing ? (
    <Alert tone="info" hideIcon>
      <span className="flex items-center gap-2" data-testid="sync-status-banner">
        <Loader2 className="size-4 shrink-0 animate-spin" aria-hidden />
        <span>
          Sync in progress — refreshing Google Search Console and GA4 data. Charts and tables update
          when the sync completes.
        </span>
      </span>
    </Alert>
  ) : null;

  const toolbar = (
    <TrafficToolbar
      range={range}
      onChangeRange={setRange}
      granularity={granularity}
      onChangeGranularity={setGranularity}
      note={toolbarNote}
      syncing={syncing}
      syncPending={syncMutation.isPending}
      onSyncNow={() => syncMutation.mutate()}
    />
  );

  // No persisted snapshot at all (default mode): the project has never
  // projected traffic — the connect/first-sync empty state (mockup).
  if (empty && range === 'latest') {
    return (
      <div className="grid gap-6">
        {syncBanner}
        {syncMutation.isError ? (
          <Alert tone="danger">{errorMessage(syncMutation.error)}</Alert>
        ) : null}
        {syncOutcome === 'failed' ? (
          <Alert tone="warning">
            Sync finished with errors. Check Settings → Integrations for the provider error, then
            try again.
          </Alert>
        ) : null}
        <TrafficEmptyState
          hasConnections={connections.length > 0}
          syncing={syncing || syncMutation.isPending}
          onSyncNow={() => syncMutation.mutate()}
        />
      </div>
    );
  }

  // A bounded preset with no matching persisted window: surfaced honestly
  // (read endpoints serve persisted snapshot windows only — never recompute).
  if (empty) {
    return (
      <div className="grid gap-6">
        {toolbar}
        {syncBanner}
        <Alert tone="info">
          No synced snapshot covers {formatWindowDate(windowBounds.from ?? '')} –{' '}
          {formatWindowDate(windowBounds.to ?? '')} yet. Traffic serves persisted sync windows only
          — switch to the latest synced window or run a sync.
        </Alert>
      </div>
    );
  }

  const tableKey = `${windowBounds.from ?? ''}|${windowBounds.to ?? ''}`;

  return (
    <div className="grid gap-6">
      {toolbar}
      {syncBanner}
      {syncNotice ? <Alert tone="info">{syncNotice}</Alert> : null}
      {syncMutation.isError ? (
        <Alert tone="danger">{errorMessage(syncMutation.error)}</Alert>
      ) : null}
      {syncOutcome === 'succeeded' ? (
        <Alert tone="success">Sync complete — charts and tables now render the new snapshot.</Alert>
      ) : null}
      {syncOutcome === 'failed' ? (
        <Alert tone="warning">
          Sync finished with errors — previously imported data is unchanged. Check Settings →
          Integrations for details.
        </Alert>
      ) : null}

      <UnifiedPerformanceCard dashboard={dashboard} granularity={granularity} />

      <PagesTable
        key={`pages-${tableKey}`}
        projectId={projectId}
        from={windowBounds.from}
        to={windowBounds.to}
      />
      <QueriesTable
        key={`queries-${tableKey}`}
        projectId={projectId}
        from={windowBounds.from}
        to={windowBounds.to}
      />
    </div>
  );
}
