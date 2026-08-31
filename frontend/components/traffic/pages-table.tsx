'use client';

import { MetricTable } from '@/components/traffic/metric-table';
import { queryKeys } from '@/lib/api/query-keys';
import { trafficApi, type TrafficPageRow } from '@/lib/api/traffic';
import { splitUrlParts } from '@/lib/traffic/traffic';

export function PagesTable({
  projectId,
  from,
  to,
}: Readonly<{ projectId: string; from?: string; to?: string }>) {
  return (
    <MetricTable<TrafficPageRow>
      testId="pages-table"
      title="Top pages"
      description="Canonical URLs by organic clicks · Google Search Console"
      leadLabel="Page"
      emptyMessage="No pages measured for this window."
      errorMessage="Could not load page stats. Check your connection and try again."
      leadSkeletonClassName="h-4 w-64 max-w-full"
      scopeId={projectId}
      queryKey={(sort, cursor) => queryKeys.traffic.pages(projectId, { from, to, sort, cursor })}
      fetchPage={(sort, cursor, signal) =>
        trafficApi.getPages(projectId, { from, to, sort, cursor }, { signal })
      }
      rowKey={(row) => row.canonical_url}
      renderLead={(row) => {
        const parts = splitUrlParts(row.canonical_url);
        return (
          <span className="font-mono text-xs break-all">
            {parts.host ? <span className="text-muted">{parts.host}</span> : null}
            {parts.rest}
          </span>
        );
      }}
    />
  );
}
