import { Activity, AlertTriangle, ArrowUpRight, Split, Zap } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { Card, CardContent } from '@/components/ui/card';
import type { DemandSnapshot } from '@/lib/api/demand';
import { countByTab, detectorStates, isActionableGap, numericMetric } from '@/lib/demand/signals';

function KpiCard({
  label,
  value,
  caption,
  icon: Icon,
  iconClassName,
  className,
}: Readonly<{
  label: string;
  value: string;
  caption: string;
  icon: LucideIcon;
  iconClassName: string;
  className?: string;
}>) {
  return (
    <Card
      className={`bg-panel border-border hover:border-border-strong transition-all ${className ?? ''}`}
    >
      <CardContent className="p-3.5">
        <div className="text-muted flex items-center justify-between text-xs">
          <span className="font-medium">{label}</span>
          <Icon className={`${iconClassName} size-3.5`} aria-hidden="true" />
        </div>
        <div className="text-foreground mt-2 text-xl font-semibold tabular-nums">{value}</div>
        <p className="text-muted mt-0.5 text-xs">{caption}</p>
      </CardContent>
    </Card>
  );
}

/** `activeDetectors/totalDetectors` plus the caption that describes it. */
function detectorHealth(summary: Record<string, unknown>): { value: string; caption: string } {
  const entries = Object.values(detectorStates(summary));
  if (entries.length === 0) {
    // No detector block at all — say so rather than claiming full coverage,
    // which `0 === 0` would otherwise do.
    return { value: '—', caption: 'No detector status reported' };
  }
  const active = entries.filter(
    (detector) => detector?.state === 'available' || detector?.state === 'partial',
  ).length;
  return {
    value: `${active}/${entries.length}`,
    caption: active === entries.length ? 'All detectors active' : 'Partial coverage',
  };
}

export function DemandSummaryCards({ snapshot }: Readonly<{ snapshot: DemandSnapshot }>) {
  const { signals } = snapshot;

  // Latent demand = impressions across every non-branded (actionable) signal.
  const latentImpressions = signals
    .filter(isActionableGap)
    .reduce((sum, signal) => sum + (numericMetric(signal, 'impressions') ?? 0), 0);

  const health = detectorHealth(snapshot.summary);

  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
      <KpiCard
        label="Latent Search Demand"
        value={latentImpressions.toLocaleString('en-US')}
        caption="Impressions in ranking gaps"
        icon={Zap}
        iconClassName="text-accent"
      />
      <KpiCard
        label="Striking Distance"
        value={String(countByTab(signals, 'striking_distance'))}
        caption="Positions 4–15 quick wins"
        icon={ArrowUpRight}
        iconClassName="text-info"
      />
      <KpiCard
        label="Cannibalization"
        value={String(countByTab(signals, 'cannibalization'))}
        caption="Internal URL conflicts"
        icon={Split}
        iconClassName="text-warning"
      />
      <KpiCard
        label="CTR Underperformers"
        value={String(countByTab(signals, 'ctr_gap'))}
        caption="Below position benchmark"
        icon={AlertTriangle}
        iconClassName="text-danger"
      />
      <KpiCard
        label="Detector Health"
        value={health.value}
        caption={health.caption}
        icon={Activity}
        iconClassName="text-success"
        className="col-span-2 sm:col-span-1"
      />
    </div>
  );
}
