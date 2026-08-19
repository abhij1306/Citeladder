import type { ReactNode } from 'react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { TrendChart, type TrendPoint } from '@/components/ui/trend-chart';
import type { AiReferrals } from '@/lib/api/ai-referrals';
import {
  aiSourceLabel,
  countDomainMax,
  countYLabels,
  formatInt,
  formatPercent,
  toCountChartPoints,
  toPercentChartPoints,
  totalSourceSessions,
} from '@/lib/ai-referrals/series';
import { bucketCountLabel } from '@/lib/ai-referrals/options';
import { formatWindowDate } from '@/lib/format';

export function AiReferralsDashboard({
  data,
  toolbar,
  fetching,
}: Readonly<{ data: AiReferrals; toolbar: ReactNode; fetching: boolean }>) {
  return (
    <div className="grid gap-6">
      {toolbar}
      <div aria-busy={fetching} className="grid gap-6">
        <div className="grid gap-6 lg:grid-cols-2">
          <ReferralVolumeCard data={data} />
          <ReferralShareCard data={data} />
        </div>
        <SourceTotals data={data} />
      </div>
    </div>
  );
}

function TrendCard({
  title,
  description,
  badge,
  points,
  yLabels,
  domainMax,
}: Readonly<{
  title: string;
  description: string;
  badge: string;
  points: TrendPoint[];
  yLabels: string[];
  domainMax?: number;
}>) {
  const firstLabel = points[0]?.label ?? '';
  const lastLabel = points.at(-1)?.label ?? '';
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="grid gap-1">
            <CardTitle>{title}</CardTitle>
            <CardDescription>{description}</CardDescription>
          </div>
          <span className="text-muted text-xs">{badge}</span>
        </div>
      </CardHeader>
      <CardContent>
        <div className="flex gap-3">
          <div
            className="text-2xs text-muted flex flex-col justify-between py-1 tabular-nums"
            aria-hidden
          >
            {yLabels.map((label) => (
              <span key={label}>{label}</span>
            ))}
          </div>
          <div className="min-w-0 flex-1">
            <TrendChart
              label={title}
              data={points}
              width={680}
              height={180}
              domainMax={domainMax}
              className="h-45 w-full"
            />
            {points.length > 1 ? (
              <div
                className="text-2xs text-muted mt-1 flex justify-between tabular-nums"
                aria-hidden
              >
                <span>{firstLabel}</span>
                <span>{lastLabel}</span>
              </div>
            ) : null}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function ReferralVolumeCard({ data }: Readonly<{ data: AiReferrals }>) {
  const values = data.referral_volume.flatMap((point) =>
    point.value === null ? [] : [point.value],
  );
  const domainMax = countDomainMax(values);
  return (
    <TrendCard
      title="AI-referred sessions"
      description="GA4 sessions whose source matches a known AI assistant"
      badge={bucketCountLabel(data.granularity, data.referral_volume.length)}
      points={toCountChartPoints(data.referral_volume)}
      yLabels={countYLabels(domainMax)}
      domainMax={domainMax}
    />
  );
}

function ReferralShareCard({ data }: Readonly<{ data: AiReferrals }>) {
  return (
    <TrendCard
      title="Share of GA4 sessions"
      description="AI-referred sessions divided by all sessions in the same GA4 source report"
      badge={bucketCountLabel(data.granularity, data.referral_share.length)}
      points={toPercentChartPoints(data.referral_share)}
      yLabels={['100%', '75%', '50%', '25%', '0%']}
    />
  );
}

function SourceTotals({ data }: Readonly<{ data: AiReferrals }>) {
  const total = totalSourceSessions(data.sources);
  const measured = data.referral_volume.some((point) => point.value !== null);
  return (
    <Card>
      <CardHeader>
        <CardTitle>AI referral sources</CardTitle>
        <CardDescription>
          {formatInt(total)} identified sessions for {formatWindowDate(data.window_start)} –{' '}
          {formatWindowDate(data.window_end)}. Shares use all GA4 source-report sessions as the
          denominator.
        </CardDescription>
      </CardHeader>
      {data.sources.length ? (
        <SourceTotalsTable data={data} />
      ) : (
        <CardContent>
          <p className="text-secondary text-sm">
            {measured
              ? 'GA4 data was measured, but no sessions matched a known AI source in this window.'
              : 'AI-referral classification is not complete for this window, so source totals are unavailable.'}
          </p>
        </CardContent>
      )}
    </Card>
  );
}

function SourceTotalsTable({ data }: Readonly<{ data: AiReferrals }>) {
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Source</TableHead>
          <TableHead numeric>Sessions</TableHead>
          <TableHead numeric>Share of GA4 sessions</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {data.sources.map((source) => (
          <TableRow key={source.ai_source}>
            <TableCell>{aiSourceLabel(source.ai_source)}</TableCell>
            <TableCell numeric>
              <span className="tabular-nums">{formatInt(source.sessions)}</span>
            </TableCell>
            <TableCell numeric>
              <span className="tabular-nums">{formatPercent(source.share, 1)}</span>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
