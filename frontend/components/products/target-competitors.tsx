'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { commerceApi } from '@/lib/api/commerce';
import { queryKeys } from '@/lib/api/query-keys';
import type { CommerceTarget } from '@/lib/api/schemas/commerce-suite';
import type { useCompetitorDiscovery } from '@/lib/products/competitor-discovery';

import type { CommerceQueries } from './commerce-queries';
import { competitorHost, competitorTone, discoveryMessage } from './commerce-format';

type Discovery = ReturnType<typeof useCompetitorDiscovery>;

/** Only the candidates found for the target on screen. */
function forTarget(
  rows: NonNullable<CommerceQueries['competitors']['data']>,
  target: CommerceTarget,
) {
  return rows.filter((row) => row.target_kind === target.kind && row.target_id === target.id);
}

export function TargetCompetitors({
  projectId,
  target,
  query,
  discovery,
}: Readonly<{
  projectId: string;
  target: CommerceTarget;
  query: CommerceQueries['competitors'];
  discovery: Discovery;
}>) {
  const client = useQueryClient();
  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: 'approved' | 'rejected' }) =>
      commerceApi.decideCompetitor(projectId, id, decision),
    onSuccess: () =>
      client.invalidateQueries({ queryKey: queryKeys.commerce.competitors(projectId) }),
  });
  // The tracker follows every run in the project, so a bulk discovery across
  // three categories otherwise showed all three banners on each one, and made
  // every target read as "Finding…" while any of them was running.
  const tasks = discovery.tasks.filter(
    (task) => task.target.kind === target.kind && task.target.id === target.id,
  );
  const running = tasks.some((task) => !task.terminal);
  const rows = query.data ? forTarget(query.data, target) : [];
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="grid gap-1">
            <CardTitle>Competitors on this shelf</CardTitle>
            <CardDescription>Candidates do not enter measurement until approved.</CardDescription>
          </div>
          <Button
            variant="secondary"
            disabled={discovery.discover.isPending || running}
            onClick={() => discovery.discover.mutate([target])}
          >
            {running ? 'Finding…' : 'Find competitors'}
          </Button>
        </div>
        {tasks.map((task) => (
          <Alert key={task.id} tone={task.status === 'failed' ? 'danger' : 'info'}>
            {discoveryMessage(task.status, task.target.kind, task.error_code)}
          </Alert>
        ))}
        {decide.isError ? (
          <Alert tone="danger">The competitor decision failed. Please try again.</Alert>
        ) : null}
      </CardHeader>
      <CardContent>
        <CompetitorRows
          query={query}
          rows={rows}
          running={running}
          pending={decide.isPending}
          onDecide={(id, decision) => decide.mutate({ id, decision })}
        />
      </CardContent>
    </Card>
  );
}

function CompetitorRows({
  query,
  rows,
  running,
  pending,
  onDecide,
}: Readonly<{
  query: CommerceQueries['competitors'];
  rows: NonNullable<CommerceQueries['competitors']['data']>;
  running: boolean;
  pending: boolean;
  onDecide: (id: string, decision: 'approved' | 'rejected') => void;
}>) {
  if (query.isError) return <Alert tone="danger">Competitors could not be loaded.</Alert>;
  if (query.isPending) return <Skeleton className="h-24 w-full" />;
  if (!rows.length) {
    return (
      <p className="text-muted py-[var(--card-padding)] text-center text-sm">
        {running
          ? 'Looking for competitors…'
          : 'No candidates yet for this target. Run Find competitors.'}
      </p>
    );
  }
  return (
    <ul className="divide-border-subtle grid divide-y">
      {rows.map((row) => (
        <li key={row.id} className="flex flex-wrap items-center gap-3 py-2">
          <a
            className="text-link min-w-0 flex-1 truncate font-medium"
            href={row.canonical_url}
            target="_blank"
            rel="noreferrer"
          >
            {competitorHost(row.canonical_url)}
          </a>
          <Badge variant="status" value={competitorTone(row.state)}>
            {row.state}
          </Badge>
          {row.state === 'pending' ? (
            <div className="flex gap-2">
              <Button size="sm" disabled={pending} onClick={() => onDecide(row.id, 'approved')}>
                Approve
              </Button>
              <Button
                size="sm"
                variant="secondary"
                disabled={pending}
                onClick={() => onDecide(row.id, 'rejected')}
              >
                Reject
              </Button>
            </div>
          ) : null}
        </li>
      ))}
    </ul>
  );
}
