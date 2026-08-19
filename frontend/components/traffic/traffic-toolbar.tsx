import { Loader2, RefreshCw } from 'lucide-react';

import { AnalyticsToolbar } from '@/components/ui/analytics-toolbar';
import { Button } from '@/components/ui/button';
import {
  GRANULARITY_OPTIONS,
  RANGE_OPTIONS,
  rangeLabel,
  type TrafficGranularity,
  type TrafficRange,
} from '@/lib/traffic/traffic';

export function TrafficToolbar({
  range,
  onChangeRange,
  granularity,
  onChangeGranularity,
  note,
  syncing,
  syncPending,
  fetching,
  onSyncNow,
}: Readonly<{
  range: TrafficRange;
  onChangeRange: (range: TrafficRange) => void;
  granularity: TrafficGranularity;
  onChangeGranularity: (granularity: TrafficGranularity) => void;
  note: string;
  syncing: boolean;
  syncPending: boolean;
  fetching: boolean;
  onSyncNow: () => void;
}>) {
  return (
    <AnalyticsToolbar
      range={range}
      defaultRange="latest"
      rangeLabel={rangeLabel(range)}
      rangeOptions={RANGE_OPTIONS}
      onChangeRange={onChangeRange}
      granularity={granularity}
      granularityOptions={GRANULARITY_OPTIONS}
      onChangeGranularity={onChangeGranularity}
      fetching={fetching}
      testId="traffic-toolbar"
      trailing={
        <div className="ml-auto flex items-center gap-3">
          <span className="text-2xs text-muted">{note}</span>
          <Button
            variant="secondary"
            size="sm"
            onClick={onSyncNow}
            disabled={syncing || syncPending}
            data-testid="sync-now-button"
          >
            {syncing || syncPending ? (
              <>
                <Loader2 className="size-4 animate-spin" aria-hidden />
                Syncing…
              </>
            ) : (
              <>
                <RefreshCw className="size-4" aria-hidden />
                Sync now
              </>
            )}
          </Button>
        </div>
      }
    />
  );
}
