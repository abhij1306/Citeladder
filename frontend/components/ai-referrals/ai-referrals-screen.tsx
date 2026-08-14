'use client';

import { keepPreviousData, useQuery } from '@tanstack/react-query';
import { ChevronDown, Loader2 } from 'lucide-react';
import { useMemo, useState } from 'react';

import { AiReferralsEmptyState } from '@/components/ai-referrals/empty-state';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Dropdown,
  DropdownContent,
  DropdownLabel,
  DropdownRadioGroup,
  DropdownRadioItem,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import { SegmentedControl } from '@/components/ui/segmented-control';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { TrendChart, type TrendPoint } from '@/components/ui/trend-chart';
import { aiReferralsApi, type AiReferrals } from '@/lib/api/ai-referrals';
import { queryKeys } from '@/lib/api/query-keys';
import {
  GRANULARITY_OPTIONS,
  RANGE_OPTIONS,
  bucketCountLabel,
  rangeLabel,
  rangeToWindow,
  type AiReferralsGranularity,
  type AiReferralsRange,
} from '@/lib/ai-referrals/options';
import {
  aiSourceLabel,
  countDomainMax,
  countYLabels,
  formatInt,
  formatPercent,
  isAiReferralsEmpty,
  toCountChartPoints,
  toPercentChartPoints,
  totalSourceSessions,
} from '@/lib/ai-referrals/series';
import { formatWindowDate } from '@/lib/format';
import { useProjectContext } from '@/lib/project/project-context';
import { cn } from '@/lib/utils';

const CHIP_ACTIVE_CLASS =
  'border-accent-border bg-accent-soft text-accent-text hover:border-accent-border hover:bg-accent-soft hover:text-accent-text';

export function AiReferralsScreen() {
  const { activeProject, isLoading: isProjectLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;
  const [range, setRange] = useState<AiReferralsRange>('latest');
  const [granularity, setGranularity] = useState<AiReferralsGranularity>('week');
  const windowBounds = useMemo(() => rangeToWindow(range), [range]);

  const dashboardQuery = useQuery({
    queryKey: queryKeys.aiReferrals.dashboard(projectId ?? '', {
      from: windowBounds.from ?? null,
      to: windowBounds.to ?? null,
      granularity,
    }),
    queryFn: ({ signal }) =>
      aiReferralsApi.getDashboard(projectId!, { ...windowBounds, granularity }, { signal }),
    enabled: Boolean(projectId),
    placeholderData: keepPreviousData,
  });

  if (isProjectLoading || (Boolean(projectId) && dashboardQuery.isLoading)) {
    return <AiReferralsSkeleton />;
  }
  if (!projectId) return <Alert tone="info">Select or create a project to see AI referrals.</Alert>;
  if (dashboardQuery.isError) {
    return (
      <Alert tone="danger">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span>AI referrals could not be loaded. Check your connection and try again.</span>
          <Button variant="secondary" size="sm" onClick={() => dashboardQuery.refetch()}>
            Retry
          </Button>
        </div>
      </Alert>
    );
  }

  const data = dashboardQuery.data ?? null;
  const empty = data ? isAiReferralsEmpty(data) : true;
  if (!data || (empty && range === 'latest')) return <AiReferralsEmptyState />;

  const toolbar = (
    <AiReferralsToolbar
      range={range}
      onChangeRange={setRange}
      granularity={granularity}
      onChangeGranularity={setGranularity}
      fetching={dashboardQuery.isFetching}
    />
  );

  if (empty) {
    return (
      <div className="grid gap-6">
        {toolbar}
        <Alert tone="info">
          No synced AI-referral snapshot covers {formatWindowDate(windowBounds.from ?? '')} –{' '}
          {formatWindowDate(windowBounds.to ?? '')}. Switch to the latest synced window or run a
          sync from Traffic.
        </Alert>
      </div>
    );
  }

  return (
    <div className="grid gap-6">
      {toolbar}
      <div aria-busy={dashboardQuery.isFetching} className="grid gap-6">
        <div className="grid gap-6 lg:grid-cols-2">
          <ReferralVolumeCard data={data} />
          <ReferralShareCard data={data} />
        </div>
        <SourceTotals data={data} />
      </div>
    </div>
  );
}

function AiReferralsToolbar({
  range,
  onChangeRange,
  granularity,
  onChangeGranularity,
  fetching,
}: Readonly<{
  range: AiReferralsRange;
  onChangeRange: (range: AiReferralsRange) => void;
  granularity: AiReferralsGranularity;
  onChangeGranularity: (granularity: AiReferralsGranularity) => void;
  fetching: boolean;
}>) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="ai-referrals-toolbar">
      <Dropdown>
        <DropdownTrigger asChild>
          <Button
            variant="secondary"
            size="sm"
            aria-label="Select date range"
            className={cn(range !== 'latest' && CHIP_ACTIVE_CLASS)}
          >
            <span className="text-muted">Range:</span>
            <span className="font-medium">{rangeLabel(range)}</span>
            <ChevronDown className="text-muted size-3" aria-hidden />
          </Button>
        </DropdownTrigger>
        <DropdownContent>
          <DropdownLabel>Date range</DropdownLabel>
          <DropdownRadioGroup value={range}>
            {RANGE_OPTIONS.map((option) => (
              <DropdownRadioItem
                key={option.value}
                value={option.value}
                onSelect={() => onChangeRange(option.value)}
              >
                {option.label}
              </DropdownRadioItem>
            ))}
          </DropdownRadioGroup>
        </DropdownContent>
      </Dropdown>
      <SegmentedControl
        value={granularity}
        onChange={onChangeGranularity}
        options={GRANULARITY_OPTIONS}
        ariaLabel="Chart interval"
      />
      <output className="text-muted flex items-center gap-1.5 text-xs">
        {fetching ? (
          <>
            <Loader2 className="size-3.5 animate-spin" aria-hidden />
            Updating data… Previous data shown.
          </>
        ) : null}
      </output>
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

export function AiReferralsSkeleton() {
  return (
    <div className="grid gap-6" aria-hidden>
      <div className="flex flex-wrap gap-2">
        <Skeleton className="h-8 w-40 rounded-full" />
        <Skeleton className="h-10 w-60 rounded-full" />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        {[0, 1].map((index) => (
          <Skeleton key={index} className="h-72" />
        ))}
      </div>
      <Skeleton className="h-56" />
    </div>
  );
}
