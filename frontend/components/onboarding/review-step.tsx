'use client';

import { useState } from 'react';
import { Globe, MessageSquare, Plus, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { ReviewCompetitor, ReviewDomain, ReviewPrompt } from '@/lib/onboarding/forms';

/**
 * Review step — everything discovery produced, organized into clean tabs
 * with internal scrolling to ensure action controls stay visible without page scroll.
 */

function SectionHead({
  label,
  count,
  muted = false,
}: Readonly<{ label: string; count: string; muted?: boolean }>) {
  return (
    <div className="flex items-baseline gap-2">
      <p className={cn('text-2xs font-bold uppercase', muted ? 'text-muted' : 'text-secondary')}>
        {label}
      </p>
      <Badge variant="neutral">{count}</Badge>
    </div>
  );
}

type TabValue = 'entities' | 'prompts';

/**
 * One tab in the review switcher.
 *
 * Ids are stable and derived from the tab value so each button can point at
 * its panel (`aria-controls`) and each panel back at its button
 * (`aria-labelledby`) — the WAI-ARIA Tabs pattern needs both halves.
 */
const tabId = (value: TabValue) => `review-tab-${value}`;
const tabPanelId = (value: TabValue) => `review-tabpanel-${value}`;

function TabButton({
  value,
  icon: Icon,
  label,
  count,
  active,
  onSelect,
  onKeyDown,
}: Readonly<{
  value: TabValue;
  icon: typeof Globe;
  label: string;
  count: number;
  active: boolean;
  onSelect: () => void;
  onKeyDown: (event: React.KeyboardEvent<HTMLButtonElement>) => void;
}>) {
  return (
    <button
      type="button"
      role="tab"
      id={tabId(value)}
      aria-selected={active}
      aria-controls={tabPanelId(value)}
      // Roving tabindex: only the active tab is in the tab order; the arrow
      // keys move between tabs, per the ARIA authoring practice.
      tabIndex={active ? 0 : -1}
      onClick={onSelect}
      onKeyDown={onKeyDown}
      className={cn(
        'flex flex-1 cursor-pointer items-center justify-center gap-2 rounded-lg px-3 py-2 text-xs font-medium transition-all duration-200 sm:text-sm',
        active
          ? 'text-foreground bg-panel font-semibold'
          : 'text-muted hover:text-foreground hover:bg-panel/50',
      )}
    >
      <div className="flex items-center gap-1.5">
        <Icon className="text-accent-text size-4" />
        <span>{label}</span>
      </div>
      <span
        className={cn(
          'text-2xs rounded-full px-2 py-0.5 font-semibold transition-colors',
          active ? 'bg-accent-soft text-accent-text' : 'bg-border-subtle/60 text-muted',
        )}
      >
        {count}
      </span>
    </button>
  );
}

function Chip({
  label,
  selected,
  onToggle,
}: Readonly<{ label: string; selected: boolean; onToggle: () => void }>) {
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-pressed={selected}
      className={cn(
        'inline-flex max-w-full cursor-pointer items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium transition-all duration-200',
        selected
          ? 'border-accent-border/60 bg-accent-soft/80 text-accent-hover hover:bg-accent-subtle/80'
          : 'border-border-subtle text-muted hover:bg-background hover:text-secondary hover:border-border-bold/30 bg-panel',
      )}
    >
      <span className="truncate">{label}</span>
      <X
        className={cn(
          'size-4 shrink-0 transition-opacity',
          selected ? 'opacity-70 hover:opacity-100' : 'opacity-40',
        )}
        aria-hidden
      />
    </button>
  );
}

