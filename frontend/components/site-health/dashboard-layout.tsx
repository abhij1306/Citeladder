import { InventorySection } from '@/components/site-health/inventory-section';
import { PageKindScores } from '@/components/site-health/page-kind-scores';
import { ScoreSection } from '@/components/site-health/score-section';
import { SiteFactsPanel } from '@/components/site-health/site-facts-panel';
import { StatusStrip } from '@/components/site-health/status-strip';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import type { useSiteHealthScreen } from '@/lib/site-health/use-site-health-screen';
import type { SiteHealthEntitlement } from '@/lib/api/types';

/**
 * The canonical Site Health dashboard layout.
 *
 * ONE composed screen that stays mounted through the entire discover → analyze
 * → scored lifecycle. Phase changes update each section's DATA and
 * mode — they never swap the layout for a different panel, so starting,
 * cancelling, or finishing a crawl visibly updates the screen the user is
 * already on. (The per-URL crawl detail view and the issues screen remain the
 * only other screens in the flow.)
 *
 * Reading order is answer-first: where the crawl stands, what you can do next,
 * the score summary, URL inventory, then page-kind diagnostics.
 */
export function SiteHealthDashboardLayout({
  screen,
  entitlement,
}: Readonly<{
  screen: ReturnType<typeof useSiteHealthScreen>;
  entitlement: SiteHealthEntitlement;
}>) {
  const {
    phase,
    inventoryMode,
    crawl,
    active,
    dashboardQuery,
    pagesQuery,
    projectSelectedTotal,
    projectSelectedError,
    startPending,
    startCrawl,
    cancelMutation,
  } = screen;

  return (
    // `min-w-0` so a wide table inside a section scrolls in its own wrapper
    // instead of widening this column (and every ancestor) to its max-content.
    <div className="grid min-w-0 gap-[var(--workspace-gap)]" data-testid="site-health-canonical">
      {!crawl ? (
        <Card data-testid="site-health-empty">
          <CardContent className="grid justify-items-start gap-3 py-[var(--empty-state-padding)]">
            <div className="grid max-w-2xl gap-1">
              <h2 className="text-foreground text-xl font-medium tracking-[-0.02em]">
                Run your first site crawl
              </h2>
              <p className="text-secondary text-sm">
                Crawl your site to see page health, issues, and recommendations as results arrive.
              </p>
            </div>
            <Button onClick={() => startCrawl()} disabled={startPending}>
              {startPending ? 'Starting…' : 'Run new crawl'}
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          {/* Where the crawl stands. */}
          <StatusStrip
            crawl={crawl}
            phase={phase}
            entitlement={entitlement}
            cancelPending={cancelMutation.isPending}
            startPending={startPending}
            pages={pagesQuery.data?.items ?? []}
            selectedTotal={projectSelectedTotal}
            selectedError={projectSelectedError}
          />

          <ScoreSection crawl={crawl} dashboard={dashboardQuery.data} />
          <InventorySection mode={inventoryMode} crawl={crawl} active={active} />

          <PageKindScores crawl={crawl} dashboard={dashboardQuery.data} />

          <SiteFactsPanel crawl={crawl} dashboard={dashboardQuery.data} />
        </>
      )}
    </div>
  );
}
