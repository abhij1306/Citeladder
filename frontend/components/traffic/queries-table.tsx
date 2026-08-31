'use client';

import { MetricTable } from '@/components/traffic/metric-table';
import { queryKeys } from '@/lib/api/query-keys';
import { trafficApi, type TrafficQueryRow } from '@/lib/api/traffic';

export function QueriesTable({
  projectId,
  from,
  to,
}: Readonly<{ projectId: string; from?: string; to?: string }>) {
  return (
    <MetricTable<TrafficQueryRow>
      testId="queries-table"
      title="Top queries"
      description="Normalized search queries by organic clicks · Google Search Console"
      leadLabel="Query"
      emptyMessage="No queries measured for this window."
      errorMessage="Could not load query stats. Check your connection and try again."
      leadSkeletonClassName="h-4 w-48 max-w-full"
      scopeId={projectId}
      queryKey={(sort, cursor) => queryKeys.traffic.queries(projectId, { from, to, sort, cursor })}
      fetchPage={(sort, cursor, signal) =>
        trafficApi.getQueries(projectId, { from, to, sort, cursor }, { signal })
      }
      rowKey={(row) => row.normalized_query}
      renderLead={(row) => row.normalized_query}
    />
  );
}
