'use client';

import Link from 'next/link';
import { useQuery, type UseQueryResult } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { CursorPager } from '@/components/ui/cursor-pager';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { siteHealthQueries } from '@/lib/api/site-health';
import type { ChangeObservation, ChangesPage, ChangeSummary } from '@/lib/api/types';
import { useCursorStack } from '@/lib/site-health/use-cursor-stack';

const CLASS_LABELS = {
  improvement: 'Improvement',
  'neutral-change': 'Neutral change',
  'potential-regression': 'Potential regression',
  'critical-regression': 'Critical regression',
} as const;

function displayPath(url: string) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname}`;
  } catch {
    return url;
  }
}

function valueLabel(value: unknown) {
  if (value === null || value === undefined || value === '') return 'Not present';
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'Not present';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function Evidence({ row }: Readonly<{ row: ChangeObservation }>) {
  return (
    <details>
      <summary className="text-accent-text cursor-pointer text-xs font-medium">
        View evidence
      </summary>
      <dl className="mt-2 grid gap-1 text-xs">
        <div>
          <dt className="text-subtle inline">Before: </dt>
          <dd className="inline">{valueLabel(row.before_value)}</dd>
        </div>
        <div>
          <dt className="text-subtle inline">After: </dt>
          <dd className="inline">{valueLabel(row.after_value)}</dd>
        </div>
        <div>
          <dt className="text-subtle inline">Analyses: </dt>
          <dd className="inline break-all">
            {row.source_analysis_a_id ?? 'none'} → {row.source_analysis_b_id ?? 'none'}
          </dd>
        </div>
        {row.implementation_event_id ? (
          <div>
            <dt className="text-subtle inline">Implementation event: </dt>
            <dd className="inline break-all">{row.implementation_event_id}</dd>
          </div>
        ) : null}
      </dl>
    </details>
  );
}

export function ChangesPanel({ projectId }: Readonly<{ projectId: string }>) {
  const pager = useCursorStack();
  const summary = useQuery(siteHealthQueries.changesSummary(projectId));
  const crawlAId = summary.data?.crawl_a_id ?? undefined;
  const crawlBId = summary.data?.crawl_b_id ?? undefined;
  const pairAvailable = summary.data?.state === 'available' && Boolean(crawlAId && crawlBId);
  const changes = useQuery({
    ...siteHealthQueries.changes(projectId, crawlAId, crawlBId, pager.cursor),
    enabled: pairAvailable,
  });

  return (
    <ChangesPanelContent
      summary={summary}
      changes={changes}
      pairAvailable={pairAvailable}
      pager={pager}
    />
  );
}

function ChangesPanelContent({
  summary,
  changes,
  pairAvailable,
  pager,
}: Readonly<{
  summary: UseQueryResult<ChangeSummary>;
  changes: UseQueryResult<ChangesPage>;
  pairAvailable: boolean;
  pager: ReturnType<typeof useCursorStack>;
}>) {
  const state = changesState(summary, changes, pairAvailable);
  return state ?? <ChangesTable summary={summary.data!} changes={changes.data!} pager={pager} />;
}

function changesState(
  summary: UseQueryResult<ChangeSummary>,
  changes: UseQueryResult<ChangesPage>,
  pairAvailable: boolean,
) {
  const loading = summary.isLoading || (pairAvailable && changes.isLoading);
  if (loading)
    return (
      <p role="status" className="text-secondary text-sm">
        Loading persisted website changes…
      </p>
    );
  if (summary.isError || changes.isError)
    return <Alert tone="danger">Could not load Website Changes.</Alert>;
  return comparisonState(summary.data, pairAvailable);
}

function comparisonState(summary: ChangeSummary | undefined, pairAvailable: boolean) {
  if (!summary || summary.state === 'unavailable')
    return (
      <Alert tone="info">
        Website Changes need two usable crawls with persisted page evidence.
      </Alert>
    );
  if (summary.state === 'non_comparable')
    return (
      <Alert tone="warning">
        These crawls are not comparable (
        {summary.reason_code?.replaceAll('_', ' ') ?? 'scope or version mismatch'}).
      </Alert>
    );
  return pairAvailable ? null : (
    <Alert tone="danger">The persisted comparison is missing its exact crawl pair.</Alert>
  );
}

function ChangesTable({
  summary,
  changes,
  pager,
}: Readonly<{
  summary: ChangeSummary;
  changes: ChangesPage;
  pager: ReturnType<typeof useCursorStack>;
}>) {
  const rows = changes.items;
  const counts = summary.summary.counts_by_class as Record<string, number> | undefined;
  return (
    <div className="grid min-w-0 gap-6" data-testid="website-changes">
      {!summary.complete_pair ? (
        <Alert tone="warning">
          This comparison includes shared observed URLs only. Added and removed page claims are
          suppressed for partial crawls.
        </Alert>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>Website Changes</CardTitle>
          <CardDescription>
            Deterministic field changes between the immediate comparable crawls. Expected marks
            exact implementation-event matches.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4 pt-0">
          <div className="grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            {Object.entries(CLASS_LABELS).map(([key, label]) => (
              <div key={key}>
                <span className="text-subtle block">{label}</span>
                <span className="font-medium tabular-nums">{counts?.[key] ?? 0}</span>
              </div>
            ))}
          </div>
          {rows.length ? (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Page</TableHead>
                  <TableHead>Field</TableHead>
                  <TableHead>Class</TableHead>
                  <TableHead>Evidence</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {rows.map((row) => (
                  <TableRow key={row.id}>
                    <TableCell>
                      <Link
                        className="text-accent-text font-medium hover:underline"
                        href={`/site/crawls/${summary.crawl_b_id}/pages/${row.site_url_id}`}
                      >
                        {displayPath(row.normalized_url)}
                      </Link>
                    </TableCell>
                    <TableCell>{row.field.replaceAll('_', ' ')}</TableCell>
                    <TableCell>
                      <Badge>{CLASS_LABELS[row.change_class]}</Badge>
                      {row.expected ? (
                        <span className="text-success-text ml-2 text-xs">Expected</span>
                      ) : null}
                    </TableCell>
                    <TableCell>
                      <Evidence row={row} />
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <p className="text-secondary text-sm">
              No changes were observed in this comparable pair.
            </p>
          )}
          {pager.canPrev || changes.next_cursor ? (
            <div className="flex justify-end">
              <CursorPager
                canPrev={pager.canPrev}
                canNext={Boolean(changes.next_cursor)}
                onPrev={pager.pop}
                onNext={() => pager.push(changes.next_cursor)}
              />
            </div>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
