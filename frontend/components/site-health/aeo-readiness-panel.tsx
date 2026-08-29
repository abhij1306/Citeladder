'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Drawer } from '@/components/ui/drawer';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { siteHealthQueries } from '@/lib/api/site-health';
import type { AeoReadiness, ReadinessCheck, ReadinessDimension } from '@/lib/api/types';
import { PLACEHOLDER } from '@/lib/site-health/status';

function pageLabel(url: string) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname}`;
  } catch {
    return url;
  }
}

function formatCoverage(coverage: number | null): string {
  return coverage === null ? PLACEHOLDER : `${Math.round(coverage * 100)}%`;
}

type DimensionState =
  | 'Needs work'
  | 'Limited evidence'
  | 'Passing'
  | 'Not measured'
  | 'Not applicable';

function dimensionState(dimension: ReadinessDimension): DimensionState {
  if (dimension.expected_evaluation_count === 0) return 'Not applicable';
  if (dimension.observed_evaluation_count === 0) return 'Not measured';
  if (dimension.fail_count > 0) return 'Needs work';
  if (
    dimension.error_count > 0 ||
    dimension.observed_evaluation_count < dimension.expected_evaluation_count
  ) {
    return 'Limited evidence';
  }
  return 'Passing';
}

function stateBadgeValue(state: DimensionState) {
  if (state === 'Needs work') return 'danger' as const;
  if (state === 'Limited evidence') return 'warning' as const;
  if (state === 'Passing') return 'success' as const;
  return 'info' as const;
}

export function AeoReadinessPanel({
  projectId,
  crawlId,
}: Readonly<{ projectId: string; crawlId: string }>) {
  const readiness = useQuery(siteHealthQueries.aeoReadiness(projectId, crawlId));
  const [detailKey, setDetailKey] = useState<string | null>(null);

  if (readiness.isLoading) {
    return (
      <output className="text-secondary block text-sm">Loading persisted AEO evaluations…</output>
    );
  }
  if (readiness.isError) return <Alert tone="danger">Could not load AEO Readiness.</Alert>;
  if (!readiness.data || readiness.data.state === 'unavailable') {
    return (
      <Alert tone="info">
        {readiness.data?.limitations[0] ??
          'AEO Readiness appears once a crawl has finished analyzing pages.'}
      </Alert>
    );
  }

  const data = readiness.data;
  const selected = data.dimensions.find((dimension) => dimension.key === detailKey) ?? null;
  return (
    <div className="grid min-w-0 gap-4" data-testid="aeo-readiness">
      <ReadinessHeader data={data} />
      {data.limitations.length > 0 ? <Alert tone="info">{data.limitations.join(' ')}</Alert> : null}
      <ReadinessLedger dimensions={data.dimensions} onOpen={setDetailKey} />
      <DimensionDrawer dimension={selected} crawlId={crawlId} onClose={() => setDetailKey(null)} />
    </div>
  );
}

function ReadinessHeader({ data }: Readonly<{ data: AeoReadiness }>) {
  const incomplete = data.state === 'incomplete';
  const items = [
    ['Analyzed pages', String(data.analysis_count)],
    ['Determinate checks', String(data.observed_evaluation_count)],
    ['Expected checks', String(data.expected_evaluation_count)],
    ['Coverage', formatCoverage(data.coverage)],
  ];
  return (
    <Card>
      <CardHeader className="gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <CardTitle>AEO Readiness</CardTitle>
          <Badge variant="status" value={incomplete ? 'warning' : 'success'}>
            {incomplete ? 'Limited evidence' : 'Available'}
          </Badge>
        </div>
        <CardDescription>
          Seven readiness dimensions with determinate coverage over expected checks.
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-2">
        <dl className="border-border-subtle grid grid-cols-2 border-y md:grid-cols-4">
          {items.map(([label, value]) => (
            <div
              key={label}
              className="border-border-subtle grid gap-1 border-b px-3 py-3 last:border-b-0 md:border-r md:border-b-0 md:last:border-r-0"
            >
              <dt className="text-muted text-xs">{label}</dt>
              <dd className="text-foreground text-lg font-semibold tabular-nums">{value}</dd>
            </div>
          ))}
        </dl>
      </CardContent>
    </Card>
  );
}

function ReadinessLedger({
  dimensions,
  onOpen,
}: Readonly<{ dimensions: ReadinessDimension[]; onOpen: (key: string) => void }>) {
  return (
    <Card>
      <CardHeader bordered>
        <CardTitle>Readiness dimensions</CardTitle>
        <CardDescription>
          One count is one persisted rule evaluation on one analyzed page.
        </CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Dimension</TableHead>
              <TableHead numeric>Determinate</TableHead>
              <TableHead numeric>Expected</TableHead>
              <TableHead numeric>N/A</TableHead>
              <TableHead numeric>Errors</TableHead>
              <TableHead numeric>Coverage</TableHead>
              <TableHead>State</TableHead>
              <TableHead className="w-28" />
            </TableRow>
          </TableHeader>
          <TableBody>
            {dimensions.map((dimension) => {
              const state = dimensionState(dimension);
              return (
                <TableRow key={dimension.key}>
                  <TableCell className="min-w-64">
                    <span className="font-medium">{dimension.label}</span>
                    <span className="text-muted mt-0.5 block text-xs">{dimension.description}</span>
                  </TableCell>
                  <TableCell numeric>{dimension.observed_evaluation_count}</TableCell>
                  <TableCell numeric>{dimension.expected_evaluation_count}</TableCell>
                  <TableCell numeric>{dimension.not_applicable_count}</TableCell>
                  <TableCell
                    numeric
                    className={
                      dimension.error_count > 0 ? 'text-warning-text font-medium' : undefined
                    }
                  >
                    {dimension.error_count}
                  </TableCell>
                  <TableCell numeric>{formatCoverage(dimension.coverage)}</TableCell>
                  <TableCell>
                    <Badge variant="status" value={stateBadgeValue(state)}>
                      {state}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <Button variant="secondary" size="sm" onClick={() => onOpen(dimension.key)}>
                      View details <span className="sr-only">for {dimension.label}</span>
                    </Button>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function DimensionDrawer({
  dimension,
  crawlId,
  onClose,
}: Readonly<{ dimension: ReadinessDimension | null; crawlId: string; onClose: () => void }>) {
  return (
    <Drawer
      open={Boolean(dimension)}
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={dimension ? `${dimension.label} evidence` : ''}
      description={dimension?.description ?? ''}
      closeLabel="Close evidence"
    >
      {dimension ? (
        <div className="grid gap-[var(--workspace-gap)]">
          <CheckLedger checks={dimension.checks} />
          <FailingPages dimension={dimension} crawlId={crawlId} />
        </div>
      ) : null}
    </Drawer>
  );
}

function CheckLedger({ checks }: Readonly<{ checks: ReadinessCheck[] }>) {
  return (
    <section className="grid gap-2">
      <h3 className="text-foreground text-base font-semibold">Checks</h3>
      {checks.length === 0 ? (
        <p className="text-secondary text-sm">No determinate checks were recorded.</p>
      ) : (
        <ul className="divide-border-subtle divide-y">
          {checks.map((check) => (
            <CheckRow key={check.rule_id} check={check} />
          ))}
        </ul>
      )}
    </section>
  );
}

function CheckRow({ check }: Readonly<{ check: ReadinessCheck }>) {
  const state =
    check.error_count > 0
      ? 'Incomplete'
      : check.fail_count > 0
        ? 'Needs work'
        : check.pass_count > 0
          ? 'Passing'
          : 'Did not apply';
  return (
    <li className="grid gap-1 py-3 first:pt-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-foreground text-sm font-medium">{check.title}</span>
        <span className="text-secondary text-xs">{state}</span>
      </div>
      <p className="text-secondary text-sm">
        {check.remediation || 'No remediation guidance is recorded for this check.'}
      </p>
      <p className="text-muted text-xs tabular-nums">
        {check.pass_count} passed · {check.fail_count} failed · {check.not_applicable_count} not
        applicable · {check.error_count} errors
      </p>
    </li>
  );
}

function FailingPages({
  dimension,
  crawlId,
}: Readonly<{ dimension: ReadinessDimension; crawlId: string }>) {
  const shown = dimension.evidence_pages.length;
  const total = dimension.failing_page_count;
  return (
    <section className="grid gap-2">
      <div className="grid gap-0.5">
        <h3 className="text-foreground text-base font-semibold">Pages to fix</h3>
        <p className="text-muted text-xs">
          {total === 0
            ? 'No failing pages were recorded.'
            : shown < total
              ? `Showing the ${shown} most affected of ${total} pages, worst first.`
              : `${total} page${total === 1 ? '' : 's'} failed at least one check, worst first.`}
        </p>
      </div>
      <ul className="divide-border-subtle divide-y">
        {dimension.evidence_pages.map((page) => (
          <li key={page.site_url_id} className="grid gap-1.5 py-3 first:pt-0">
            <Link
              className="text-accent-text truncate text-sm font-medium hover:underline"
              href={`/site/crawls/${crawlId}/pages/${page.site_url_id}`}
            >
              {pageLabel(page.normalized_url)}
            </Link>
            <ul className="grid gap-1">
              {page.failed_checks.map((check) => (
                <li key={check.rule_id} className="text-secondary flex items-start gap-2 text-xs">
                  <span className="bg-danger mt-1.5 size-1.5 shrink-0 rounded-full" aria-hidden />
                  {check.title}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </section>
  );
}
