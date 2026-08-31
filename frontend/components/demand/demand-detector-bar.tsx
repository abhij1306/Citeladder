import { Info } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Pressable } from '@/components/ui/pressable';
import { Tooltip } from '@/components/ui/tooltip';
import type { DemandSnapshot } from '@/lib/api/demand';
import { detectorStates } from '@/lib/demand/signals';

const DETECTOR_DEFINITIONS: Record<
  string,
  { label: string; description: string; requirements: string }
> = {
  striking_distance: {
    label: 'Striking distance',
    description: 'Finds queries ranking on positions 4–15 with high impressions.',
    requirements: 'Requires non-branded queries, >=50 impressions, and avg position 4.0–15.0.',
  },
  cannibalization: {
    label: 'Cannibalization',
    description: 'Detects queries where 2+ distinct pages compete and split impressions.',
    requirements:
      'Requires resolved non-branded queries with >=2 pages having >=20 imp and >=10% share.',
  },
  property_relative_ctr_gap: {
    label: 'CTR gap',
    description: 'Detects queries/pages underperforming expected CTR for their position band.',
    requirements:
      'Requires cohort of >=20 queries and >=500 impressions in the property position band.',
  },
  query_trends: {
    label: 'Query trends',
    description: 'Detects emerging (≥1.5x) and declining (≤0.67x) search momentum.',
    requirements:
      'Requires at least 28 days of daily continuous Search Console coverage across both 14d windows.',
  },
};

function detectorBadgeValue(state: string): 'success' | 'warning' | 'info' | 'danger' {
  switch (state) {
    case 'available':
      return 'success';
    case 'partial':
      return 'warning';
    case 'insufficient_history':
      return 'info';
    default:
      return 'danger';
  }
}

function detectorStateLabel(state: string): string {
  switch (state) {
    case 'available':
      return 'Active';
    case 'partial':
      return 'Partial';
    case 'insufficient_history':
      return 'Needs 28d history';
    case 'unavailable':
      return 'Unavailable';
    default:
      return state.replace(/_/g, ' ');
  }
}

export function DemandDetectorBar({ snapshot }: Readonly<{ snapshot: DemandSnapshot }>) {
  const detectors = detectorStates(snapshot.summary);

  const limitations = Array.from(
    new Set(snapshot.signals.flatMap((signal) => signal.limitations).filter(Boolean)),
  );

  return (
    <div className="bg-well border-border-subtle flex flex-col gap-2.5 rounded-md border p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-muted text-xs font-medium">Detectors:</span>
        {Object.entries(DETECTOR_DEFINITIONS).map(([key, meta]) => {
          const rawState = detectors[key]?.state ?? 'unavailable';
          const badgeTone = detectorBadgeValue(rawState);
          const stateText = detectorStateLabel(rawState);
          const detectorLimitations = detectors[key]?.limitations ?? [];

          return (
            <Tooltip
              key={key}
              content={
                <div className="max-w-xs p-1 text-xs">
                  <p className="font-medium">{meta.label}</p>
                  <p className="mt-1 opacity-90">{meta.description}</p>
                  <p className="mt-1.5 border-t border-white/20 pt-1.5 text-xs opacity-75">
                    {meta.requirements}
                  </p>
                  {detectorLimitations.length > 0 && (
                    <p className="text-warning-text mt-1 text-xs font-medium">
                      Note: {detectorLimitations.join(' ')}
                    </p>
                  )}
                </div>
              }
            >
              <Pressable
                type="button"
                className="bg-panel border-border hover:border-border-strong flex cursor-help items-center gap-1.5 rounded border px-2 py-1 text-xs transition-colors"
              >
                <span className="text-foreground font-medium">{meta.label}</span>
                <Badge variant="status" value={badgeTone}>
                  {stateText}
                </Badge>
              </Pressable>
            </Tooltip>
          );
        })}
      </div>

      <div className="text-muted flex items-center gap-1.5 text-xs">
        <Info className="size-3 shrink-0" aria-hidden="true" />
        <span>
          {limitations.length > 0
            ? limitations.join(' ')
            : 'GSC detail rows may omit privacy-filtered queries.'}
        </span>
      </div>
    </div>
  );
}
