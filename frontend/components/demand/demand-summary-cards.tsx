import { Activity, AlertTriangle, ArrowUpRight, Split, Zap, type LucideIcon } from 'lucide-react';

import type { DemandSnapshot } from '@/lib/api/demand';
import { countByTab, detectorStates, isActionableGap, numericMetric } from '@/lib/demand/signals';
import { availabilityLabel } from '@/lib/format';

function KpiSegment({
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
    <div
      className={`hover:bg-panel-tonal/40 flex flex-col justify-between p-4.5 transition-colors sm:p-5 ${className ?? ''}`}
    >
      <div className="text-muted flex items-center justify-between text-xs font-semibold tracking-wider uppercase">
        <span className="truncate">{label}</span>
        <Icon className={`${iconClassName} ml-2 size-4 shrink-0`} aria-hidden="true" />
      </div>
      <div className="text-foreground font-display mt-2 text-2xl font-semibold tabular-nums">
        {value}
      </div>
      <p className="text-muted mt-1 text-xs leading-relaxed">{caption}</p>
    </div>
  );
}

/** `activeDetectors/totalDetectors` plus the caption that describes it. */
function detectorHealth(summary: Record<string, unknown>): { value: string; caption: string } {
  const entries = Object.values(detectorStates(summary));
  if (entries.length === 0) {
    // No detector block at all — say so rather than claiming full coverage,
    // which `0 === 0` would otherwise do.
    return { value: availabilityLabel('unknown'), caption: 'No detector status reported' };
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
    <div className="bg-panel shadow-card border-border/70 overflow-hidden rounded-sm border">
      <div className="divide-border/60 grid grid-cols-1 divide-y sm:grid-cols-2 lg:grid-cols-5 lg:divide-x lg:divide-y-0">
        <KpiSegment
          label="Latent Search Demand"
          value={latentImpressions.toLocaleString('en-US')}
          caption="Impressions in ranking gaps"
          icon={Zap}
          iconClassName="text-accent"
        />
        <KpiSegment
          label="Striking Distance"
          value={String(countByTab(signals, 'striking_distance'))}
          caption="Positions 4–15 quick wins"
          icon={ArrowUpRight}
          iconClassName="text-info"
        />
        <KpiSegment
          label="Cannibalization"
          value={String(countByTab(signals, 'cannibalization'))}
          caption="Internal URL conflicts"
          icon={Split}
          iconClassName="text-warning"
        />
        <KpiSegment
          label="CTR Underperformers"
          value={String(countByTab(signals, 'ctr_gap'))}
          caption="Below position benchmark"
          icon={AlertTriangle}
          iconClassName="text-danger"
        />
        <KpiSegment
          label="Detector Health"
          value={health.value}
          caption={health.caption}
          icon={Activity}
          iconClassName="text-success"
          className="sm:col-span-2 lg:col-span-1"
        />
      </div>
    </div>
  );
}
