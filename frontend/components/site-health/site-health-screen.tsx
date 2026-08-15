'use client';

import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { MutationNotice } from '@/components/ui/mutation-notice';
import { SiteHealthDashboardLayout } from '@/components/site-health/dashboard-layout';
import { LinkGraphPanel } from '@/components/site-health/link-graph-panel';
import { ScreenHeader, ScreenSkeleton } from '@/components/site-health/screen-states';
import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import { useProjectContext } from '@/lib/project/project-context';
import { useSiteHealthScreen } from '@/lib/site-health/use-site-health-screen';

/**
 * Site Health screen container (Slice 7).
 *
 * Resolves the active project, then delegates all data orchestration
 * (entitlement, dashboard, pages, mutations, export, phase resolution) to
 * `useSiteHealthScreen` and rendering to the canonical
 * `SiteHealthDashboardLayout` — one always-mounted screen whose sections
 * update in place across the discover → select → analyze → scored flow. The
 * header offers the single primary control (`primaryAction`) so start/cancel/
 * re-crawl is available from the same place at every point.
 */
export function SiteHealthScreen() {
  const [tab, setTab] = useState<'pages' | 'link-graph'>('pages');
  const { activeProject, isLoading: projectLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;

  const screen = useSiteHealthScreen(projectId);
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

  if (projectLoading) {
    return <ScreenSkeleton label="Loading your Site Health project…" />;
  }

  if (!projectId) {
    return (
      <div className="grid gap-6">
        <ScreenHeader />
        <Alert tone="info">Select or create a project to analyze its site health.</Alert>
      </div>
    );
  }

  // Error states must precede the resolving skeleton. A failed entitlement
  // query deliberately resolves to no access mode, which also produces the
  // fail-closed `resolving` phase. Checking the phase first made this branch
  // unreachable and left the route looking as though it was loading forever.
  if (entitlementQuery.isError || dashboardQuery.isError) {
    return (
      <div className="grid gap-6">
        <ScreenHeader />
        <Alert tone="danger">Could not load Site Health. Please refresh.</Alert>
      </div>
    );
  }

  if (entitlementQuery.data?.resolver_status === 'entitlement_unresolved') {
    return (
      <div className="grid gap-6">
        <ScreenHeader />
        <Alert tone="warning">
          Site Health access could not be resolved. Refresh to try again, or contact your workspace
          administrator if this continues.
        </Alert>
      </div>
    );
  }

  // A 'resolving' phase means the server dashboard projection has not settled
  // yet. Holding the skeleton for that beat avoids rendering a client guess.
  if (entitlementQuery.isLoading || dashboardQuery.isLoading || phase === 'resolving') {
    const label = entitlementQuery.isLoading
      ? 'Checking Site Health access…'
      : 'Loading your latest Site Health crawl…';
    return <ScreenSkeleton label={label} />;
  }

  // A crawl has one contextual action. Before the first run it lives in the
  // empty-state card; afterwards the header changes from Stop to Run new crawl
  // solely from the persisted crawl status. Export remains secondary.
  const headerActions = crawl ? (
    <div className="flex items-center gap-2">
      <Button
        variant="secondary"
        size="sm"
        onClick={() => runExport('csv', 'pages')}
        disabled={exporting}
      >
        {exporting ? 'Exporting…' : 'Export'}
      </Button>
      {active ? (
        <Button
          variant="destructive"
          size="sm"
          onClick={cancelCrawl}
          disabled={cancelMutation.isPending}
        >
          {cancelMutation.isPending ? 'Stopping…' : 'Stop crawl'}
        </Button>
      ) : (
        <Button size="sm" onClick={() => startCrawl()} disabled={startPending}>
          {startPending ? 'Starting…' : 'Run new crawl'}
        </Button>
      )}
    </div>
  ) : undefined;

  return (
    <div className="grid min-w-0 gap-6">
      <ScreenHeader actions={headerActions} />

      {exportError ? <Alert tone="danger">{exportError}</Alert> : null}
      {createMutation.isError ? (
        // A4: recrawl/start — 4xx verbatim (e.g. a crawl is already running),
        // transient failures get the retry affordance.
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
      <div
        className="border-border flex gap-1 border-b"
        role="tablist"
        aria-label="Website analysis"
      >
        {(
          [
            ['pages', 'Pages'],
            ['link-graph', 'Link Graph'],
          ] as const
        ).map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="tab"
            aria-selected={tab === value}
            className={`min-h-10 border-b-2 px-3 text-sm font-medium transition-colors ${tab === value ? 'border-accent text-foreground' : 'text-muted hover:text-foreground border-transparent'}`}
            onClick={() => setTab(value)}
          >
            {label}
          </button>
        ))}
      </div>
      {/* ONE screen. The Site Intelligence workspace used to wrap this whole
          dashboard as its "Pages" tab — the old screen nested inside the new
          one, two live information architectures over the same crawl. The
          workspace and its five panels are deleted; Site Health is Site
          Health, and issues live on the Issues screen. */}
      {tab === 'pages' ? (
        <SiteHealthDashboardLayout screen={screen} entitlement={entitlementQuery.data!} />
      ) : crawl ? (
        <LinkGraphPanel projectId={projectId} crawlId={crawl.id} />
      ) : (
        <Alert tone="info">Run a crawl before opening the Website Link Graph.</Alert>
      )}
    </div>
  );
}
