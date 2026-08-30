'use client';

import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardEyebrow,
  CardHeader,
  CardTitle,
} from '@/components/ui/card';
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
import type { SiteHealthOverview } from '@/lib/api/types';
import { PLACEHOLDER } from '@/lib/site-health/status';

function percent(value: number | null): string {
  return value === null ? PLACEHOLDER : `${Math.round(value * 100)}%`;
}

function headline(score: number | null, state: string): string {
  if (state === 'limited_evidence') return 'Limited evidence';
  if (state === 'measured' && score !== null) return `${Math.round(score)}`;
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
  const [webFundamentalsOpen, setWebFundamentalsOpen] = useState(false);
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
        <WebFundamentalsCard
          data={data.web_fundamentals}
          onOpen={() => setWebFundamentalsOpen(true)}
        />
        <StateCard title="Trend" value={data.trend.state} />
        <StateCard title="Changes" value={data.change_summary.state} />
      </div>
      <WebFundamentalsDrawer
        data={data.web_fundamentals}
        open={webFundamentalsOpen}
        onOpenChange={setWebFundamentalsOpen}
      />
    </div>
  );
}

function WebFundamentalsCard({
  data,
  onOpen,
}: Readonly<{ data: SiteHealthOverview['web_fundamentals']; onOpen: () => void }>) {
  return (
    <Card>
      <CardHeader>
        <CardEyebrow>Web Fundamentals</CardEyebrow>
        <CardTitle className="text-lg">{data.state}</CardTitle>
        <CardDescription>Persisted HTTP evidence across four areas.</CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        <Button variant="secondary" size="sm" onClick={onOpen}>
          View evidence
        </Button>
      </CardContent>
    </Card>
  );
}

function WebFundamentalsDrawer({
  data,
  open,
  onOpenChange,
}: Readonly<{
  data: SiteHealthOverview['web_fundamentals'];
  open: boolean;
  onOpenChange: (open: boolean) => void;
}>) {
  return (
    <Drawer
      open={open}
      onOpenChange={onOpenChange}
      title="Web Fundamentals"
      description="Static evidence from the acquired HTML and response headers."
    >
      <div className="grid gap-4">
        {data.areas.map((area) => (
          <Card key={area.key}>
            <CardHeader bordered>
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="capitalize">{area.key}</CardTitle>
                <Badge variant="status" value="info">
                  {area.state}
                </Badge>
              </div>
              <CardDescription>
                {percent(area.coverage)} evidence coverage · {area.passed_count} passed ·{' '}
                {area.missing_count} missing · {area.unavailable_count} unavailable
              </CardDescription>
            </CardHeader>
            <CardContent className="grid gap-3">
              {area.top_findings.length === 0 ? (
                <p className="text-secondary text-sm">No missing HTTP-evidence checks.</p>
              ) : (
                area.top_findings.map((finding) => (
                  <div key={finding.rule_id} className="grid gap-1">
                    <span className="text-foreground text-sm font-medium">{finding.title}</span>
                    <span className="text-muted text-xs">
                      {finding.affected_pages} affected pages · {finding.remediation}
                    </span>
                  </div>
                ))
              )}
              {area.unavailable_checks.length > 0 ? (
                <p className="text-muted text-xs">
                  Unavailable without browser evidence: {area.unavailable_checks.join(', ')}.
                </p>
              ) : null}
            </CardContent>
          </Card>
        ))}
        <Alert tone="info">{data.limitations.join(' ')}</Alert>
      </div>
    </Drawer>
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
        <CardEyebrow>{title}</CardEyebrow>
        <p className="font-display text-foreground text-3xl font-semibold tracking-[-0.03em] tabular-nums">
          {value}
        </p>
      </CardHeader>
      <CardContent className="text-muted pt-0 text-xs">{detail}</CardContent>
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
        <CardEyebrow>{title}</CardEyebrow>
        <CardTitle className="text-lg">{value || 'Unavailable'}</CardTitle>
      </CardHeader>
    </Card>
  );
}
