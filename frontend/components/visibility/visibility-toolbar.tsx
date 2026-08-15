'use client';

import { CalendarRange, ChevronDown, CircleHelp, Download } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { LaunchAuditButton } from '@/components/runs/launch-audit-button';
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
import { cn } from '@/lib/utils';
import {
  GRANULARITY_OPTIONS,
  RANGE_OPTIONS,
  TREND_ENGINES,
  granularityLabel,
  rangeLabel,
  type TrendGranularity,
  type TrendRange,
} from '@/lib/visibility/trends';

/** Engine filter value shared across every tab. */
export type EngineFilter = LogicalEngine | 'all';

/** Help destination for the metric-definitions button — the public FAQ carries
 *  the deterministic-scoring answers until a real docs surface exists. */
const METRICS_HELP_URL = '/faq';

// Flat filter-chip language: a 30px hairline pill showing the VALUE alone (no
// "Label:" prefix — the value reads as a sentence: "Last 30 days", "All
// models"). A non-default value flips the chip to the accent-soft active state
// (blue reserved for active states, never the default surface).
const CHIP_CLASS = 'h-[var(--control-height-sm)] rounded-full border-border bg-panel px-3 text-xs';
const CHIP_ACTIVE_CLASS =
  'border-accent-border bg-accent-soft text-accent-text hover:border-accent-border hover:bg-accent-soft hover:text-accent-text';

/**
 * Shared filter bar rendered ABOVE the tablist (design.md tabbed workspace).
 *
 * A single control row whose filter STATE lives in `visibility-dashboard.tsx`
 * and persists across tab switches. Only the controls relevant to the active
 * tab are shown; hidden controls keep their state and reappear unchanged. There
 * is no Single Run / Trend mode toggle — the tablist replaces it.
 *
 * Ownership (plan §IA):
 *   - Run:         Overview + both evidence tabs
 *   - Engine:      all four tabs
 *   - Prompt:      both evidence tabs (evidence filtering, NOT prompt taxonomy)
 *   - Range:       Trends + both evidence tabs
 *   - Granularity: Trends only
 * Right-aligned: a help link and an Export affordance (disabled until F10).
 */