export function ReviewStep({
  domains,
  competitors,
  prompts,
  onToggleDomain,
  onToggleCompetitor,
  onTogglePrompt,
  onEditPrompt,
  onRenameCompetitor,
  onAddCompetitor,
  maximumCompetitors,
}: Readonly<{
  domains: ReviewDomain[];
  competitors: ReviewCompetitor[];
  prompts: ReviewPrompt[];
  onToggleDomain: (index: number) => void;
  onToggleCompetitor: (index: number) => void;
  onTogglePrompt: (index: number) => void;
  onEditPrompt: (index: number, text: string) => void;
  onRenameCompetitor: (index: number, name: string) => void;
  onAddCompetitor: () => void;
  maximumCompetitors: number | undefined;
}>) {
  const [activeTab, setActiveTab] = useState<TabValue>('entities');

  const selectedDomains = domains.filter((d) => d.selected).length;
  const selectedCompetitors = competitors.filter((c) => c.selected).length;
  const selectedPrompts = prompts.filter((p) => p.selected).length;
  const competitorLimitReached =
    maximumCompetitors === undefined || selectedCompetitors >= maximumCompetitors;

  /**
   * Arrow-key navigation between the two tabs (WAI-ARIA Tabs pattern).
   *
   * Both arrows toggle because there are exactly two tabs, so Left and Right
   * from either one lands on the other — that is what wrapping degenerates to
   * at length 2. Focus follows selection, matching the automatic-activation
   * variant of the pattern.
   */
  const handleTabKeyDown = (event: React.KeyboardEvent<HTMLButtonElement>) => {
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return;
    event.preventDefault();
    const next: TabValue = activeTab === 'entities' ? 'prompts' : 'entities';
    setActiveTab(next);
    document.getElementById(tabId(next))?.focus();
  };

  return (
    <div className="flex flex-col gap-4">
      {/* Tab Switcher */}
      <div className="border-border-subtle/80 bg-well/70 flex rounded-xl border p-1" role="tablist">
        <TabButton
          value="entities"
          icon={Globe}
          label="Domains & Competitors"
          count={selectedDomains + selectedCompetitors}
          active={activeTab === 'entities'}
          onSelect={() => setActiveTab('entities')}
          onKeyDown={handleTabKeyDown}
        />
        <TabButton
          value="prompts"
          icon={MessageSquare}
          label="Starting Prompts"
          count={selectedPrompts}
          active={activeTab === 'prompts'}
          onSelect={() => setActiveTab('prompts')}
          onKeyDown={handleTabKeyDown}
        />
      </div>

      {/* Tab 1: Domains & Competitors */}
      {/*
        Both panels stay MOUNTED and the inactive one is hidden. Unmounting it
        would leave the inactive tab's `aria-controls` pointing at an id that is
        not in the document, which breaks the ARIA Tabs relationship for AT, and
        would also discard the panel's DOM state (scroll position, an in-progress
        competitor rename) every time the user switches tabs.
      */}
      <div
        role="tabpanel"
        hidden={activeTab !== 'entities'}
        id={tabPanelId('entities')}
        aria-labelledby={tabId('entities')}
        className="bg-panel/60 shadow-card rounded-xl p-4"
      >
        <div className="max-h-90 overflow-y-auto pr-1 sm:max-h-100">
          <div className="grid gap-5 md:grid-cols-[minmax(0,2fr)_minmax(0,3fr)]">
            {/* Column 1: Domains */}
            {/* Card: the raised rung separates it from the panel, not an outline (docs/design.md §4a). */}
            <div className="bg-panel shadow-card rounded-lg p-4">
              <div className="mb-3">
                <SectionHead label="Your domains" count={`${selectedDomains} selected`} />
              </div>
              {domains.length === 0 ? (
                <p className="text-muted text-sm italic">None found — you can add these later.</p>
              ) : (
                <div className="flex flex-wrap content-start gap-2">
                  {domains.map((entry, index) => (
                    <Chip
                      key={entry.domain}
                      label={entry.domain}
                      selected={entry.selected}
                      onToggle={() => onToggleDomain(index)}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* Column 2: Competitors */}
            {/* Card: the raised rung separates it from the panel, not an outline (docs/design.md §4a). */}
            <div className="bg-panel shadow-card rounded-lg p-4">
              <div className="mb-3 flex items-center justify-between">
                <SectionHead
                  label="Competitors"
                  count={`${selectedCompetitors} of ${maximumCompetitors ?? '…'}`}
                />
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={onAddCompetitor}
                  disabled={competitorLimitReached}
                  title={
                    maximumCompetitors !== undefined && competitorLimitReached
                      ? `You can track up to ${maximumCompetitors} competitors`
                      : undefined
                  }
                  className="text-accent-text hover:bg-accent-soft gap-1 px-2 text-xs font-semibold"
                >
                  <Plus className="size-4" aria-hidden />
                  Add competitor
                </Button>
              </div>

              {competitors.length === 0 ? (
                <p className="text-muted text-sm italic">None found — add any you want to track.</p>
              ) : (
                <ul className="grid list-none content-start gap-2">
                  {competitors.map((competitor, index) => (
                    <li key={competitor.id} className="grid gap-1.5">
                      <div className="flex items-center gap-2">
                        <Input
                          value={competitor.name}
                          onChange={(event) => onRenameCompetitor(index, event.target.value)}
                          aria-label={`Competitor ${index + 1} name`}
                          placeholder="Competitor name"
                          className={cn(
                            'border-border-subtle bg-background/60 text-foreground focus:border-accent focus:ring-accent/20 focus:bg-panel text-sm transition-all focus:ring-1',
                            !competitor.selected && 'bg-well/40 line-through opacity-50',
                          )}
                        />
                        <Button
                          variant="ghost"
                          size="icon"
                          aria-label={
                            competitor.selected
                              ? `Exclude ${competitor.name || 'competitor'}`
                              : `Include ${competitor.name || 'competitor'}`
                          }
                          aria-pressed={competitor.selected}
                          onClick={() => onToggleCompetitor(index)}
                          className={cn(
                            'shrink-0 transition-colors',
                            competitor.selected
                              ? 'text-muted hover:text-secondary'
                              : 'bg-accent-soft text-accent-text hover:bg-accent-subtle',
                          )}
                        >
                          <X
                            className={cn('size-4', !competitor.selected && 'opacity-40')}
                            aria-hidden
                          />
                        </Button>
                      </div>
                      {competitor.reasoning ? (
                        <p className="text-2xs text-muted px-1 leading-relaxed">
                          {competitor.reasoning}
                          {competitor.evidence_urls?.length ? ' · Supporting links available' : ''}
                        </p>
                      ) : null}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Tab 2: Starting Prompts */}
      <div
        role="tabpanel"
        hidden={activeTab !== 'prompts'}
        id={tabPanelId('prompts')}
        aria-labelledby={tabId('prompts')}
        className="bg-panel/60 shadow-card rounded-xl p-4"
      >
        <div className="mb-3 flex items-center justify-between px-1">
          <SectionHead label="Starting prompts" count={`${selectedPrompts} selected`} />
          <span className="text-2xs text-muted font-medium">Use the checkbox to select</span>
        </div>

        <div className="max-h-90 overflow-y-auto pr-1 sm:max-h-100">
          {prompts.length === 0 ? (
            <p className="bg-panel shadow-card text-muted rounded-xl px-4 py-4 text-sm italic">
              None found — you can write your own after setup.
            </p>
          ) : (
            <ul className="flex list-none flex-col gap-2">
              {prompts.map((prompt, index) => (
                <li key={prompt.id}>
                  <div
                    className={cn(
                      'flex items-center justify-between gap-3 rounded-xl border p-3 transition-all duration-200',
                      prompt.selected
                        ? 'border-accent-border/60 bg-accent-soft/30 hover:bg-accent-soft/50'
                        : 'border-border-subtle bg-panel hover:bg-background/80 hover:border-border-bold/20',
                    )}
                  >
                    <div className="flex min-w-0 flex-1 items-start gap-3">
                      <input
                        type="checkbox"
                        checked={prompt.selected}
                        onChange={() => onTogglePrompt(index)}
                        aria-label={prompt.text}
                        className="border-border text-accent-text focus:ring-accent/20 accent-accent mt-0.5 size-4 shrink-0 cursor-pointer rounded-md"
                      />
                      <Input
                        value={prompt.text}
                        onChange={(event) => onEditPrompt(index, event.target.value)}
                        aria-label={`Prompt ${index + 1}`}
                        className={cn(
                          'min-w-0 flex-1 border-0 bg-transparent px-0 text-sm shadow-none focus:ring-0',
                          !prompt.selected && 'text-muted line-through',
                        )}
                      />
                    </div>
                    <div className="flex shrink-0 items-center gap-1.5">
                      <Badge variant="neutral">
                        {prompt.cohort === 'market_visibility' ? 'Market' : 'Brand diagnostic'}
                      </Badge>
                      {prompt.theme ? <Badge variant="neutral">{prompt.theme}</Badge> : null}
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
