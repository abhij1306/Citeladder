'use client';

import { CalendarRange, ChevronDown, CircleHelp, Download } from 'lucide-react';
import { forwardRef } from 'react';

import { LaunchAuditButton } from '@/components/runs/launch-audit-button';
import { Button } from '@/components/ui/button';
import {
  Dropdown,
  DropdownContent,
  DropdownLabel,
  DropdownRadioGroup,
  DropdownRadioItem,
  DropdownTrigger,
} from '@/components/ui/dropdown';
import { Tooltip } from '@/components/ui/tooltip';
import type { LogicalEngine } from '@/lib/api/types';
import { ICONS } from '@/lib/icons';
import {
  engineLabel,
  isEvidenceTab,
  type PromptOption,
  type RunOption,
  type VisibilityTab,
} from '@/lib/visibility/dashboard';
import {
  GRANULARITY_OPTIONS,
  RANGE_OPTIONS,
  TREND_ENGINES,
  granularityLabel,
  rangeLabel,
  type TrendGranularity,
  type TrendRange,
} from '@/lib/visibility/trends';

export type EngineFilter = LogicalEngine | 'all';
const METRICS_HELP_URL = '/faq';

type ToolbarProps = Readonly<{
  activeTab: VisibilityTab;
  runs: RunOption[];
  selectedRunId: string | null;
  onSelectRun: (runId: string | null) => void;
  engine: EngineFilter;
  onChangeEngine: (engine: EngineFilter) => void;
  promptOptions: PromptOption[];
  promptId: string | null;
  onChangePrompt: (promptId: string | null) => void;
  range: TrendRange;
  onChangeRange: (range: TrendRange) => void;
  granularity: TrendGranularity;
  onChangeGranularity: (granularity: TrendGranularity) => void;
  cohort: 'core' | 'comparison';
  onChangeCohort: (cohort: 'core' | 'comparison') => void;
}>;

export function VisibilityToolbar(props: ToolbarProps) {
  const evidence = isEvidenceTab(props.activeTab);
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="visibility-toolbar">
      <CohortFilter {...props} />
      {props.activeTab === 'trends' || evidence ? <RunFilter {...props} /> : null}
      <EngineFilterControl {...props} />
      {props.activeTab === 'trends' || evidence ? <RangeFilter {...props} /> : null}
      {props.activeTab === 'trends' ? <GranularityFilter {...props} /> : null}
      {evidence ? <PromptFilter {...props} /> : null}
      <ToolbarActions />
    </div>
  );
}

const FilterButton = forwardRef<
  HTMLButtonElement,
  Readonly<
    Omit<React.ComponentPropsWithoutRef<typeof Button>, 'aria-label' | 'children'> & {
      active: boolean;
      label: string;
      children: React.ReactNode;
    }
  >
>(function FilterButton({ active, label, children, className, ...buttonProps }, ref) {
  return (
    <Button
      ref={ref}
      variant={active ? 'tonal' : 'secondary'}
      size="sm"
      aria-label={label}
      className={className}
      {...buttonProps}
    >
      {children}
      <ChevronDown className="text-muted size-3" aria-hidden />
    </Button>
  );
});

function CohortFilter({ cohort, onChangeCohort }: ToolbarProps) {
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <FilterButton active={cohort !== 'core'} label="Filter by prompt cohort">
          <span className="font-medium">{cohort === 'core' ? 'Core' : 'Comparison'}</span>
        </FilterButton>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>Prompt cohort</DropdownLabel>
        <DropdownRadioGroup value={cohort}>
          <DropdownRadioItem value="core" onSelect={() => onChangeCohort('core')}>
            Core visibility
          </DropdownRadioItem>
          <DropdownRadioItem value="comparison" onSelect={() => onChangeCohort('comparison')}>
            Named comparisons
          </DropdownRadioItem>
        </DropdownRadioGroup>
      </DropdownContent>
    </Dropdown>
  );
}

