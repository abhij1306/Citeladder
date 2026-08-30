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
  if ((state === 'measured' || state === 'limited_evidence') && score !== null)
    return `${Math.round(score)}`;
  if (state === 'limited_evidence') return 'Limited evidence';
  if (state === 'excluded') return 'Excluded';
  return 'Not measured';
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
  const eligibilityTone = searchEligibilityTone(data.search_eligibility);
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
          value={data.crawl_coverage.state || 'Unknown'}
          detail="Selected intended-public denominator"
        />
      </div>
      {data.limitations.length > 0 ? <Alert tone="info">{data.limitations.join(' ')}</Alert> : null}
      <div className="grid min-w-0 gap-4 xl:grid-cols-[1.4fr_1fr]">
        <DimensionLedger dimensions={data.aeo_dimensions} />
        <TopIssues issues={data.top_issues} />
      </div>
      <div className="grid gap-4 md:grid-cols-3">
        <StateCard title="Web Fundamentals" value={data.web_fundamentals.state} />
        <StateCard title="Trend" value={data.trend.state} />
        <StateCard title="Changes" value={data.change_summary.state} />
      </div>
    </div>
  );
}

function searchEligibilityTone(state: SiteHealthOverview['search_eligibility']) {
  if (state === 'eligible') return 'success' as const;
  if (state === 'blocked') return 'danger' as const;
  return 'warning' as const;
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

function DimensionLedger({
  dimensions,
}: Readonly<{ dimensions: SiteHealthOverview['aeo_dimensions'] }>) {
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
              const key = dimension.key;
              return (
                <TableRow key={key}>
                  <TableCell className="font-medium">{key}</TableCell>
                  <TableCell>{dimension.dimension_applicability}</TableCell>
                  <TableCell>
                    <Badge variant="status" value="info">
                      {dimension.dimension_measurement_state}
                    </Badge>
                  </TableCell>
                  <TableCell numeric>{dimension.score ?? PLACEHOLDER}</TableCell>
                  <TableCell numeric>{percent(dimension.coverage)}</TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function TopIssues({ issues }: Readonly<{ issues: SiteHealthOverview['top_issues'] }>) {
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
              <li key={`${issue.rule_id}-${issue.finding_class}`} className="grid gap-1 py-3">
                <span className="text-foreground text-sm font-medium">
                  {issue.description || issue.rule_id}
                </span>
                <span className="text-muted text-xs">
                  {issue.affected_pages} affected pages · {issue.finding_class}
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
