import { ChevronDown, Loader2 } from 'lucide-react';

import { Button } from '@/components/ui/button';
import {
  Dropdown,
  DropdownContent,
  DropdownLabel,
  DropdownRadioGroup,
  DropdownRadioItem,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import { SegmentedControl } from '@/components/ui/segmented-control';
import { cn } from '@/lib/utils';

const ACTIVE_CLASS =
  'border-accent-border bg-accent-soft text-accent-text hover:border-accent-border hover:bg-accent-soft hover:text-accent-text';

export function AnalyticsToolbar<Range extends string, Granularity extends string>({
  range,
  defaultRange,
  rangeLabel,
  rangeOptions,
  onChangeRange,
  granularity,
  granularityOptions,
  onChangeGranularity,
  fetching,
  testId,
  trailing,
}: Readonly<{
  range: Range;
  defaultRange: Range;
  rangeLabel: string;
  rangeOptions: readonly { value: Range; label: string }[];
  onChangeRange: (range: Range) => void;
  granularity: Granularity;
  granularityOptions: readonly { value: Granularity; label: string }[];
  onChangeGranularity: (granularity: Granularity) => void;
  fetching: boolean;
  testId: string;
  trailing?: React.ReactNode;
}>) {
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid={testId}>
      <Dropdown>
        <DropdownTrigger asChild>
          <Button
            variant="secondary"
            size="sm"
            aria-label="Select date range"
            className={cn(range !== defaultRange && ACTIVE_CLASS)}
          >
            <span className="text-muted">Range:</span>
            <span className="font-medium">{rangeLabel}</span>
            <ChevronDown className="text-muted size-3" aria-hidden />
          </Button>
        </DropdownTrigger>
        <DropdownContent>
          <DropdownLabel>Date range</DropdownLabel>
          <DropdownRadioGroup value={range}>
            {rangeOptions.map((option) => (
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
        options={granularityOptions}
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
      {trailing}
    </div>
  );
}
