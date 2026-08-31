import { useState } from 'react';

import { Card, CardContent } from '@/components/ui/card';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import { Pressable } from '@/components/ui/pressable';
import { MetricPanel } from '@/components/traffic/metric-panel';
import type { TrafficDashboard } from '@/lib/api/traffic';
import {
  bucketAdverb,
  countAxisTicks,
  countDomainMax,
  formatCountTick,
  toChartPoints,
  trafficStats,
  type TrafficGranularity,
} from '@/lib/traffic/traffic';
import { cn } from '@/lib/utils';

type MetricKey = 'clicks' | 'impressions' | 'ctr' | 'position';

const METRIC_ORDER: readonly MetricKey[] = ['clicks', 'impressions', 'ctr', 'position'];
const PANEL_GRID_COLUMNS: Readonly<Record<number, string>> = {
  1: 'grid-cols-1',
  2: 'grid-cols-1 sm:grid-cols-2',
  3: 'grid-cols-1 lg:grid-cols-3',
  4: 'grid-cols-1 sm:grid-cols-2 xl:grid-cols-4',
};
const METRIC_CONFIGS: Readonly<
  Record<
    MetricKey,
    {
      label: string;
      strokeClass: string;
      fillClass: string;
      bgSolid: string;
      bgActive: string;
      borderAccent: string;
      testId: string;
      description: string;
    }
  >
> = {
  clicks: {
    label: 'Clicks',
    strokeClass: 'stroke-chart-1',
    fillClass: 'fill-chart-1',
    bgSolid: 'bg-chart-1',
    bgActive: 'bg-chart-1/10',
    borderAccent: 'border-t-2 border-t-chart-1',
    testId: 'trend-chart-clicks',
    description: 'Google Search Console · clicks',
  },
  impressions: {
    label: 'Impressions',
    strokeClass: 'stroke-chart-2',
    fillClass: 'fill-chart-2',
    bgSolid: 'bg-chart-2',
    bgActive: 'bg-chart-2/10',
    borderAccent: 'border-t-2 border-t-chart-2',
    testId: 'trend-chart-impressions',
    description: 'Google Search Console · daily',
  },
  ctr: {
    label: 'CTR',
    strokeClass: 'stroke-chart-3',
    fillClass: 'fill-chart-3',
    bgSolid: 'bg-chart-3',
    bgActive: 'bg-chart-3/10',
    borderAccent: 'border-t-2 border-t-chart-3',
    testId: 'trend-chart-ctr',
    description: 'Click-through rate',
  },
  position: {
    label: 'Position',
    strokeClass: 'stroke-chart-5',
    fillClass: 'fill-chart-5',
    bgSolid: 'bg-chart-5',
    bgActive: 'bg-chart-5/10',
    borderAccent: 'border-t-2 border-t-chart-5',
    testId: 'trend-chart-average-position',
    description: 'Average position · lower is better',
  },
};
const STAT_ACCENT_CLASSES: Readonly<Record<string, string>> = {
  clicks: METRIC_CONFIGS.clicks.borderAccent,
  impressions: METRIC_CONFIGS.impressions.borderAccent,
  ctr: METRIC_CONFIGS.ctr.borderAccent,
  position: METRIC_CONFIGS.position.borderAccent,
  sessions: 'border-t-2 border-t-chart-6',
  conversions: 'border-t-2 border-t-chart-8',
};

function ctrDomainMax(points: ReturnType<typeof toChartPoints>): number {
  const max = points.reduce(
    (value, point) => (point.value !== null && point.value > value ? point.value : value),
    0,
  );
  return max <= 0 ? 10 : Math.min(100, Math.ceil(max / 5) * 5);
}
function positionDomainMax(points: ReturnType<typeof toChartPoints>): number {
  return Math.max(
    10,
    Math.ceil(
      points.reduce(
        (value, point) => (point.value !== null && point.value > value ? point.value : value),
        0,
      ),
    ),
  );
}
function formatter(key: MetricKey, value: number) {
  if (key === 'ctr') return `${value.toFixed(1)}%`;
  if (key === 'position') return value.toFixed(1);
  return value.toLocaleString('en-US');
}
function tickFormatter(key: MetricKey, value: number) {
  if (key === 'ctr') return `${Math.round(value)}%`;
  return key === 'position' ? `${Math.round(value)}` : formatCountTick(value);
}

