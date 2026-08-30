'use client';

import { useState } from 'react';
import Link from 'next/link';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Drawer } from '@/components/ui/drawer';
import { ScoreBar } from '@/components/ui/score-bar';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { TrendChart } from '@/components/ui/trend-chart';
import type { SiteHealthOverview } from '@/lib/api/types';
import { PLACEHOLDER, statusLabel } from '@/lib/site-health/status';

function percent(value: number | null): string {
  return value === null ? PLACEHOLDER : `${Math.round(value * 100)}%`;
}

export function OverviewDetails({ data }: Readonly<{ data: SiteHealthOverview }>) {
  const [webFundamentalsOpen, setWebFundamentalsOpen] = useState(false);
  return (
    <>
      {data.limitations.length > 0 ? <Alert tone="info">{data.limitations.join(' ')}</Alert> : null}
      <div className="grid min-w-0 gap-4 xl:grid-cols-[1.15fr_1fr]">
        <DimensionLedger dimensions={data.aeo_dimensions} />
        <TopIssues issues={data.top_issues} />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <WebFundamentalsCard
          data={data.web_fundamentals}
          onOpen={() => setWebFundamentalsOpen(true)}
        />
        <TrendCard data={data.trend} />
        <ChangeSummaryCard data={data.change_summary} />
      </div>
      <WebFundamentalsDrawer
        data={data.web_fundamentals}
        open={webFundamentalsOpen}
        onOpenChange={setWebFundamentalsOpen}
      />
    </>
  );
}

export function OverviewDetailsSkeleton() {
  return (
    <div className="grid gap-4" aria-busy="true" aria-label="Loading Overview details">
      <div className="grid gap-4 xl:grid-cols-[1.15fr_1fr]" aria-hidden>
        {[0, 1].map((key) => (
          <Card key={key}>
            <CardContent className="grid gap-3 p-[var(--card-padding)]">
              <Skeleton className="h-5 w-40" />
              {Array.from({ length: 5 }, (_, index) => (
                <Skeleton key={index} className="h-10 w-full" />
              ))}
            </CardContent>
          </Card>
        ))}
      </div>
      <div className="grid gap-4 xl:grid-cols-3" aria-hidden>
        {[0, 1, 2].map((key) => (
          <Card key={key}>
            <CardContent className="grid gap-3 p-[var(--card-padding)]">
              <Skeleton className="h-5 w-36" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-4 w-3/4" />
            </CardContent>
          </Card>
        ))}
      </div>
    </div>
  );
}

