'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { Loader2 } from 'lucide-react';
import { useState } from 'react';

import { TrafficEmptyState } from '@/components/traffic/empty-state';
import { PagesTable } from '@/components/traffic/pages-table';
import { QueriesTable } from '@/components/traffic/queries-table';
import { TrafficToolbar } from '@/components/traffic/traffic-toolbar';
import { UnifiedPerformanceCard } from '@/components/traffic/unified-performance-card';
import { Alert } from '@/components/ui/alert';
import { NestedTabs } from '@/components/ui/nested-tabs';
import { Skeleton } from '@/components/ui/skeleton';
import { integrationsApi } from '@/lib/api/integrations';
import { queryKeys } from '@/lib/api/query-keys';
import { trafficApi, type TrafficDashboard } from '@/lib/api/traffic';
import { useProjectContext } from '@/lib/project/project-context';
import {
  formatSyncTimestamp,
  formatWindowDate,
  isEmptyDashboard,
  rangeToWindow,
  type TrafficGranularity,
  type TrafficRange,
} from '@/lib/traffic/traffic';

import { useTrafficSync } from './use-traffic-sync';

const TRAFFIC_TABLE_TABS = [
  { id: 'pages', label: 'Top pages' },
  { id: 'queries', label: 'Top queries' },
] as const;
type TrafficTableView = (typeof TRAFFIC_TABLE_TABS)[number]['id'];

type DashboardQuery = ReturnType<typeof useQuery<TrafficDashboard>>;
type ConnectionsQuery = ReturnType<
  typeof useQuery<Awaited<ReturnType<typeof integrationsApi.list>>>
>;

