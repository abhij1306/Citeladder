'use client';

import { useQuery } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { demandApi, type DemandSnapshot } from '@/lib/api/demand';
import { httpErrorStatus } from '@/lib/api/errors';
import { formatWindowDate } from '@/lib/format';
import { useProjectContext } from '@/lib/project/project-context';

type DemandSignal = DemandSnapshot['signals'][number];

function numericMetric(signal: DemandSignal, key: string): number | null {
  const value = signal.metrics[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function signalTarget(signal: DemandSignal): { kind: 'Query' | 'Page'; value: string } {
  const targetKind = signal.evidence.target_kind;
  const target = signal.evidence.target;
  if (targetKind === 'page') {
    return { kind: 'Page', value: typeof target === 'string' ? target : signal.page_url };
  }
  return { kind: 'Query', value: typeof target === 'string' ? target : signal.topic_cluster };
}

function formatCtr(signal: DemandSignal): string {
  const persistedCtr = numericMetric(signal, 'ctr');
  if (persistedCtr !== null) return `${(persistedCtr * 100).toFixed(1)}%`;
  const impressions = numericMetric(signal, 'impressions');
  const clicks = numericMetric(signal, 'clicks');
  if (impressions === null || clicks === null || impressions === 0) return '—';
  return `${((clicks / impressions) * 100).toFixed(1)}%`;
}

function formatCount(value: number | null): string {
  return value === null ? '—' : value.toLocaleString('en-US');
}

function SearchSignalRow({ signal, rank }: Readonly<{ signal: DemandSignal; rank: number }>) {
  const target = signalTarget(signal);
  return (
    <article className="border-border-subtle grid gap-3 border-t py-4 first:border-t-0 first:pt-0 last:pb-0">
      <div className="flex min-w-0 items-start gap-3">
        <span className="text-muted w-6 shrink-0 pt-0.5 text-xs tabular-nums">#{rank}</span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="neutral">{target.kind}</Badge>
            <p className="text-foreground min-w-0 break-words text-sm font-medium">{target.value}</p>
          </div>
        </div>
      </div>
      <dl className="ml-9 grid grid-cols-3 gap-3">
        <div>
          <dt className="text-muted text-xs">Impressions</dt>
          <dd className="text-foreground mt-1 text-sm font-medium tabular-nums">
            {formatCount(numericMetric(signal, 'impressions'))}
          </dd>
        </div>
        <div>
          <dt className="text-muted text-xs">Clicks</dt>
          <dd className="text-foreground mt-1 text-sm font-medium tabular-nums">
            {formatCount(numericMetric(signal, 'clicks'))}
          </dd>
        </div>
        <div>
          <dt className="text-muted text-xs">CTR</dt>
          <dd className="text-foreground mt-1 text-sm font-medium tabular-nums">
            {formatCtr(signal)}
          </dd>
        </div>
      </dl>
    </article>
  );
}

function SearchDemandSnapshot({ snapshot }: Readonly<{ snapshot: DemandSnapshot }>) {
  if (snapshot.coverage.search !== 'observed') {
    return (
      <Alert tone="info">
        Search Console evidence is unavailable for this snapshot. Sync Search Console to measure
        search demand.
      </Alert>
    );
  }

  const limitations = Array.from(
    new Set(snapshot.signals.flatMap((signal) => signal.limitations).filter(Boolean)),
  );
  const windowLabel = `${formatWindowDate(snapshot.window_start)} – ${formatWindowDate(snapshot.window_end)}`;

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {snapshot.signals.length === 1
            ? '1 search gap needs attention'
            : `${snapshot.signals.length} search gaps need attention`}
        </CardTitle>
        <CardDescription>
          High-impression, low-click queries and pages for {windowLabel}. Highest-priority gaps are
          shown first.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {snapshot.signals.length ? (
          <div>
            {snapshot.signals.map((signal, index) => (
              <SearchSignalRow key={signal.id} signal={signal} rank={index + 1} />
            ))}
          </div>
        ) : (
          <p className="text-secondary text-sm">
            Search Console data was observed, but no query or page met the configured
            high-impression, low-click criteria in this window.
          </p>
        )}
        {limitations.length ? (
          <p className="text-muted border-border-subtle mt-4 border-t pt-3 text-xs">
            {limitations.join(' ')}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function DemandProjection() {
  const { activeProject, isLoading: projectLoading } = useProjectContext();
  const latest = useQuery({
    queryKey: ['demand', activeProject?.id, 'latest'],
    queryFn: ({ signal }) => demandApi.getLatest(activeProject!.id, { signal }),
    enabled: Boolean(activeProject),
  });

  if (projectLoading || latest.isLoading) {
    return <Skeleton className="h-72" aria-label="Loading search demand" />;
  }
  if (!activeProject) return <Alert tone="info">Select a project to inspect search demand.</Alert>;
  if (latest.isError && httpErrorStatus(latest.error) === 404) {
    return (
      <Alert tone="info">
        No Search Demand snapshot exists yet. Sync Traffic evidence, then recompute Demand
        Intelligence.
      </Alert>
    );
  }
  if (latest.isError) return <Alert tone="danger">Search demand could not be loaded.</Alert>;
  if (!latest.data) return null;

  return <SearchDemandSnapshot snapshot={latest.data} />;
}
