'use client';

import { useState } from 'react';

import { InventorySection } from '@/components/site-health/inventory-section';
import { PageKindScores } from '@/components/site-health/page-kind-scores';
import { PhaseControls } from '@/components/site-health/phase-controls';
import { ScoreSection } from '@/components/site-health/score-section';
import { SiteFactsPanel } from '@/components/site-health/site-facts-panel';
import { StatusStrip } from '@/components/site-health/status-strip';
import type { useSiteHealthScreen } from '@/lib/site-health/use-site-health-screen';
import type { SiteHealthEntitlement } from '@/lib/api/types';
import type { PhaseMutation } from '@/components/site-health/phase-controls';

/**
 * The canonical Site Health dashboard layout.
 *
 * ONE composed screen that stays mounted through the entire discover → select
 * → analyze → scored lifecycle. Phase changes update each section's DATA and
 * mode — they never swap the layout for a different panel, so starting,
 * cancelling, or finishing a crawl visibly updates the screen the user is
 * already on. (The per-URL crawl detail view and the issues screen remain the
 * only other screens in the flow.)
 *
 * Reading order is answer-first: where the crawl stands, what you can do next,
 * the scores, then the URL inventory as the drill-down.
 */
export function SiteHealthDashboardLayout({
  screen,
  entitlement,
  projectId,
  onRecrawl,
}: Readonly<{
  screen: ReturnType<typeof useSiteHealthScreen>;
  entitlement: SiteHealthEntitlement;
  projectId: string;
  onRecrawl: () => void;
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
    cancelMutation,
    cancelCrawl,
  } = screen;
  const [lastPhaseMutation, setLastPhaseMutation] = useState<PhaseMutation | null>(null);

  return (
    // `min-w-0` so a wide table inside a section scrolls in its own wrapper
    // instead of widening this column (and every ancestor) to its max-content.
    <div className="grid min-w-0 gap-6" data-testid="site-health-canonical">
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

      {/* What you can do about it: continue discovery, run an analysis batch,
          re-crawl. */}
      <PhaseControls
        screen={screen}
        lastMutation={lastPhaseMutation}
        onMutationStart={setLastPhaseMutation}
        onRecrawl={onRecrawl}
      />

      {/* Scores come BEFORE the URL inventory. They are the crawl-level answer
          ("how healthy is this site") and the inventory is the drill-down;
          rendering them underneath a 25-row table put the headline result
          three screens down and made it look as though scoring had vanished. */}
      <ScoreSection
        crawl={crawl}
        dashboard={dashboardQuery.data}
        pages={pagesQuery.data?.items ?? []}
        // Live running-mean fallback applies whenever analysis may still be
        // producing scores — the analyzing phase, and an ACTIVE crawl already
        // showing a mid-run dashboard projection (phase 'dashboard' via
        // hasScoreData with null metric fields).
        analyzing={phase === 'analyzing' || (phase === 'dashboard' && active)}
        selectedTotal={projectSelectedTotal}
      />

      <PageKindScores crawl={crawl} dashboard={dashboardQuery.data} />

      <InventorySection
        mode={inventoryMode}
        crawl={crawl}
        entitlement={entitlement}
        projectId={projectId}
        active={active}
        onCancel={cancelCrawl}
        cancelPending={cancelMutation.isPending}
      />

      <SiteFactsPanel crawl={crawl} dashboard={dashboardQuery.data} />
    </div>
  );
}