export function TrafficSkeleton() {
  return (
    <div className="grid gap-6" aria-busy="true" data-testid="traffic-skeleton">
      <div className="flex flex-wrap items-center gap-2">
        <Skeleton className="h-8 w-40 rounded-full" />
        <Skeleton className="h-10 w-60 rounded-full" />
        <Skeleton className="ml-auto h-8 w-32 rounded-full" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {Array.from({ length: 6 }, (_, index) => (
          <Skeleton key={index} className="h-26" />
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

/** Coordinates project-scoped data; rendering lives in cohesive dashboard sections. */
export function TrafficScreen() {
  const { activeProject, isLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;
  const workspaceId = activeProject?.workspace_id ?? null;
  const [range, setRange] = useState<TrafficRange>('latest');
  const [granularity, setGranularity] = useState<TrafficGranularity>('day');
  const bounds = rangeToWindow(range);
  const dashboard = useQuery({
    queryKey: queryKeys.traffic.dashboard(projectId ?? '', { ...bounds, granularity }),
    queryFn: ({ signal }) =>
      trafficApi.getTraffic(projectId ?? '', { ...bounds, granularity }, { signal }),
    enabled: Boolean(projectId),
    placeholderData: keepPreviousData,
  });
  const connections = useQuery({
    queryKey: queryKeys.integrations.connections(workspaceId),
    queryFn: ({ signal }) => integrationsApi.list({ signal }),
    enabled: Boolean(workspaceId),
  });

  return (
    <TrafficDataGate
      isProjectLoading={isLoading}
      projectId={projectId}
      dashboard={dashboard}
      connections={connections}
      range={range}
      setRange={setRange}
      granularity={granularity}
      setGranularity={setGranularity}
    />
  );
}

function TrafficDataGate({
  isProjectLoading,
  projectId,
  dashboard,
  connections,
  range,
  setRange,
  granularity,
  setGranularity,
}: Readonly<{
  isProjectLoading: boolean;
  projectId: string | null;
  dashboard: DashboardQuery;
  connections: ConnectionsQuery;
  range: TrafficRange;
  setRange: (range: TrafficRange) => void;
  granularity: TrafficGranularity;
  setGranularity: (value: TrafficGranularity) => void;
}>) {
  if (isProjectLoading || (Boolean(projectId) && dashboard.isLoading)) return <TrafficSkeleton />;
  if (!projectId) return <Alert tone="info">Select or create a project to see its traffic.</Alert>;
  if (dashboard.isError)
    return (
      <Alert tone="danger">Could not load traffic data. Check your connection and try again.</Alert>
    );
  return (
    <TrafficDashboard
      projectId={projectId}
      dashboard={dashboard.data as TrafficDashboard}
      dashboardFetching={dashboard.isFetching}
      connections={connections.data ?? []}
      range={range}
      setRange={setRange}
      granularity={granularity}
      setGranularity={setGranularity}
    />
  );
}

function TrafficDashboard({
  projectId,
  dashboard,
  dashboardFetching,
  connections,
  range,
  setRange,
  granularity,
  setGranularity,
}: Readonly<{
  projectId: string;
  dashboard: TrafficDashboard;
  dashboardFetching: boolean;
  connections: Awaited<ReturnType<typeof integrationsApi.list>>;
  range: TrafficRange;
  setRange: (range: TrafficRange) => void;
  granularity: TrafficGranularity;
  setGranularity: (value: TrafficGranularity) => void;
}>) {
  const sync = useTrafficSync(projectId);
  const lastSynced = latestSync(connections);
  const note = syncNote(sync.syncing, sync.startedAt, lastSynced);
  const toolbar = (
    <TrafficToolbar
      range={range}
      onChangeRange={setRange}
      granularity={granularity}
      onChangeGranularity={setGranularity}
      note={note}
      syncing={sync.syncing}
      syncPending={sync.mutation.isPending}
      fetching={dashboardFetching}
      onSyncNow={() => sync.mutation.mutate()}
    />
  );
  if (isEmptyDashboard(dashboard))
    return (
      <EmptyTrafficDashboard
        range={range}
        toolbar={toolbar}
        connections={connections}
        sync={sync}
      />
    );
  return (
    <PopulatedTrafficDashboard
      projectId={projectId}
      dashboard={dashboard}
      dashboardFetching={dashboardFetching}
      range={range}
      toolbar={toolbar}
      sync={sync}
    />
  );
}

function EmptyTrafficDashboard({
  range,
  toolbar,
  connections,
  sync,
}: Readonly<{
  range: TrafficRange;
  toolbar: React.ReactNode;
  connections: Awaited<ReturnType<typeof integrationsApi.list>>;
  sync: ReturnType<typeof useTrafficSync>;
}>) {
  // Both dates describe the same persisted snapshot window.
  const bounds = rangeToWindow(range);
  if (range !== 'latest')
    return (
      <div className="grid gap-6">
        {toolbar}
        <SyncBanner active={sync.syncing} />
        <Alert tone="info">
          No synced snapshot covers {formatWindowDate(bounds.from ?? '')} –{' '}
          {formatWindowDate(bounds.to ?? '')} yet. Traffic serves persisted sync windows only —
          switch to the latest synced window or run a sync.
        </Alert>
      </div>
    );
  return (
    <div className="grid gap-6">
      <SyncBanner active={sync.syncing} />
      <TrafficAlerts sync={sync} includeSuccess={false} />
      <TrafficEmptyState
        hasConnections={connections.length > 0}
        syncing={sync.syncing || sync.mutation.isPending}
        onSyncNow={() => sync.mutation.mutate()}
      />
    </div>
  );
}

function PopulatedTrafficDashboard({
  projectId,
  dashboard,
  dashboardFetching,
  range,
  toolbar,
  sync,
}: Readonly<{
  projectId: string;
  dashboard: TrafficDashboard;
  dashboardFetching: boolean;
  range: TrafficRange;
  toolbar: React.ReactNode;
  sync: ReturnType<typeof useTrafficSync>;
}>) {
  const [tableView, setTableView] = useState<TrafficTableView>('pages');
  const bounds = rangeToWindow(range);
  // Retain the current context project id while React Query shows previous data
  // during a project switch; placeholder dashboard data may belong to the old project.
  const tableKey = `${bounds.from ?? ''}|${bounds.to ?? ''}`;
  return (
    <div className="grid gap-6">
      {toolbar}
      <SyncBanner active={sync.syncing} />
      <TrafficAlerts sync={sync} />
      <div aria-busy={dashboardFetching} className="grid gap-6">
        <UnifiedPerformanceCard dashboard={dashboard} granularity={dashboard.granularity} />
        <NestedTabs
          tabs={TRAFFIC_TABLE_TABS}
          activeTab={tableView}
          onSelectTab={setTableView}
          ariaLabel="Traffic rankings"
          idPrefix="traffic-rankings"
          panel={
            <TrafficRankings
              projectId={projectId}
              tableView={tableView}
              tableKey={tableKey}
              from={bounds.from}
              to={bounds.to}
            />
          }
        />
      </div>
    </div>
  );
}

function TrafficRankings({
  projectId,
  tableView,
  tableKey,
  from,
  to,
}: Readonly<{
  projectId: string;
  tableView: TrafficTableView;
  tableKey: string;
  from: string | undefined;
  to: string | undefined;
}>) {
  return (
    <div className="grid gap-3">
      <p className="text-muted text-xs">
        Rankings use totals for the selected date range. Chart interval does not change their order.
      </p>
      {tableView === 'pages' ? (
        <PagesTable key={`pages-${tableKey}`} projectId={projectId} from={from} to={to} />
      ) : (
        <QueriesTable key={`queries-${tableKey}`} projectId={projectId} from={from} to={to} />
      )}
    </div>
  );
}

function latestSync(connections: Awaited<ReturnType<typeof integrationsApi.list>>) {
  return connections.reduce<string | null>(
    (latest, connection) =>
      !connection.last_synced_at || (latest && connection.last_synced_at <= latest)
        ? latest
        : connection.last_synced_at,
    null,
  );
}
function syncNote(syncing: boolean, startedAt: string | null, lastSynced: string | null) {
  if (syncing && startedAt) return `Started ${formatSyncTimestamp(startedAt)}`;
  return lastSynced ? `Last synced ${formatSyncTimestamp(lastSynced)}` : 'Never synced';
}
function SyncBanner({ active }: Readonly<{ active: boolean }>) {
  return active ? (
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
}
function errorMessage(error: unknown) {
  return error instanceof Error && error.message
    ? error.message
    : 'Something went wrong. Please try again.';
}
function TrafficAlerts({
  sync,
  includeSuccess = true,
}: Readonly<{ sync: ReturnType<typeof useTrafficSync>; includeSuccess?: boolean }>) {
  return (
    <>
      {sync.notice ? <Alert tone="info">{sync.notice}</Alert> : null}
      {sync.mutation.isError ? (
        <Alert tone="danger">{errorMessage(sync.mutation.error)}</Alert>
      ) : null}
      {includeSuccess && sync.outcome === 'succeeded' ? (
        <Alert tone="success">Sync complete — charts and tables now render the new snapshot.</Alert>
      ) : null}
      {sync.outcome === 'failed' ? (
        <Alert tone="warning">
          Sync finished with errors — previously imported data is unchanged. Check Settings →
          Integrations for details.
        </Alert>
      ) : null}
    </>
  );
}
