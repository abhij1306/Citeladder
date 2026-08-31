import { Activity, AlertTriangle, ArrowUpRight, Split, Zap, type LucideIcon } from 'lucide-react';
import type { ReactNode } from 'react';

import { UnavailableValue } from '@/components/ui/unavailable-value';
import { MetricGroup, MetricItem } from '@/components/ui/workspace';
import type { DemandSnapshot } from '@/lib/api/demand';
import { countByTab, detectorStates, isActionableGap, numericMetric } from '@/lib/demand/signals';

function KpiSegment({
  label,
  value,
  caption,
  icon: Icon,
  iconClassName,
  className,
}: Readonly<{
  label: string;
  value: ReactNode;
  caption: string;
  icon: LucideIcon;
  iconClassName: string;
  className?: string;
}>) {
  return (
    <MetricItem
      label={label}
      value={value}
      detail={caption}
      marker={<Icon className={`${iconClassName} size-4 shrink-0`} aria-hidden="true" />}
      className={className}
    />
  );
}

/** `activeDetectors/totalDetectors` plus the caption that describes it. */
function detectorHealth(summary: Record<string, unknown>): {
  value: string | null;
  caption: string;
} {
  const entries = Object.values(detectorStates(summary));
  if (entries.length === 0) {
    // No detector block at all — say so rather than claiming full coverage,
    // which `0 === 0` would otherwise do.
    return { value: null, caption: 'No detector status reported' };
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
    <MetricGroup className="lg:grid-cols-5">
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
        value={health.value ?? <UnavailableValue state="unknown" />}
        caption={health.caption}
        icon={Activity}
        iconClassName="text-success"
        className="sm:col-span-2 lg:col-span-1"
      />
    </MetricGroup>
  );
}