export function VisibilityToolbar({
  activeTab,
  runs,
  selectedRunId,
  onSelectRun,
  engine,
  onChangeEngine,
  promptOptions,
  promptId,
  onChangePrompt,
  range,
  onChangeRange,
  granularity,
  onChangeGranularity,
  cohort,
  onChangeCohort,
}: Readonly<{
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
}>) {
  const evidence = isEvidenceTab(activeTab);
  const showRun = activeTab === 'trends' || evidence;
  const showPrompt = evidence;
  const showRange = activeTab === 'trends' || evidence;
  const showGranularity = activeTab === 'trends';

  const selectedRun = runs.find((run) => run.id === selectedRunId) ?? null;
  const engineText = engine === 'all' ? 'All models' : engineLabel(engine);
  const activePrompt = promptOptions.find((option) => option.id === promptId) ?? null;
  const promptText = promptId === null ? 'All prompts' : (activePrompt?.label ?? 'All prompts');

  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="visibility-toolbar">
      <Dropdown>
        <DropdownTrigger asChild>
          <Button
            variant="secondary"
            size="sm"
            aria-label="Filter by prompt cohort"
            className={cn(CHIP_CLASS, cohort !== 'core' && CHIP_ACTIVE_CLASS)}
          >
            <span className="font-medium">{cohort === 'core' ? 'Core' : 'Comparison'}</span>
            <ChevronDown className="text-muted size-3" aria-hidden />
          </Button>
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
      {showRun ? (
        <Dropdown>
          <DropdownTrigger asChild>
            <Button variant="secondary" size="sm" aria-label="Select run" className={CHIP_CLASS}>
              <ICONS.runs className="text-muted size-3" aria-hidden strokeWidth={2} />
              <span className="font-medium">{selectedRun?.label ?? 'Latest'}</span>
              <ChevronDown className="text-muted size-3" aria-hidden />
            </Button>
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
      ) : null}

      <Dropdown>
        <DropdownTrigger asChild>
          <Button
            variant="secondary"
            size="sm"
            aria-label="Filter by model"
            className={cn(CHIP_CLASS, engine !== 'all' && CHIP_ACTIVE_CLASS)}
          >
            <ICONS.analytics className="size-3" aria-hidden strokeWidth={2} />
            <span className="font-medium">{engineText}</span>
            <ChevronDown className="text-muted size-3" aria-hidden />
          </Button>
        </DropdownTrigger>
        <DropdownContent>
          <DropdownLabel>Model</DropdownLabel>
          <DropdownRadioGroup value={engine}>
            <DropdownRadioItem value="all" onSelect={() => onChangeEngine('all')}>
              All models
            </DropdownRadioItem>
            {TREND_ENGINES.map((option: LogicalEngine) => (
              <DropdownRadioItem
                key={option}
                value={option}
                onSelect={() => onChangeEngine(option)}
              >
                {engineLabel(option)}
              </DropdownRadioItem>
            ))}
          </DropdownRadioGroup>
        </DropdownContent>
      </Dropdown>

      {showRange ? (
        <Dropdown>
          <DropdownTrigger asChild>
            <Button
              variant="secondary"
              size="sm"
              aria-label="Select date range"
              className={cn(CHIP_CLASS, range !== '90d' && CHIP_ACTIVE_CLASS)}
            >
              <CalendarRange className="size-3" aria-hidden strokeWidth={2} />
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
      ) : null}

      {showGranularity ? (
        <Dropdown>
          <DropdownTrigger asChild>
            <Button
              variant="secondary"
              size="sm"
              aria-label="Select granularity"
              className={cn(CHIP_CLASS, granularity !== 'run' && CHIP_ACTIVE_CLASS)}
            >
              <span className="font-medium">{granularityLabel(granularity)}</span>
              <ChevronDown className="text-muted size-3" aria-hidden />
            </Button>
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
      ) : null}

      {showPrompt ? (
        <Dropdown>
          <DropdownTrigger asChild>
            <Button
              variant="secondary"
              size="sm"
              aria-label="Filter by prompt"
              className={cn(CHIP_CLASS, promptId !== null && CHIP_ACTIVE_CLASS)}
            >
              <ICONS.prompts className="size-3" aria-hidden strokeWidth={2} />
              <span className="max-w-[16ch] truncate font-medium">{promptText}</span>
              <ChevronDown className="text-muted size-3" aria-hidden />
            </Button>
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
      ) : null}

      {/* Right side of the filter row: help + export. Both are affordances the
          mock shows; export stays a disabled placeholder until report export
          lands (F10), rather than shipping a button that does nothing. */}
      <div className="ms-auto flex items-center gap-2">
        <LaunchAuditButton size="sm" />
        <Tooltip content="How these metrics are calculated">
          <Button variant="secondary" size="sm" className="size-8 rounded-full px-0" asChild>
            {/* The label belongs on the anchor, not on the `asChild` Button:
                Slot does forward it, but this is the element a screen reader
                actually announces, and the icon-only link has no text of its
                own. Static a11y checks read it here too. */}
            <a href={METRICS_HELP_URL} aria-label="About these metrics">
              <CircleHelp className="size-3" aria-hidden strokeWidth={2} />
            </a>
          </Button>
        </Tooltip>
        <Tooltip content="Export is available from a run (coming with reports)">
          <span>
            <Button
              variant="secondary"
              size="sm"
              className={CHIP_CLASS}
              disabled
              aria-disabled="true"
            >
              <Download className="size-3" aria-hidden strokeWidth={2} />
              Export
            </Button>
          </span>
        </Tooltip>
      </div>
    </div>
  );
}
