'use client';

import { useQuery } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
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
import type { SiteHealthOverview } from '@/lib/api/types';
import { PLACEHOLDER } from '@/lib/site-health/status';

function percent(value: number | null): string {
  return value === null ? PLACEHOLDER : `${Math.round(value * 100)}%`;
}

function headline(score: number | null, state: string): string {
  if (state === 'measured' && score !== null) return `${Math.round(score)}`;
  if (state === 'limited_evidence') return 'Limited evidence';
  if (state === 'excluded') return 'Excluded';
  return 'Not measured';
}

function recordString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === 'string' ? value : '';
}

function recordNumber(record: Record<string, unknown>, key: string): number | null {
  const value = record[key];
  return typeof value === 'number' ? value : null;
}

export function OverviewPanel({
  projectId,
  crawlId,
}: Readonly<{ projectId: string; crawlId: string }>) {
  const overview = useQuery(siteHealthQueries.overview(projectId, crawlId));
  if (overview.isLoading)
    return (
      <output className="text-secondary text-sm">Loading persisted Site Health Overview…</output>
    );
  if (overview.isError || !overview.data)
    return <Alert tone="danger">Could not load Site Health Overview.</Alert>;
  return <OverviewContent data={overview.data} />;
}

function OverviewContent({ data }: Readonly<{ data: SiteHealthOverview }>) {
  const eligibilityTone =
    data.search_eligibility === 'eligible'
      ? 'success'
      : data.search_eligibility === 'blocked'
        ? 'danger'
        : 'warning';
  return (
    <div className="grid min-w-0 gap-4" data-testid="site-health-overview">
      <Alert tone={eligibilityTone}>
        Search eligibility: {data.search_eligibility}. {data.audited_page_count} audited of{' '}
        {data.selected_page_count} selected pages.
      </Alert>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        <MetricCard
          title="Technical Integrity"
          value={headline(data.technical_integrity_score, data.technical_integrity_state)}
          detail={`${percent(data.technical_integrity_coverage)} evidence coverage`}
        />
        <MetricCard
          title="AEO Readiness"
          value={headline(data.aeo_readiness_score, data.aeo_measurement_state)}
          detail="Audited pages only"
        />
        <MetricCard
          title="AEO Measurement Coverage"
          value={percent(data.aeo_measurement_coverage)}
          detail="Across applicable and unresolved pillars"
        />
        <MetricCard
          title="Crawl Coverage"
          value={recordString(data.crawl_coverage, 'state') || 'Unknown'}
          detail="Selected intended-public denominator"
        />
      </div>
      {data.limitations.length > 0 ? <Alert tone="info">{data.limitations.join(' ')}</Alert> : null}
      <div className="grid min-w-0 gap-4 xl:grid-cols-[1.4fr_1fr]">
        <DimensionLedger dimensions={data.aeo_dimensions} />
        <TopIssues issues={data.top_issues} />
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <StateCard title="Web Fundamentals" value={recordString(data.web_fundamentals, 'state')} />
        <StateCard title="Trend" value={recordString(data.trend, 'state')} />
        <StateCard title="Changes" value={recordString(data.change_summary, 'state')} />
      </div>
    </div>
  );
}

function MetricCard({
  title,
  value,
  detail,
}: Readonly<{ title: string; value: string; detail: string }>) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{title}</CardDescription>
        <CardTitle>{value}</CardTitle>
      </CardHeader>
      <CardContent className="text-muted text-xs">{detail}</CardContent>
    </Card>
  );
}

function DimensionLedger({ dimensions }: Readonly<{ dimensions: Record<string, unknown>[] }>) {
  return (
    <Card>
      <CardHeader bordered>
        <CardTitle>AEO readiness pillars</CardTitle>
        <CardDescription>Score, applicability, and measurement remain separate.</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Pillar</TableHead>
              <TableHead>Applicability</TableHead>
              <TableHead>State</TableHead>
              <TableHead numeric>Readiness</TableHead>
              <TableHead numeric>Coverage</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {dimensions.map((dimension) => {
              const key = recordString(dimension, 'key');
              return (
                <TableRow key={key}>
                  <TableCell className="font-medium">{key}</TableCell>
                  <TableCell>{recordString(dimension, 'dimension_applicability')}</TableCell>
                  <TableCell>
                    <Badge variant="status" value="info">
                      {recordString(dimension, 'dimension_measurement_state')}
                    </Badge>
                  </TableCell>
                  <TableCell numeric>{recordNumber(dimension, 'score') ?? PLACEHOLDER}</TableCell>
                  <TableCell numeric>{percent(recordNumber(dimension, 'coverage'))}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function TopIssues({ issues }: Readonly<{ issues: Record<string, unknown>[] }>) {
  return (
    <Card>
      <CardHeader bordered>
        <CardTitle>Top issues</CardTitle>
        <CardDescription>
          Eligibility blockers, then highest-impact defects and gaps.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="divide-border-subtle divide-y">
          {issues.length === 0 ? (
            <li className="text-secondary py-3 text-sm">No persisted issues.</li>
          ) : (
            issues.map((issue) => (
              <li
                key={`${recordString(issue, 'rule_id')}-${recordString(issue, 'finding_class')}`}
                className="grid gap-1 py-3"
              >
                <span className="text-foreground text-sm font-medium">
                  {recordString(issue, 'description') || recordString(issue, 'rule_id')}
                </span>
                <span className="text-muted text-xs">
                  {recordNumber(issue, 'affected_pages') ?? 0} affected pages ·{' '}
                  {recordString(issue, 'finding_class')}
                </span>
              </li>
            ))
          )}
        </ul>
      </CardContent>
    </Card>
  );
}

function StateCard({ title, value }: Readonly<{ title: string; value: string }>) {
  return (
    <Card>
      <CardHeader>
        <CardDescription>{title}</CardDescription>
        <CardTitle>{value || 'Unavailable'}</CardTitle>
      </CardHeader>
    </Card>
  );
}
