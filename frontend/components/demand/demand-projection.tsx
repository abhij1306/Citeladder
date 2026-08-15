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

const SIGNAL_LABELS: Record<string, string> = {
  high_impression_low_ctr: 'Low CTR',
  branded_query_performance: 'Branded cohort',
  striking_distance: 'Striking distance',
  query_cannibalization: 'Cannibalization',
  property_relative_ctr_gap: 'CTR gap',
  emerging_query: 'Emerging',
  declining_query: 'Declining',
};

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
            <Badge variant="neutral">{SIGNAL_LABELS[signal.signal_type] ?? 'Demand signal'}</Badge>
            <p className="text-foreground min-w-0 text-sm font-medium break-words">
              {target.value}
            </p>
          </div>
        </div>
      </div>
      <dl className="ml-9 grid grid-cols-2 gap-3 sm:grid-cols-4">
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
        <div>
          <dt className="text-muted text-xs">Position</dt>
          <dd className="text-foreground mt-1 text-sm font-medium tabular-nums">
            {numericMetric(signal, 'position')?.toFixed(1) ?? '—'}
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
  const detectorNotes = detectorStateNotes(snapshot.summary.detectors);

  return (
    <Card>
      <CardHeader>
        <CardTitle>
          {snapshot.signals.length === 1
            ? '1 demand signal observed'
            : `${snapshot.signals.length} demand signals observed`}
        </CardTitle>
        <CardDescription>
          Versioned GSC query evidence for {windowLabel}. Highest-priority signals are shown first;
          branded demand remains a separate, non-actionable cohort.
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
            Search Console data was observed, but no configured detector emitted a signal in this
            window.
          </p>
        )}
        {detectorNotes.length ? (
          <ul className="text-muted border-border-subtle mt-4 list-disc border-t pt-3 pl-5 text-xs">
            {detectorNotes.map((note) => (
              <li key={note}>{note}</li>
            ))}
          </ul>
        ) : null}
        {limitations.length ? (
          <p className="text-muted border-border-subtle mt-4 border-t pt-3 text-xs">
            {limitations.join(' ')}
          </p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function detectorStateNotes(value: unknown): string[] {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return [];
  const labels: Record<string, string> = {
    cannibalization: 'Cannibalization',
    property_relative_ctr_gap: 'CTR gap',
    query_trends: 'Query trends',
    striking_distance: 'Striking distance',
  };
  const notes: string[] = [];
  for (const [key, raw] of Object.entries(value)) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) continue;
    const state = (raw as Record<string, unknown>).state;
    if (state === 'unavailable' || state === 'insufficient_history' || state === 'partial') {
      notes.push(`${labels[key] ?? key}: ${String(state).replace('_', ' ')}.`);
    }
  }
  return notes;
}

export function DemandProjection() {
  const { activeProject, isLoading: projectLoading } = useProjectContext();
  const latest = useQuery({
    queryKey: ['demand', activeProject?.id, 'latest'],
    queryFn: ({ signal }) => demandApi.getLatest(activeProject!.id, { signal }),
    enabled: Boolean(activeProject),
  });

  if (projectLoading || latest.isLoading) {
    return (
      <>
        <output className="sr-only">Loading search demand</output>
        <Skeleton className="h-72" />
      </>
    );
  }
  if (!activeProject) return <Alert tone="info">Select a project to inspect search demand.</Alert>;
  if (latest.isError && httpErrorStatus(latest.error) === 404) {
    return (
      <Alert tone="info">
        No Search Demand snapshot exists yet. Sync Traffic evidence, then recompute Search Demand.
      </Alert>
    );
  }
  if (latest.isError) return <Alert tone="danger">Search demand could not be loaded.</Alert>;
  if (!latest.data) return null;

  return <SearchDemandSnapshot snapshot={latest.data} />;
}
