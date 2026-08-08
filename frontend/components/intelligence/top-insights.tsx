'use client';

import { useQuery } from '@tanstack/react-query';

import { opportunitiesQueries } from '@/lib/api/opportunities';

import { Insight } from './insight';
import { insightFromOpportunity } from './opportunity-insight';

/**
 * Top insights across all layers, for Overview (§7.1).
 *
 * The ranked list is server-ordered by the deterministic formula — this does
 * not re-sort. Insights without resolvable evidence are dropped before the
 * count is taken, because `Insight` declines to render them (§5) and a count
 * that disagrees with the visible rows is worse than no count.
 */
export function TopInsights({
  projectId,
  limit = 5,
}: Readonly<{ projectId: string; limit?: number }>) {
  const query = useQuery({
    ...opportunitiesQueries.list(projectId, { limit }),
    enabled: Boolean(projectId),
  });

  if (query.isLoading || query.isError || !query.data) return null;

  const insights = query.data.items
    .map(insightFromOpportunity)
    .filter((insight) => insight.evidence !== null);

  if (insights.length === 0) return null;

  return (
    <section aria-label="Top insights" className="flex flex-col gap-3">
      <h2 className="text-foreground text-sm font-semibold">Top insights</h2>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {insights.map((insight) => (
          <Insight key={insight.id} insight={insight} />
        ))}
      </div>
    </section>
  );
}
