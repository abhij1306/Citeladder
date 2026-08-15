'use client';

import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { siteHealthQueries } from '@/lib/api/site-health';
import type { ReadinessDimension } from '@/lib/api/types';

function coverageLabel(value: number | null) {
  return value === null ? 'Unavailable' : `${Math.round(value * 100)}%`;
}

function pageLabel(url: string) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname}`;
  } catch {
    return url;
  }
}

function EvidenceLinks({
  dimension,
  crawlId,
}: Readonly<{ dimension: ReadinessDimension; crawlId: string }>) {
  if (!dimension.evidence_links.length)
    return <span className="text-subtle">No persisted evaluations</span>;
  return (
    <details>
      <summary className="text-accent-text cursor-pointer text-xs font-medium">
        View {dimension.evidence_links.length} evidence link
        {dimension.evidence_links.length === 1 ? '' : 's'}
      </summary>
      <ul className="mt-2 grid gap-1.5">
        {dimension.evidence_links.map((link) => (
          <li key={link.evaluation_id} className="flex flex-wrap items-baseline gap-x-2 text-xs">
            <span
              className={
                link.outcome === 'fail' ? 'text-danger-text font-medium' : 'text-secondary'
              }
            >
              {link.outcome.replace('_', ' ')}
            </span>
            <Link
              className="text-accent-text hover:underline"
              href={`/site/crawls/${crawlId}/pages/${link.site_url_id}`}
            >
              {pageLabel(link.normalized_url)}
            </Link>
            <span className="text-subtle">{link.rule_id}</span>
          </li>
        ))}
      </ul>
    </details>
  );
}

export function AeoReadinessPanel({
  projectId,
  crawlId,
}: Readonly<{ projectId: string; crawlId: string }>) {
  const readiness = useQuery(siteHealthQueries.aeoReadiness(projectId, crawlId));

  if (readiness.isLoading) {
    return (
      <p role="status" className="text-secondary text-sm">
        Loading persisted AEO evaluations…
      </p>
    );
  }
  if (readiness.isError) {
    return <Alert tone="danger">Could not load AEO Readiness.</Alert>;
  }
  if (!readiness.data || readiness.data.state === 'unavailable') {
    return (
      <Alert tone="info">
        AEO Readiness will appear after a usable crawl has persisted page evaluations.
      </Alert>
    );
  }

  const data = readiness.data;
  return (
    <div className="grid min-w-0 gap-6" data-testid="aeo-readiness">
      {data.state === 'incomplete' || data.limitations.length ? (
        <Alert tone="warning">{data.limitations.join(' ')}</Alert>
      ) : null}
      <Card>
        <CardHeader>
          <CardTitle>AEO Readiness</CardTitle>
          <CardDescription>
            Seven presentation dimensions over {data.analysis_count} analyzed page
            {data.analysis_count === 1 ? '' : 's'}. Counts are persisted rule outcomes—not a new
            score.
          </CardDescription>
        </CardHeader>
        <CardContent className="pt-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Dimension</TableHead>
                <TableHead numeric>Pass</TableHead>
                <TableHead numeric>Fail</TableHead>
                <TableHead numeric>Not applicable</TableHead>
                <TableHead>Coverage</TableHead>
                <TableHead>Evidence</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {data.dimensions.map((dimension) => (
                <TableRow key={dimension.key}>
                  <TableCell>
                    <span className="font-medium">{dimension.label}</span>
                    <span className="text-subtle block text-xs">
                      {dimension.rule_ids.length} mapped rules
                    </span>
                  </TableCell>
                  <TableCell numeric>{dimension.pass_count}</TableCell>
                  <TableCell
                    numeric
                    className={dimension.fail_count ? 'text-danger-text font-medium' : undefined}
                  >
                    {dimension.fail_count}
                  </TableCell>
                  <TableCell numeric>{dimension.not_applicable_count}</TableCell>
                  <TableCell>
                    <span className="tabular-nums">{coverageLabel(dimension.coverage)}</span>
                    <span className="text-subtle block text-xs">
                      {dimension.observed_evaluation_count} of {dimension.expected_evaluation_count}
                    </span>
                  </TableCell>
                  <TableCell>
                    <EvidenceLinks dimension={dimension} crawlId={crawlId} />
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
      <p className="text-subtle text-xs">
        Taxonomy {data.taxonomy_version} · Analyzer {data.analyzer_version}
      </p>
    </div>
  );
}
