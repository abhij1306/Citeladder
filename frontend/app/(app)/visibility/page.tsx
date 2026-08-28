'use client';

import { Suspense } from 'react';

import { TooltipProvider } from '@/components/ui/tooltip';
import { DashboardSkeleton } from '@/components/visibility/dashboard-skeleton';
import { VisibilityDashboard } from '@/components/visibility/visibility-dashboard';

/**
 * Visibility workspace screen (three-tab IA).
 *
 * One workspace shell with a shared filter bar above an accessible tablist and
 * exactly three focused panels:
 *   - **Trends** (default): cross-run Visibility Score, Share of Voice, ranking
 *     movement, latest model comparison, and prompt movement, from
 *     `GET /projects/{id}/visibility/trends`.
 *   - **Mentions & Citations**: persisted brand/competitor mentions and
 *     classified citation records with task/analysis/artifact provenance.
 *   - **Query Fanout**: frozen prompts, provider-generated search queries, and
 *     search-count / text-availability states.
 * The two evidence tabs share the persisted
 * `GET /projects/{id}/visibility/evidence` dataset. Sentiment + Avg Position
 * stay explicitly not measured (decision B-2). There are no
 * Sources, Topics, or Sentiment tabs. All endpoints go through `visibility.ts`,
 * scoped to the active project from the F5 context. The page title renders in
 * the top bar (F5), so there is no in-page header block.
 */
export default function VisibilityPage() {
  return (
    <TooltipProvider>
      <div className="grid gap-[var(--workspace-gap)]">
        <Suspense fallback={<DashboardSkeleton />}>
          <VisibilityDashboard />
        </Suspense>
      </div>
    </TooltipProvider>
  );
}