function RunFilter({ runs, selectedRunId, onSelectRun }: ToolbarProps) {
  const selected = runs.find((run) => run.id === selectedRunId);
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <FilterButton active={false} label="Select run">
          <ICONS.runs className="text-muted size-3" aria-hidden strokeWidth={2} />
          <span className="font-medium">{selected?.label ?? 'Latest'}</span>
        </FilterButton>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>Runs</DropdownLabel>
        <DropdownRadioGroup value={selectedRunId ?? '__latest__'}>
          <DropdownRadioItem value="__latest__" onSelect={() => onSelectRun(null)}>
            Latest
          </DropdownRadioItem>
          {runs.map((run) => (
            <DropdownRadioItem key={run.id} value={run.id} onSelect={() => onSelectRun(run.id)}>
              {run.label}
            </DropdownRadioItem>
          ))}
        </DropdownRadioGroup>
      </DropdownContent>
    </Dropdown>
  );
}

function EngineFilterControl({ engine, onChangeEngine }: ToolbarProps) {
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <FilterButton active={engine !== 'all'} label="Filter by model">
          <ICONS.analytics className="size-3" aria-hidden strokeWidth={2} />
          <span className="font-medium">
            {engine === 'all' ? 'All models' : engineLabel(engine)}
          </span>
        </FilterButton>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>Model</DropdownLabel>
        <DropdownRadioGroup value={engine}>
          <DropdownRadioItem value="all" onSelect={() => onChangeEngine('all')}>
            All models
          </DropdownRadioItem>
          {TREND_ENGINES.map((engine) => (
            <DropdownRadioItem key={engine} value={engine} onSelect={() => onChangeEngine(engine)}>
              {engineLabel(engine)}
            </DropdownRadioItem>
          ))}
        </DropdownRadioGroup>
      </DropdownContent>
    </Dropdown>
  );
}

function RangeFilter({ range, onChangeRange }: ToolbarProps) {
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <FilterButton active={range !== '90d'} label="Select date range">
          <CalendarRange className="size-3" aria-hidden strokeWidth={2} />
          <span className="font-medium">{rangeLabel(range)}</span>
        </FilterButton>
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
  );
}

function GranularityFilter({ granularity, onChangeGranularity }: ToolbarProps) {
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <FilterButton active={granularity !== 'run'} label="Select granularity">
          <span className="font-medium">{granularityLabel(granularity)}</span>
        </FilterButton>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>Granularity</DropdownLabel>
        <DropdownRadioGroup value={granularity}>
          {GRANULARITY_OPTIONS.map((option) => (
            <DropdownRadioItem
              key={option.value}
              value={option.value}
              onSelect={() => onChangeGranularity(option.value)}
            >
              {option.label}
            </DropdownRadioItem>
          ))}
        </DropdownRadioGroup>
      </DropdownContent>
    </Dropdown>
  );
}

function PromptFilter({ promptOptions, promptId, onChangePrompt }: ToolbarProps) {
  const prompt = promptOptions.find((option) => option.id === promptId);
  return (
    <Dropdown>
      <DropdownTrigger asChild>
        <FilterButton active={promptId !== null} label="Filter by prompt">
          <ICONS.prompts className="size-3" aria-hidden strokeWidth={2} />
          <span className="max-w-[16ch] truncate font-medium">
            {prompt?.label ?? 'All prompts'}
          </span>
        </FilterButton>
      </DropdownTrigger>
      <DropdownContent>
        <DropdownLabel>Prompt</DropdownLabel>
        <DropdownRadioGroup value={promptId ?? '__all__'}>
          <DropdownRadioItem value="__all__" onSelect={() => onChangePrompt(null)}>
            All prompts
          </DropdownRadioItem>
          {promptOptions.map((option) => (
            <DropdownRadioItem
              key={option.id}
              value={option.id}
              onSelect={() => onChangePrompt(option.id)}
            >
              {option.label}
            </DropdownRadioItem>
          ))}
        </DropdownRadioGroup>
      </DropdownContent>
    </Dropdown>
  );
}

function ToolbarActions() {
  return (
    <div className="ms-auto flex items-center gap-2">
      <LaunchAuditButton size="sm" />
      <Tooltip content="How these metrics are calculated">
        <Button variant="secondary" size="icon" asChild>
          <a href={METRICS_HELP_URL} aria-label="About these metrics">
            <CircleHelp className="size-3" aria-hidden strokeWidth={2} />
          </a>
        </Button>
      </Tooltip>
      <Tooltip content="Export is available from a run (coming with reports)">
        <span>
          <Button variant="secondary" size="sm" disabled aria-disabled="true">
            <Download className="size-3" aria-hidden strokeWidth={2} />
            Export
          </Button>
        </span>
      </Tooltip>
    </div>
  );
}
