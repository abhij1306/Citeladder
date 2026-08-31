'use client';

import { type ReactNode, useMemo } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { MutationNotice } from '@/components/ui/mutation-notice';
import { Tabs } from '@/components/ui/tabs';
import { SiteHealthDashboardLayout } from '@/components/site-health/dashboard-layout';
import { AeoReadinessPanel } from '@/components/site-health/aeo-readiness-panel';
import { ArchitecturePanel } from '@/components/site-health/architecture-panel';
import { ChangesPanel } from '@/components/site-health/changes-panel';
import { OverviewPanel } from '@/components/site-health/overview-panel';
import { ScreenHeader, ScreenSkeleton } from '@/components/site-health/screen-states';
import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import { useProjectContext } from '@/lib/project/project-context';
import { useSiteHealthScreen } from '@/lib/site-health/use-site-health-screen';
import { stringUrlCodec, useUrlState } from '@/lib/navigation/url-state';

export function SiteHealthScreen() {
  const { activeProject, isLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;
  const screen = useSiteHealthScreen(projectId);
  if (isLoading) return <ScreenSkeleton label="Loading your Site Health project…" />;
  if (!projectId)
    return (
      <ScreenMessage tone="info">
        Select or create a project to analyze its site health.
      </ScreenMessage>
    );
  return <LoadedSiteHealthScreen projectId={projectId} screen={screen} />;
}

function LoadedSiteHealthScreen({
  projectId,
  screen,
}: Readonly<{ projectId: string; screen: ReturnType<typeof useSiteHealthScreen> }>) {
  const {
    entitlementQuery,
    dashboardQuery,
    phase,
    crawl,
    active,
    stalled,
    startPending,
    createMutation,
    cancelMutation,
    startCrawl,
    cancelCrawl,
    runExport,
    exporting,
    exportError,
  } = screen;
  const defaultTab: AnalysisTab = phase === 'dashboard' ? 'overview' : 'pages';
  const tabCodec = useMemo(
    () =>
      stringUrlCodec(
        ANALYSIS_TABS.map((item) => item.value),
        defaultTab,
      ),
    [defaultTab],
  );
  const [tab, selectTab] = useUrlState('tab', tabCodec, { clearKeys: ['cursor', 'sort'] });
  const blockingState = screenBlockingState({
    entitlementLoading: entitlementQuery.isLoading,
    dashboardLoading: dashboardQuery.isLoading,
    entitlementError: entitlementQuery.isError,
    dashboardError: dashboardQuery.isError,
    resolverStatus: entitlementQuery.data?.resolver_status,
    phase,
  });
  if (blockingState) return blockingState;
  const headerActions = crawl ? (
    <CrawlActions
      active={active}
      exporting={exporting}
      cancelPending={cancelMutation.isPending}
      startPending={startPending}
      onExport={() => runExport('csv', 'pages')}
      onCancel={cancelCrawl}
      onStart={startCrawl}
    />
  ) : undefined;
  return (
    <div className="grid min-w-0 gap-[var(--workspace-gap)]">
      {exportError ? <Alert tone="danger">{exportError}</Alert> : null}
      {createMutation.isError ? (
        <MutationNotice
          notice={mutationNoticeForError(createMutation.error, { action: 'start a crawl' })}
          onRetry={startCrawl}
        />
      ) : null}
      {cancelMutation.isError ? (
        <MutationNotice
          notice={mutationNoticeForError(cancelMutation.error, { action: 'stop the crawl' })}
          onRetry={cancelCrawl}
        />
      ) : null}
      {stalled ? (
        <Alert tone="warning">
          This crawl has an expired worker lease. Recovery is still being checked; results already
          persisted remain visible below.
        </Alert>
      ) : null}
      <AnalysisTabs tab={tab} setTab={selectTab} actions={headerActions} />
      <AnalysisPanel
        tab={tab}
        crawlId={crawl?.id}
        projectId={projectId}
        screen={screen}
        entitlement={entitlementQuery.data!}
      />
    </div>
  );
}

type AnalysisTab = 'overview' | 'pages' | 'architecture' | 'aeo-readiness' | 'changes';

const ANALYSIS_TABS: ReadonlyArray<{ value: AnalysisTab; label: string }> = [
  { value: 'overview', label: 'Overview' },
  { value: 'pages', label: 'Pages' },
  { value: 'architecture', label: 'Architecture' },
  { value: 'aeo-readiness', label: 'AEO Readiness' },
  { value: 'changes', label: 'Changes' },
];

function AnalysisTabs({
  tab,
  setTab,
  actions,
}: Readonly<{
  tab: string;
  setTab: (tab: AnalysisTab) => void;
  actions?: ReactNode;
}>) {
  // Page actions share the tablist row: the tablist's own block-end rule is
  // suppressed so the row wrapper can carry it across the full width, keeping
  // the selected tab's underline flush with the rule under the buttons.
  return (
    <div className="border-border relative z-10 flex min-h-10 items-center gap-3 border-b">
      <Tabs
        value={tab as AnalysisTab}
        onValueChange={setTab}
        items={ANALYSIS_TABS}
        ariaLabel="Website analysis"
        rootClassName="min-w-0 flex-1"
        className="border-b-0"
      />
      {actions ? <div className="ml-auto flex shrink-0 items-center">{actions}</div> : null}
    </div>
  );
}

function AnalysisPanel({
  tab,
  crawlId,
  projectId,
  screen,
  entitlement,
}: Readonly<{
  tab: string;
  crawlId: string | undefined;
  projectId: string;
  screen: ReturnType<typeof useSiteHealthScreen>;
  entitlement: NonNullable<ReturnType<typeof useSiteHealthScreen>['entitlementQuery']['data']>;
}>) {
  if (tab === 'pages')
    return <SiteHealthDashboardLayout screen={screen} entitlement={entitlement} />;
  if (tab === 'overview' && crawlId)
    return (
      <OverviewPanel
        projectId={projectId}
        crawlId={crawlId}
        crawl={screen.crawl}
        dashboard={screen.dashboardQuery.data}
      />
    );
  // Architecture reads a project-scoped projection, so it renders its own
  // "derived after the crawl finishes" state rather than needing a crawl here.
  if (tab === 'architecture')
    return <ArchitecturePanel key={projectId} projectId={projectId} crawlId={crawlId} />;
  if (tab === 'aeo-readiness' && crawlId)
    return <AeoReadinessPanel projectId={projectId} crawlId={crawlId} />;
  if (tab === 'changes') return <ChangesPanel key={projectId} projectId={projectId} />;
  return <Alert tone="info">Run a crawl before opening Website analysis.</Alert>;
}

function screenBlockingState({
  entitlementLoading,
  dashboardLoading,
  entitlementError,
  dashboardError,
  resolverStatus,
  phase,
}: Readonly<{
  entitlementLoading: boolean;
  dashboardLoading: boolean;
  entitlementError: boolean;
  dashboardError: boolean;
  resolverStatus: string | undefined;
  phase: string;
}>) {
  if (entitlementError || dashboardError)
    return <ScreenMessage tone="danger">Could not load Site Health. Please refresh.</ScreenMessage>;
  if (resolverStatus === 'entitlement_unresolved')
    return (
      <ScreenMessage tone="warning">
        Site Health access could not be resolved. Refresh to try again, or contact your workspace
        administrator if this continues.
      </ScreenMessage>
    );
  if (entitlementLoading || dashboardLoading || phase === 'resolving')
    return (
      <ScreenSkeleton
        label={
          entitlementLoading
            ? 'Checking Site Health access…'
            : 'Loading your latest Site Health crawl…'
        }
      />
    );
  return null;
}

function ScreenMessage({
  tone,
  children,
}: Readonly<{ tone: 'danger' | 'warning' | 'info'; children: string }>) {
  return (
    <div className="grid gap-[var(--workspace-gap)]">
      <ScreenHeader />
      <Alert tone={tone}>{children}</Alert>
    </div>
  );
}
function CrawlActions({
  active,
  exporting,
  cancelPending,
  startPending,
  onExport,
  onCancel,
  onStart,
}: Readonly<{
  active: boolean;
  exporting: boolean;
  cancelPending: boolean;
  startPending: boolean;
  onExport: () => void;
  onCancel: () => void;
  onStart: () => void;
}>) {
  return (
    <div className="flex items-center gap-2">
      <Button variant="secondary" size="sm" onClick={onExport} disabled={exporting}>
        {exporting ? 'Exporting…' : 'Export'}
      </Button>
      {active ? (
        <Button variant="destructive" size="sm" onClick={onCancel} disabled={cancelPending}>
          {cancelPending ? 'Stopping…' : 'Stop crawl'}
        </Button>
      ) : (
        <Button size="sm" onClick={() => onStart()} disabled={startPending}>
          {startPending ? 'Starting…' : 'Run new crawl'}
        </Button>
      )}
    </div>
  );
}
