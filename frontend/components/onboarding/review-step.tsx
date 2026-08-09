'use client';

import { useState } from 'react';
import { Plus, X } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { cn } from '@/lib/utils';
import type { ReviewCompetitor, ReviewDomain, ReviewPrompt } from '@/lib/onboarding/forms';

function competitorUrl(competitor: ReviewCompetitor): string {
  const domain = competitor.domains.find(Boolean);
  if (!domain) return '';
  return /^https?:\/\//i.test(domain) ? domain : `https://${domain}`;
}

/**
 * A reviewable suggestion, in both states.
 *
 * An unselected chip is rendered MUTED rather than dropped. Hiding it made
 * every exclusion permanent — and discovery legitimately returns more
 * suggestions than the cap pre-selects, so the extras were unreachable before
 * the user ever touched anything. A review step whose choices cannot be undone
 * is not a review step.
 */
function DomainChip({
  label,
  selected,
  onToggle,
}: Readonly<{ label: string; selected: boolean; onToggle: () => void }>) {
  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-all',
        selected
          ? 'border-accent-border/60 bg-accent-soft/80 text-accent-hover'
          : 'border-border-subtle text-muted border-dashed',
      )}
    >
      <span className="truncate">{label}</span>
      <button
        type="button"
        onClick={onToggle}
        aria-label={`${selected ? 'Exclude' : 'Include'} ${label}`}
        aria-pressed={selected}
        className="text-muted hover:text-foreground shrink-0 cursor-pointer p-0.5 transition-colors"
      >
        {selected ? (
          <X className="size-3.5" aria-hidden />
        ) : (
          <Plus className="size-3.5" aria-hidden />
        )}
      </button>
    </div>
  );
}