function DimensionLedger({
  dimensions,
}: Readonly<{ dimensions: SiteHealthOverview['aeo_dimensions'] }>) {
  return (
    <Card id="site-readiness-pillars">
      <CardHeader bordered>
        <CardTitle>AEO Readiness by pillar</CardTitle>
        <CardDescription>Observed quality and evidence coverage stay separate.</CardDescription>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Pillar</TableHead>
              <TableHead numeric>Score</TableHead>
              <TableHead>Quality</TableHead>
              <TableHead numeric>Coverage</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {dimensions.map((dimension) => (
              <TableRow key={dimension.key}>
                <TableCell>
                  {/* The subtitle stays a single row: the ledger is a scanning
                      surface, and a wrapping sentence pushes the score columns
                      off a screenful. Full text stays available on hover. */}
                  <div className="grid max-w-md min-w-0 gap-1">
                    <span className="text-foreground font-medium">{dimension.label}</span>
                    <span className="text-muted truncate text-xs" title={dimension.description}>
                      {dimension.description}
                    </span>
                    {dimension.reason === 'measured_at_site_scope' ? (
                      <span className="text-muted text-xs">Measured at site scope</span>
                    ) : null}
                  </div>
                </TableCell>
                <TableCell numeric>{dimension.score ?? PLACEHOLDER}</TableCell>
                <TableCell className="min-w-32">
                  {dimension.score === null ? (
                    <span className="text-muted text-xs">
                      {dimension.reason === 'measured_at_site_scope'
                        ? 'Site-scoped evidence'
                        : statusLabel(dimension.dimension_measurement_state)}
                    </span>
                  ) : (
                    <ScoreBar value={dimension.score} label={`${dimension.label} score`} />
                  )}
                </TableCell>
                <TableCell numeric>{percent(dimension.coverage)}</TableCell>
              </TableRow>
            ))}
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
        <div className="flex items-start justify-between gap-3">
          <div>
            <CardTitle>Top issues</CardTitle>
            <CardDescription>Highest-impact persisted defects and readiness gaps.</CardDescription>
          </div>
          <Button asChild variant="secondary" size="sm">
            <Link href="/issues">View all issues</Link>
          </Button>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Impact</TableHead>
              <TableHead>Issue</TableHead>
              <TableHead>Type</TableHead>
              <TableHead numeric>Pages</TableHead>
              <TableHead>Effect</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {issues.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="text-secondary text-sm">
                  No persisted issues.
                </TableCell>
              </TableRow>
            ) : (
              issues.map((issue) => (
                <TableRow key={`${issue.rule_id}-${issue.finding_class}`}>
                  <TableCell>
                    {issue.finding_class === 'advisory' ? (
                      <Badge>{issue.impact_label}</Badge>
                    ) : (
                      <Badge variant="status" value={severityTone(issue.severity)}>
                        {statusLabel(issue.severity)}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell>
                    <Link
                      className="text-foreground font-medium underline decoration-transparent hover:decoration-current"
                      href={issueHref(issue.rule_id, issue.finding_class)}
                    >
                      {issue.description || issue.rule_id}
                    </Link>
                  </TableCell>
                  <TableCell>{statusLabel(issue.finding_class)}</TableCell>
                  <TableCell numeric>{issue.affected_pages}</TableCell>
                  <TableCell>
                    <ScoreEffect roles={issue.score_roles} />
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

function WebFundamentalsCard({
  data,
  onOpen,
}: Readonly<{ data: SiteHealthOverview['web_fundamentals']; onOpen: () => void }>) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Web Fundamentals</CardTitle>
        <CardDescription>Persisted HTTP evidence across four areas.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4 pt-0">
        <div className="grid grid-cols-2 gap-2">
          {data.areas.map((area) => (
            <div
              key={area.key}
              className="border-border-subtle bg-well grid gap-1 rounded-sm border p-3"
            >
              <span className="text-foreground text-xs font-medium capitalize">{area.key}</span>
              <Badge variant="status" value={measurementTone(area.state)}>
                {statusLabel(area.state)}
              </Badge>
            </div>
          ))}
        </div>
        <Button variant="secondary" size="sm" onClick={onOpen} className="justify-self-start">
          View evidence
        </Button>
      </CardContent>
    </Card>
  );
}

function TrendCard({ data }: Readonly<{ data: SiteHealthOverview['trend'] }>) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>AEO Readiness trend</CardTitle>
        <CardDescription>Comparable terminal crawl snapshots only.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-2 pt-0">
        <TrendChart data={data.series} label="AEO Readiness trend" className="h-auto w-full" />
        {data.state === 'unavailable' ? (
          <p className="text-muted text-xs">Run a second comparable crawl to establish a trend.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

/**
 * Change-summary labels are frozen into the snapshot at build time, so a
 * Presentation resolves change-summary labels from the stable metric key.
 */
const CHANGE_METRIC_LABELS: Record<string, string> = {
  web_fundamentals_score: 'Web Fundamentals',
  web_fundamentals_coverage: 'Web Fundamentals coverage',
  aeo_readiness_score: 'AEO Readiness',
  aeo_measurement_coverage: 'AEO coverage',
};

function ChangeSummaryCard({ data }: Readonly<{ data: SiteHealthOverview['change_summary'] }>) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Change summary</CardTitle>
        <CardDescription>Change since the previous comparable crawl.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3 pt-0">
        {data.metrics.map((metric) => (
          <div key={metric.key} className="flex items-center justify-between gap-3 text-sm">
            <span className="text-secondary">
              {CHANGE_METRIC_LABELS[metric.key] ?? metric.label}
            </span>
            <span className="text-foreground font-medium tabular-nums">
              {directionIndicator(metric.direction)} {formatDelta(metric.delta, metric.key)}
            </span>
          </div>
        ))}
        {data.state === 'unavailable' ? (
          <p className="text-muted text-xs">No comparable snapshot yet.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function directionIndicator(direction: string): string {
  if (direction === 'increased') return '↑';
  if (direction === 'decreased') return '↓';
  if (direction === 'unchanged') return '→';
  return '·';
}

/**
 * Which site score a rule feeds. A rule can feed both scores, and a diagnostic
 * rule feeds neither. Short labels keep the column narrow next to the ledger.
 */
const SCORE_ROLE_LABELS: Record<string, string> = {
  web_fundamentals: 'Web',
  aeo_readiness: 'AEO',
};

function ScoreEffect({ roles }: Readonly<{ roles: readonly string[] }>) {
  const labels = roles.flatMap((role) => {
    const label = SCORE_ROLE_LABELS[role];
    return label ? [[role, label] as const] : [];
  });
  if (labels.length === 0) return <span className="text-muted text-xs">{PLACEHOLDER}</span>;
  return (
    <div className="flex flex-wrap gap-1">
      {labels.map(([role, label]) => (
        <Badge key={role}>{label}</Badge>
      ))}
    </div>
  );
}

function severityTone(severity: string): 'danger' | 'warning' | 'info' {
  if (severity === 'critical' || severity === 'high') return 'danger';
  if (severity === 'medium') return 'warning';
  if (severity === 'low' || severity === 'info') return 'info';
  return 'info';
}

function measurementTone(state: string): 'success' | 'warning' | 'info' {
  if (state === 'measured') return 'success';
  if (state === 'limited_evidence') return 'warning';
  return 'info';
}

function issueHref(ruleId: string, findingClass: string): string {
  const params = new URLSearchParams({ rule: ruleId });
  if (findingClass === 'advisory') params.set('finding_class', findingClass);
  return `/issues?${params.toString()}`;
}

function formatDelta(delta: number | null, key: string): string {
  if (delta === null) return PLACEHOLDER;
  const value = key.endsWith('_coverage') ? delta * 100 : delta;
  return `${value > 0 ? '+' : ''}${Math.round(value)}${key.endsWith('_coverage') ? ' pp' : ''}`;
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
                <Badge variant="status" value={measurementTone(area.state)}>
                  {statusLabel(area.state)}
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
        <Alert tone="info">
          Field Core Web Vitals: {statusLabel(data.field_data.state)} —{' '}
          {statusLabel(data.field_data.reason)}.
        </Alert>
        {data.limitations.length > 0 ? (
          <Alert tone="info">{data.limitations.join(' ')}</Alert>
        ) : null}
      </div>
    </Drawer>
  );
}