export function UnifiedPerformanceCard({
  dashboard,
  granularity,
}: Readonly<{ dashboard: TrafficDashboard; granularity: TrafficGranularity }>) {
  const [activeMetrics, setActiveMetrics] = useState<Set<MetricKey>>(() => new Set(METRIC_ORDER));
  const stats = trafficStats(dashboard);
  const metricSeries = {
    clicks: toChartPoints(dashboard.series.clicks),
    impressions: toChartPoints(dashboard.series.impressions),
    ctr: toChartPoints(dashboard.series.ctr, { percent: true }),
    position: toChartPoints(dashboard.series.position),
  };
  const impressionMax = countDomainMax(dashboard.series.impressions);
  const panelDomains = {
    clicks: countDomainMax(dashboard.series.clicks),
    impressions: impressionMax,
    ctr: ctrDomainMax(metricSeries.ctr),
    position: positionDomainMax(metricSeries.position),
  };
  const activePanels = METRIC_ORDER.filter((key) => activeMetrics.has(key));
  const toggleMetric = (key: MetricKey) =>
    setActiveMetrics((current) => {
      const next = new Set(current);
      if (next.has(key) && next.size > 1) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <Card className="overflow-hidden">
      <div data-testid="traffic-stats" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {stats.map((stat) => (
          <StatCard
            key={stat.key}
            stat={stat}
            activeMetrics={activeMetrics}
            toggleMetric={toggleMetric}
            granularity={granularity}
            impressionMax={impressionMax}
          />
        ))}
      </div>
      <CardContent className="p-[var(--card-padding)]">
        <div
          data-testid="traffic-metric-panels"
          className={cn(
            'grid gap-[var(--workspace-gap)]',
            PANEL_GRID_COLUMNS[activePanels.length] ?? 'grid-cols-1',
          )}
        >
          {activePanels.map((key) => (
            <MetricPanel
              key={key}
              title={METRIC_CONFIGS[key].label}
              description={METRIC_CONFIGS[key].description}
              points={metricSeries[key]}
              domainMax={panelDomains[key]}
              formatTick={(value) => tickFormatter(key, value)}
              formatValue={(value) => formatter(key, value)}
              series={{
                strokeClass: METRIC_CONFIGS[key].strokeClass,
                fillClass: METRIC_CONFIGS[key].fillClass,
              }}
              invert={key === 'position'}
              testId={METRIC_CONFIGS[key].testId}
            />
          ))}
        </div>
      </CardContent>
    </Card>
  );
}

type Stat = ReturnType<typeof trafficStats>[number];

type StatCardProps = Readonly<{
  stat: Stat;
  activeMetrics: Set<MetricKey>;
  toggleMetric: (key: MetricKey) => void;
  granularity: TrafficGranularity;
  impressionMax: number;
}>;

function metricState(stat: Stat, activeMetrics: Set<MetricKey>) {
  const chartable = METRIC_ORDER.includes(stat.key as MetricKey);
  const key = stat.key as MetricKey;
  return { chartable, key, checked: chartable && activeMetrics.has(key) };
}

function StatCard(props: StatCardProps) {
  const state = metricState(props.stat, props.activeMetrics);
  if (!state.chartable) {
    return (
      <div data-testid={`stat-${props.stat.key}`} className={statClassName(props.stat, state)}>
        <StaticStat stat={props.stat} />
      </div>
    );
  }
  return (
    <Pressable
      type="button"
      data-testid={`stat-${props.stat.key}`}
      onClick={() => props.toggleMetric(state.key)}
      aria-pressed={state.checked}
      className={statClassName(props.stat, state)}
    >
      <ChartableStat
        stat={props.stat}
        state={state}
        granularity={props.granularity}
        impressionMax={props.impressionMax}
      />
    </Pressable>
  );
}

function statClassName(stat: Stat, state: ReturnType<typeof metricState>) {
  const accent = state.chartable
    ? state.checked
      ? METRIC_CONFIGS[state.key].borderAccent
      : 'border-t-2 border-t-muted/20'
    : (STAT_ACCENT_CLASSES[stat.key] ?? 'border-t-2 border-t-accent');
  return cn(
    'border-border grid gap-1 p-4 text-left transition-[background-color,border-color] select-none',
    state.chartable && 'cursor-pointer',
    accent,
    state.chartable && state.checked
      ? METRIC_CONFIGS[state.key].bgActive
      : 'hover:bg-background-alt/40',
  );
}

function ChartableStat({
  stat,
  state,
  granularity,
  impressionMax,
}: Readonly<{
  stat: Stat;
  state: ReturnType<typeof metricState>;
  granularity: TrafficGranularity;
  impressionMax: number;
}>) {
  return (
    <div>
      <div className="flex items-center justify-between gap-1">
        <span className={eyebrowClasses}>{stat.label}</span>
        <span
          className={cn(
            'text-3xs inline-flex size-4 items-center justify-center rounded border font-medium transition-colors',
            state.checked
              ? cn('text-inverse border-transparent', METRIC_CONFIGS[state.key].bgSolid)
              : 'border-border text-transparent',
          )}
        >
          ✓
        </span>
      </div>
      <StatValues stat={stat} />
      {stat.key === 'ctr' ? (
        <span className="sr-only">Click-through rate · 0–100% scale 100%</span>
      ) : null}
      {stat.key === 'impressions' ? (
        <span className="sr-only">
          Google Search Console · {bucketAdverb(granularity)}{' '}
          {countAxisTicks(impressionMax)[0] ?? '60K'}
        </span>
      ) : null}
    </div>
  );
}

function StaticStat({ stat }: Readonly<{ stat: Stat }>) {
  return (
    <>
      <span className={eyebrowClasses}>{stat.label}</span>
      <StatValues stat={stat} />
    </>
  );
}

function StatValues({ stat }: Readonly<{ stat: Stat }>) {
  const delta =
    stat.tone === 'up' ? 'text-score-high' : stat.tone === 'down' ? 'text-score-low' : 'text-muted';
  return (
    <>
      <span
        className={cn(
          'mono text-2xl font-medium tabular-nums tracking-[-0.02em]',
          stat.placeholder ? 'text-muted' : 'text-foreground',
        )}
      >
        {stat.value}
      </span>
      <span className={cn('text-xs font-medium tabular-nums', delta)}>{stat.delta}</span>
    </>
  );
}
