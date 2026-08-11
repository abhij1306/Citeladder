'use client';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { MutationNotice } from '@/components/ui/mutation-notice';
import { SiteHealthDashboardLayout } from '@/components/site-health/dashboard-layout';
import { ScreenHeader, ScreenSkeleton } from '@/components/site-health/screen-states';
import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import { useProjectContext } from '@/lib/project/project-context';
import { useSiteHealthScreen } from '@/lib/site-health/use-site-health-screen';
import { CrawlIntakeDialog } from '@/components/site-health/crawl-intake-dialog';
import { useState } from 'react';

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
  const { activeProject, isLoading: projectLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;
  const [intakeOpen, setIntakeOpen] = useState(false);

  const screen = useSiteHealthScreen(projectId);
  const {
    entitlementQuery,
    dashboardQuery,
    phase,
    crawl,
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

  // A 'resolving' phase means one of the three inputs the phase reads has not
  // settled yet. Holding the skeleton for that beat is the whole point of the
  // explicit phase: rendering a guess and correcting it is what made the screen
  // visibly flip between the URL list and the analysis view.
  if (entitlementQuery.isLoading || dashboardQuery.isLoading || phase === 'resolving') {
    const label = entitlementQuery.isLoading
      ? 'Checking Site Health access…'
      : 'Loading your latest Site Health crawl…';
    return <ScreenSkeleton label={label} />;
  }

  // Two header controls, on simple rules rather than a phase switch:
  //
  //  - Export, whenever a crawl exists. It was gated on `phase === 'dashboard'`,
  //    so a cancelled or still-running crawl offered no way to take the rows
  //    already collected — exactly when a user most wants them.
  //  - Start discovery, only when there is no crawl to act on. Once one exists,
  //    every crawl action (continue discovery, analyze, re-crawl) lives
  //    together in the phase-controls card rather than being split between
  //    there and the page header.
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
    </div>
  ) : (
    <Button size="sm" onClick={() => setIntakeOpen(true)} disabled={startPending}>
      {startPending ? 'Starting…' : 'Start discovery'}
    </Button>
  );

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
          notice={mutationNoticeForError(cancelMutation.error, { action: 'cancel the crawl' })}
          onRetry={cancelCrawl}
        />
      ) : null}
      {stalled ? (
        // We have stopped polling this crawl, so say so rather than leaving a
        // progress state that silently never advances. Whatever it managed to
        // analyze is still below; refreshing picks up a late server-side
        // resolution.
        <Alert tone="warning">
          This crawl hasn&apos;t reported progress for a while and may have stopped. Any results
          collected so far are shown below — refresh to check again, or start a new crawl.
        </Alert>
      ) : null}
      <CrawlIntakeDialog
        projectId={projectId}
        open={intakeOpen}
        advancedControlsEnabled={Boolean(entitlementQuery.data?.advanced_controls_enabled)}
        onClose={() => setIntakeOpen(false)}
        onStart={startCrawl}
      />

      {/* ONE screen. The Site Intelligence workspace used to wrap this whole
          dashboard as its "Pages" tab — the old screen nested inside the new
          one, two live information architectures over the same crawl. The
          workspace and its five panels are deleted; Site Health is Site
          Health, and issues live on the Issues screen. */}
      <SiteHealthDashboardLayout
        screen={screen}
        entitlement={entitlementQuery.data!}
        projectId={projectId}
        onRecrawl={() => setIntakeOpen(true)}
      />
    </div>
  );
}
