'use client';

import { useQuery } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { demandApi, type DemandSnapshot } from '@/lib/api/demand';
import { httpErrorStatus } from '@/lib/api/errors';
import { useProjectContext } from '@/lib/project/project-context';

const SIGNAL_LABELS: Record<string, string> = {
  high_impression_low_ctr: 'High-impression, low-click demand',
};

function describeCoverage(value: unknown): string {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return String(value);
  const details = value as Record<string, unknown>;
  const parts: string[] = [];
  if (typeof details.state === 'string') parts.push(details.state);
  if (typeof details.total_pages === 'number' && typeof details.matched_pages === 'number') {
    parts.push(`${details.matched_pages} of ${details.total_pages} pages joined`);
  }
  if (typeof details.join_rate === 'number') parts.push(`${Math.round(details.join_rate * 100)}%`);

  const counts = Object.entries(details)
    .filter(
      (entry): entry is [string, number] =>
        typeof entry[1] === 'number' &&
        !['join_rate', 'total_pages', 'matched_pages'].includes(entry[0]),
    )
    .map(([key, count]) => `${key.replaceAll('_', ' ')} ${count}`);
  return parts.concat(counts).join(' · ') || 'None represented';
}

function Coverage({ coverage }: Readonly<{ coverage: Record<string, unknown> }>) {
  return (
    <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {Object.entries(coverage).map(([source, value]) => (
        <div key={source} className="border-border-subtle rounded-md border p-3">
          <dt className="text-muted text-xs capitalize">{source.replaceAll('_', ' ')}</dt>
          <dd className="text-foreground mt-1 text-sm font-medium">{describeCoverage(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function Signals({ snapshot }: Readonly<{ snapshot: DemandSnapshot }>) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Prioritized signals</CardTitle>
        <CardDescription>
          Every item traces to persisted Search Console or Traffic evidence.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {snapshot.signals.length ? (
          snapshot.signals.map((signal) => (
            <article key={signal.id} className="border-border-subtle rounded-md border p-3">
              <div className="flex flex-wrap justify-between gap-2">
                <h4 className="text-sm font-medium">
                  {SIGNAL_LABELS[signal.signal_type] ?? signal.signal_type}
                </h4>
                <span className="text-muted font-mono text-xs">
                  {signal.priority_score ?? 'unranked'}
                </span>
              </div>
              <p className="text-secondary mt-1 text-sm">
                {signal.topic_cluster || signal.page_url}
              </p>
              {signal.limitations.map((limitation) => (
                <p key={limitation} className="text-muted mt-2 text-xs">
                  {limitation}
                </p>
              ))}
            </article>
          ))
        ) : (
          <p className="text-muted text-sm">
            No active search-demand signals were detected in this evidence window.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function Snapshot({ snapshot }: Readonly<{ snapshot: DemandSnapshot }>) {
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Demand overview</CardTitle>
          <CardDescription>
            {snapshot.window_start}–{snapshot.window_end}; comparisons are descriptive and never
            assert causality.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Coverage coverage={snapshot.coverage} />
        </CardContent>
      </Card>
      <Signals snapshot={snapshot} />
    </div>
  );
}

export function DemandProjection({ panel }: Readonly<{ panel: 'overview' | 'search' }>) {
  const { activeProject, isLoading: projectLoading } = useProjectContext();
  const latest = useQuery({
    queryKey: ['demand', activeProject?.id, 'latest'],
    queryFn: ({ signal }) => demandApi.getLatest(activeProject!.id, { signal }),
    enabled: Boolean(activeProject),
  });

  if (projectLoading || latest.isLoading) {
    return (
      <div className="grid gap-4" aria-busy="true">
        <Skeleton className="h-28" />
        <Skeleton className="h-64" />
      </div>
    );
  }
  if (!activeProject) return <Alert tone="info">Select a project to inspect demand.</Alert>;
  if (latest.isError && httpErrorStatus(latest.error) === 404) {
    return (
      <Alert tone="info">
        No Demand snapshot exists yet. Sync Traffic evidence, then recompute Demand Intelligence.
      </Alert>
    );
  }
  if (latest.isError) return <Alert tone="danger">Demand signals could not be loaded.</Alert>;
  if (!latest.data) return null;

  const snapshot =
    panel === 'search'
      ? {
          ...latest.data,
          signals: latest.data.signals.filter(
            (signal) => signal.signal_type === 'high_impression_low_ctr',
          ),
        }
      : latest.data;
  return <Snapshot snapshot={snapshot} />;
}