function CompetitorChip({
  competitor,
  onToggle,
  onEditDomain,
}: Readonly<{
  competitor: ReviewCompetitor;
  onToggle: () => void;
  onEditDomain: (domain: string) => void;
}>) {
  const primaryDomain = competitor.domains.find(Boolean) || competitor.name;
  const displayName = competitor.name || primaryDomain || 'Competitor';

  const [isEditing, setIsEditing] = useState(
    competitor.name === '' && competitor.domains.length === 0,
  );
  const [editDomain, setEditDomain] = useState(primaryDomain);

  // The field is labelled, seeded, and placeheld as a DOMAIN, so it writes the
  // domain. It used to write `name` instead, which left `domains` holding the
  // value the user had just replaced — the submitted payload carried both, and
  // the chip's link still pointed at the old host.
  const handleSave = () => {
    setIsEditing(false);
    const trimmed = editDomain.trim();
    if (trimmed) {
      onEditDomain(trimmed);
    }
  };

  const url = competitorUrl(competitor);
  const selected = competitor.selected;

  return (
    <div
      className={cn(
        'flex items-center justify-between gap-1.5 rounded-lg border px-3 py-1.5 text-sm font-medium transition-all',
        selected
          ? 'border-accent-border/60 bg-accent-soft/80 text-accent-hover'
          : 'border-border-subtle text-muted border-dashed',
      )}
    >
      {isEditing ? (
        <input
          autoFocus
          type="text"
          value={editDomain}
          onChange={(e) => setEditDomain(e.target.value)}
          onBlur={handleSave}
          onKeyDown={(e) => {
            if (e.key === 'Enter') handleSave();
            if (e.key === 'Escape') {
              setEditDomain(primaryDomain);
              setIsEditing(false);
            }
          }}
          placeholder="e.g. acme.com"
          aria-label={`Edit domain for ${displayName}`}
          className="text-accent-hover placeholder:text-accent-hover/50 min-w-0 flex-1 border-0 bg-transparent p-0 text-sm font-medium focus:ring-0 focus:outline-none"
        />
      ) : (
        <button
          type="button"
          onClick={() => {
            setEditDomain(primaryDomain);
            setIsEditing(true);
          }}
          title="Click chip to edit domain"
          className="text-accent-hover min-w-0 flex-1 cursor-pointer truncate text-left text-sm font-medium"
        >
          {displayName}
        </button>
      )}

      {url ? (
        <a href={url} target="_blank" rel="noreferrer" className="sr-only">
          {url}
        </a>
      ) : null}

      <button
        type="button"
        onClick={onToggle}
        aria-label={`${selected ? 'Exclude' : 'Include'} ${displayName}`}
        aria-pressed={selected}
        className="text-muted hover:text-foreground shrink-0 cursor-pointer p-0.5 transition-colors"
      >
        {selected ? (
          <X className="size-3.5" aria-hidden />
        ) : (
          <Plus className="size-3.5" aria-hidden />
        )}
      </button>
    </div>
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
  onEditCompetitorDomain,
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
  onEditCompetitorDomain: (index: number, domain: string) => void;
  onAddCompetitor: () => void;
  maximumCompetitors: number | undefined;
}>) {
  const selectedDomains = domains.filter((d) => d.selected);
  const selectedCompetitors = competitors.filter((c) => c.selected);
  const selectedPrompts = prompts.filter((p) => p.selected).length;
  const competitorLimitReached =
    maximumCompetitors === undefined || selectedCompetitors.length >= maximumCompetitors;

  return (
    <div className="grid w-full items-start gap-5 lg:grid-cols-12">
      {/* Left Column (5 cols): Domains & Competitors */}
      <div className="space-y-4 lg:col-span-5">
        {/* Card 1: Your Domains */}
        <div className="bg-panel border-border-subtle/80 space-y-2.5 rounded-xl border p-4 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-muted text-xs font-semibold tracking-wider uppercase">
              Your Domains
            </span>
            <Badge variant="neutral" className="px-2 py-0.5 text-xs">
              {selectedDomains.length} selected
            </Badge>
          </div>
          {domains.length === 0 ? (
            <p className="website-body text-muted italic">No domains were discovered.</p>
          ) : (
            <div className="flex flex-wrap gap-2 pt-0.5">
              {domains.map((entry, index) => (
                <DomainChip
                  key={entry.domain}
                  label={entry.domain}
                  selected={entry.selected}
                  onToggle={() => onToggleDomain(index)}
                />
              ))}
            </div>
          )}
        </div>

        {/* Card 2: Competitors — Sleek Single-Line Chips */}
        <div className="bg-panel border-border-subtle/80 space-y-3 rounded-xl border p-4 shadow-xs">
          <div className="flex items-center justify-between">
            <span className="text-muted text-xs font-semibold tracking-wider uppercase">
              Competitors
            </span>
            <div className="flex items-center gap-2">
              <Badge variant="neutral" className="px-2 py-0.5 text-xs">
                {selectedCompetitors.length} of {maximumCompetitors ?? '…'}
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                onClick={onAddCompetitor}
                disabled={competitorLimitReached}
                className="text-accent-text hover:bg-accent-soft border-accent-border/60 h-6 gap-1 rounded-lg border border-dashed px-2.5 text-xs font-medium"
              >
                <Plus className="size-3.5" aria-hidden />
                Add competitor
              </Button>
            </div>
          </div>

          {/* 2-Column Grid for Competitor Chips */}
          {competitors.length === 0 ? (
            <p className="website-body text-muted italic">No competitors were discovered.</p>
          ) : (
            <div className="grid grid-cols-2 gap-2">
              {competitors.map((competitor, index) => (
                <CompetitorChip
                  key={competitor.id}
                  competitor={competitor}
                  onToggle={() => onToggleCompetitor(index)}
                  onEditDomain={(domain) => onEditCompetitorDomain(index, domain)}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Right Column (7 cols): Starting Prompts Portfolio */}
      <div className="bg-panel border-border-subtle/80 space-y-3 rounded-xl border p-4 shadow-xs lg:col-span-7">
        <div className="flex items-center justify-between">
          <span className="text-muted text-xs font-semibold tracking-wider uppercase">
            Starting Prompts ({selectedPrompts} selected)
          </span>
          <span className="text-muted text-xs font-normal">Check to select / edit text</span>
        </div>

        <div className="max-h-80 overflow-y-auto pr-1">
          {prompts.length === 0 ? (
            <p className="website-body text-muted py-2 italic">
              None found — you can write your own after setup.
            </p>
          ) : (
            <ul className="m-0 flex list-none flex-col gap-2 p-0">
              {prompts.map((prompt, index) => (
                <li key={prompt.id}>
                  <div
                    className={cn(
                      'flex items-center justify-between gap-3 rounded-lg border px-3 py-2 transition-all',
                      prompt.selected
                        ? 'border-accent-border/50 bg-accent-soft/20'
                        : 'border-border-subtle bg-well/20 opacity-60',
                    )}
                  >
                    <div className="flex min-w-0 flex-1 items-center gap-2.5">
                      <input
                        type="checkbox"
                        checked={prompt.selected}
                        onChange={() => onTogglePrompt(index)}
                        aria-label={prompt.text}
                        className="border-border text-accent-text accent-accent size-4 shrink-0 cursor-pointer rounded"
                      />
                      <Input
                        value={prompt.text}
                        onChange={(event) => onEditPrompt(index, event.target.value)}
                        aria-label={`Prompt ${index + 1}`}
                        className={cn(
                          'h-7 min-w-0 flex-1 border-0 bg-transparent px-0 text-sm shadow-none focus:ring-0',
                          !prompt.selected && 'text-muted line-through',
                        )}
                      />
                    </div>
                    <div className="flex shrink-0 items-center gap-1">
                      <Badge variant="neutral" className="px-2 py-0.5 text-xs font-normal">
                        {prompt.cohort === 'market_visibility' ? 'Industry' : 'Brand'}
                      </Badge>
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
