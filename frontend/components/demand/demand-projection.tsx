'use client';

import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { demandApi, type DemandCapability, type DemandSnapshot } from '@/lib/api/demand';
import { useProjectContext } from '@/lib/project/project-context';

const LABELS: Record<string, string> = {
  high_impression_low_ctr: 'High-impression, low-click demand',
  unanswered_required_question: 'Unanswered required question',
};

function Coverage({ coverage }: Readonly<{ coverage: Record<string, unknown> }>) {
  const describe = (value: unknown): string => {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return String(value);
    const details = value as Record<string, unknown>;
    const parts = [typeof details.state === 'string' ? details.state : null];
    if (typeof details.total_pages === 'number' && typeof details.matched_pages === 'number') {
      parts.push(`${details.matched_pages} of ${details.total_pages} pages joined`);
    }
    if (typeof details.join_rate === 'number')
      parts.push(`${Math.round(details.join_rate * 100)}%`);
    const keyEvents = details.key_events;
    if (keyEvents && typeof keyEvents === 'object' && !Array.isArray(keyEvents)) {
      const event = keyEvents as Record<string, unknown>;
      parts.push(
        event.state === 'observed'
          ? `${String(event.value)} key events observed`
          : 'key events unavailable',
      );
    }
    const knownParts = parts.filter(Boolean);
    if (knownParts.length) return knownParts.join(' · ');
    const counts = Object.entries(details)
      .filter((entry): entry is [string, number] => typeof entry[1] === 'number')
      .map(([key, count]) => `${key.replaceAll('_', ' ')} ${count}`);
    return counts.join(' · ') || 'None represented';
  };
  return (
    <dl className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {Object.entries(coverage).map(([source, value]) => (
        <div key={source} className="border-border-subtle rounded-md border p-3">
          <dt className="text-muted text-xs capitalize">{source.replaceAll('_', ' ')}</dt>
          <dd className="text-foreground mt-1 text-sm font-medium">{describe(value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function EvidencePanel({
  snapshot,
  datasets,
  isLoading,
  isError,
}: Readonly<{
  snapshot: DemandSnapshot;
  datasets: DemandCapability[];
  isLoading: boolean;
  isError: boolean;
}>) {
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Source coverage</CardTitle>
          <CardDescription>
            Unavailable is preserved separately from an observed zero.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Coverage coverage={snapshot.coverage} />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Provenance</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm">
          <p>
            {snapshot.source_metric_row_ids.length} metric rows ·{' '}
            {snapshot.source_artifact_ids.length} immutable artifacts
          </p>
          <p>
            {snapshot.journey_version_ids.length} journey versions ·{' '}
            {snapshot.source_audit_ids.length} visibility audits
          </p>
          <p className="text-muted font-mono text-xs">
            {snapshot.analyzer_version} · {snapshot.formula_version}
          </p>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Report families</CardTitle>
          <CardDescription>
            Compatibility and coverage come from persisted sync evidence; this view never probes
            Google.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2">
          {isLoading ? <Skeleton className="h-20" /> : null}
          {isError ? (
            <Alert tone="danger">Report capability evidence could not be loaded.</Alert>
          ) : null}
          {datasets.map((dataset) => (
            <div
              className="border-border-subtle grid gap-1 border-b py-2 text-sm sm:grid-cols-[1fr_auto]"
              key={`${dataset.provider}:${dataset.dataset}`}
            >
              <span className="text-secondary break-all">
                {dataset.provider.toUpperCase()} · {dataset.dataset.replaceAll('_', ' ')}
              </span>
              <span className="text-foreground font-medium capitalize">{dataset.state}</span>
            </div>
          ))}
          {!isLoading && datasets.length === 0 ? (
            <p className="text-muted text-sm">No report capability evidence exists yet.</p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

function PromptPanel({ snapshot }: Readonly<{ snapshot: DemandSnapshot }>) {
  const portfolio = snapshot.summary.prompt_portfolio;
  const values =
    portfolio && typeof portfolio === 'object' && !Array.isArray(portfolio)
      ? (portfolio as Record<string, unknown>)
      : {};
  const active = typeof values.active_count === 'number' ? values.active_count : 0;
  const grounded =
    typeof values.demand_grounded_count === 'number' ? values.demand_grounded_count : 0;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Active prompt portfolio</CardTitle>
        <CardDescription>
          {active} active prompts; {grounded} retain Demand snapshot or signal provenance.
          Measurement starts only when you run or schedule an audit.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <Coverage coverage={{ intents: values.by_intent ?? {}, cohorts: values.by_cohort ?? {} }} />
        <Link
          className="text-accent-text min-h-11 w-fit py-3 text-sm font-medium underline"
          href="/prompts"
        >
          Manage prompt portfolio
        </Link>
      </CardContent>
    </Card>
  );
}

function JourneyPanel({ snapshot }: Readonly<{ snapshot: DemandSnapshot }>) {
  const description = snapshot.journey_version_ids.length
    ? `${snapshot.journey_version_ids.length} immutable journey version(s) contributed.`
    : 'No journey is configured; missing key events are unavailable, not zero.';
  return (
    <Card>
      <CardHeader>
        <CardTitle>Configured journeys</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent>
        <Link className="text-accent-text text-sm underline" href="/analytics">
          Inspect engagement evidence
        </Link>
      </CardContent>
    </Card>
  );
}

function SignalsPanel({
  snapshot,
  searchOnly,
}: Readonly<{ snapshot: DemandSnapshot; searchOnly: boolean }>) {
  const signals = searchOnly
    ? snapshot.signals.filter((row) => row.signal_type === 'high_impression_low_ctr')
    : snapshot.signals;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Prioritized signals</CardTitle>
        <CardDescription>Every item traces to persisted Site or Google evidence.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        {signals.length ? (
          signals.map((signal) => (
            <article key={signal.id} className="border-border-subtle rounded-md border p-3">
              <div className="flex flex-wrap justify-between gap-2">
                <h4 className="text-sm font-medium">
                  {LABELS[signal.signal_type] ?? signal.signal_type}
                </h4>
                <span className="text-muted font-mono text-xs">
                  {signal.priority_score ?? 'unranked'}
                </span>
              </div>
              <p className="text-secondary mt-1 text-sm">
                {signal.topic_cluster || signal.page_url}
              </p>
              {signal.limitations.map((item) => (
                <p key={item} className="text-muted mt-2 text-xs">
                  {item}
                </p>
              ))}
            </article>
          ))
        ) : (
          <p className="text-muted text-sm">
            No active signals were detected in this evidence window.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

function SnapshotPanel({
  snapshot,
  panel,
  capabilities,
}: Readonly<{
  snapshot: DemandSnapshot;
  panel: 'overview' | 'search' | 'journeys' | 'prompts' | 'evidence';
  capabilities: { data?: { datasets: DemandCapability[] }; isLoading: boolean; isError: boolean };
}>) {
  if (panel === 'evidence')
    return (
      <EvidencePanel
        snapshot={snapshot}
        datasets={capabilities.data?.datasets ?? []}
        isLoading={capabilities.isLoading}
        isError={capabilities.isError}
      />
    );
  if (panel === 'prompts') return <PromptPanel snapshot={snapshot} />;
  return (
    <div className="grid gap-4">
      <Card>
        <CardHeader>
          <CardTitle>{panel === 'journeys' ? 'Journey measurement' : 'Demand overview'}</CardTitle>
          <CardDescription>
            {snapshot.window_start}–{snapshot.window_end}; comparisons are descriptive and never
            assert causality.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <Coverage coverage={snapshot.coverage} />
        </CardContent>
      </Card>
      {panel === 'journeys' ? (
        <JourneyPanel snapshot={snapshot} />
      ) : (
        <SignalsPanel snapshot={snapshot} searchOnly={panel === 'search'} />
      )}
    </div>
  );
}

export function DemandProjection({
  panel,
}: Readonly<{ panel: 'overview' | 'search' | 'journeys' | 'prompts' | 'evidence' }>) {
  const { activeProject, isLoading: projectLoading } = useProjectContext();
  const list = useQuery({
    queryKey: ['demand', activeProject?.id, 'snapshots'],
    queryFn: ({ signal }) => demandApi.listSnapshots(activeProject!.id, { signal }),
    enabled: Boolean(activeProject),
  });
  const latestId = list.data?.items[0]?.id;
  const detail = useQuery({
    queryKey: ['demand', activeProject?.id, 'snapshot', latestId],
    queryFn: ({ signal }) => demandApi.getSnapshot(activeProject!.id, latestId!, { signal }),
    enabled: Boolean(activeProject && latestId),
  });
  const capabilities = useQuery({
    queryKey: ['demand', activeProject?.id, 'capabilities'],
    queryFn: ({ signal }) => demandApi.getCapabilities(activeProject!.id, { signal }),
    enabled: Boolean(activeProject && panel === 'evidence'),
  });
  if (projectLoading || list.isLoading || detail.isLoading)
    return (
      <div className="grid gap-4" aria-busy="true">
        <Skeleton className="h-28" />
        <Skeleton className="h-64" />
      </div>
    );
  if (!activeProject)
    return <Alert tone="info">Select a project to inspect Demand Intelligence.</Alert>;
  if (list.isError || detail.isError)
    return <Alert tone="danger">Demand evidence could not be loaded.</Alert>;
  const snapshot = detail.data;
  if (!snapshot)
    return (
      <Alert tone="info">
        No Demand snapshot exists yet. Sync Traffic evidence, then recompute Demand Intelligence.
      </Alert>
    );
  return <SnapshotPanel snapshot={snapshot} panel={panel} capabilities={capabilities} />;
}
