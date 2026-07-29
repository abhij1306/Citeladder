'use client';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { SiteHealthDashboardLayout } from '@/components/site-health/dashboard-layout';
import { ScreenHeader, ScreenSkeleton } from '@/components/site-health/screen-states';
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
  const { activeProject, isLoading: projectLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;

  const screen = useSiteHealthScreen(projectId);
  const {
    entitlementQuery,
    dashboardQuery,
    phase,
    primaryAction,
    active,
    stalled,
    startPending,
    createMutation,
    startCrawl,
    runExport,
    exporting,
    exportError,
  } = screen;

  // A 'resolving' phase means one of the three inputs the phase reads has not
  // settled yet. Holding the skeleton for that beat is the whole point of the
  // explicit phase: rendering a guess and correcting it is what made the screen
  // visibly flip between the URL list and the analysis view.
  if (
    projectLoading ||
    (projectId && (entitlementQuery.isLoading || dashboardQuery.isLoading || phase === 'resolving'))
  ) {
    return <ScreenSkeleton />;
  }

  if (!projectId) {
    return (
      <div className="grid gap-6">
        <ScreenHeader />
        <Alert tone="info">Select or create a project to analyze its site health.</Alert>
      </div>
    );
  }

  if (entitlementQuery.isError || dashboardQuery.isError) {
    return (
      <div className="grid gap-6">
        <ScreenHeader />
        <Alert tone="danger">Could not load Site Health. Please refresh.</Alert>
      </div>
    );
  }

  const primaryButton = (() => {
    switch (primaryAction) {
      case 'start':
        return (
          <Button size="sm" onClick={startCrawl} disabled={startPending}>
            {startPending ? 'Starting…' : 'Start discovery'}
          </Button>
        );
      case 'cancel':
        // Cancellation lives beside the active inventory/table controls, not
        // in the global page header.
        return null;
      case 'recrawl':
        return (
          <Button size="sm" onClick={startCrawl} disabled={startPending || active}>
            {startPending
              ? 'Starting…'
              : phase === 'terminal'
                ? 'Start a new crawl'
                : 'Re-crawl now'}
          </Button>
        );
      default:
        return null;
    }
  })();

  const headerActions =
    primaryButton || phase === 'dashboard' ? (
      <div className="flex items-center gap-2">
        {phase === 'dashboard' ? (
          <Button
            variant="secondary"
            size="sm"
            onClick={() => runExport('csv', 'pages')}
            disabled={exporting}
          >
            {exporting ? 'Exporting…' : 'Export'}
          </Button>
        ) : null}
        {primaryButton}
      </div>
    ) : null;

  return (
    <div className="grid gap-6">
      <ScreenHeader actions={headerActions} />

      {exportError ? <Alert tone="danger">{exportError}</Alert> : null}
      {createMutation.isError ? (
        <Alert tone="danger">Could not start a crawl. It may already be running.</Alert>
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

      <SiteHealthDashboardLayout
        screen={screen}
        entitlement={entitlementQuery.data!}
        projectId={projectId}
      />
    </div>
  );
}
