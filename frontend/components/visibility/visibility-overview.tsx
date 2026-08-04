'use client';

import type { UseQueryResult } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { Alert } from '@/components/ui/alert';
import { DashboardSkeleton } from '@/components/visibility/dashboard-skeleton';
import { EngineComparison } from '@/components/visibility/engine-comparison';
import { OverviewSummary } from '@/components/visibility/overview-summary';
import { RankingsTable } from '@/components/visibility/rankings-table';
import { PromptInsights } from '@/components/visibility/prompt-insights';
import type { ObservedCompetitor, PromptMetricItem, Visibility } from '@/lib/api/types';
import type { VisibilityFilters } from '@/lib/visibility/dashboard';

/**
 * Overview tab — the selected-run Visibility composition (the default tab).
 *
 * Reads the same `GET /projects/{id}/visibility?audit_id=` selected-run
 * projection as before and preserves the same loading / error / empty
 * behavior; only the composition changed:
 *
 *   summary line (headline % + inline metrics)
 *   row 1: Competitors table                 | Share of answers
 *   row 2: By model table
 *
 * The standalone Visibility Score card and the per-engine ring grid are
 * retired from Overview — the headline percentage now lives in the summary
 * line, and the per-model numbers read far better as a table (see
 * `EngineComparison`, whose data logic is unchanged).
 *
 * It does NOT append trend charts or raw evidence below the fold — those belong
 * to the Trends / Mentions / Search-queries tabs.
 */
export function VisibilityOverview({
  query,
  engineFilter,
  brandName,
  brandHistory,
  projectId,
  promptQuery,
  suggestionsQuery,
}: Readonly<{
  query: UseQueryResult<Visibility, unknown>;
  engineFilter: VisibilityFilters['engine'];
  /** Active project's brand name — used by the summary sentence. */
  brandName: string;
  /**
   * Real per-brand visibility history for the Competitors sparklines, when the
   * cross-run series is already cached. Undefined simply hides the column.
   */
  brandHistory?: ReadonlyMap<string, number[]>;
  projectId: string;
  promptQuery: UseQueryResult<PromptMetricItem[], unknown>;
  suggestionsQuery: UseQueryResult<ObservedCompetitor[], unknown>;
}>) {
  const visibility = query.data;

  // Precedence: data wins; otherwise a terminal error shows only the alert
  // (no skeleton), and everything else is still loading.
  let body: ReactNode;
  if (visibility) {
    body = (
      <>
        <OverviewSummary visibility={visibility} brandName={brandName} />
        <RankingsTable visibility={visibility} history={brandHistory} />
        <EngineComparison visibility={visibility} filter={engineFilter} />
        <PromptInsights
          projectId={projectId}
          promptQuery={promptQuery}
          suggestionsQuery={suggestionsQuery}
        />
      </>
    );
  } else if (query.isError) {
    body = null;
  } else {
    body = <DashboardSkeleton />;
  }

  return (
    <div className="grid gap-3">
      {query.isError ? (
        <Alert tone="danger">
          Could not load visibility metrics for this run. Try another run or refresh.
        </Alert>
      ) : null}

      {body}
    </div>
  );
}
