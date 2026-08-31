'use client';

import { useState } from 'react';
import { Plus } from 'lucide-react';

import { ChipRow, ReviewSection, ToggleChip } from '@/components/onboarding/choice-controls';
import { BrandLogo } from '@/components/ui/brand-logo';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import type { ReviewCompetitor, ReviewDomain } from '@/lib/onboarding/forms';

function competitorUrl(competitor: ReviewCompetitor): string {
  const domain = competitor.domains.find(Boolean);
  if (!domain) return '';
  return /^https?:\/\//i.test(domain) ? domain : `https://${domain}`;
}

function CompetitorChip({
  competitor,
  disabled,
  onToggle,
  onEditDomain,
}: Readonly<{
  competitor: ReviewCompetitor;
  disabled: boolean;
  onToggle: () => void;
  onEditDomain: (domain: string) => void;
}>) {
  const primaryDomain = competitor.domains.find(Boolean) || '';
  const displayName = competitor.name || primaryDomain || 'New competitor';

  // A manually added competitor arrives empty, so it opens straight into the
  // field it exists to collect.
  const [isEditing, setIsEditing] = useState(
    competitor.name === '' && competitor.domains.length === 0,
  );
  const [draft, setDraft] = useState(primaryDomain);

  // The field is labelled, seeded, and placeheld as a DOMAIN, so it writes the
  // domain. It used to write `name` instead, which left `domains` holding the
  // value the user had just replaced — the submitted payload carried both, and
  // the chip's link still pointed at the old host.
  const save = () => {
    setIsEditing(false);
    const trimmed = draft.trim();
    if (trimmed) onEditDomain(trimmed);
  };

  if (isEditing) {
    return (
      <span className="flex items-center gap-1.5">
        <Input
          // oxlint-disable-next-line jsx-a11y/no-autofocus -- Edit is an explicit action and focus must enter the newly mounted inline editor.
          autoFocus
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onBlur={save}
          onKeyDown={(event) => {
            if (event.key === 'Enter') save();
            if (event.key === 'Escape') {
              setDraft(primaryDomain);
              setIsEditing(false);
            }
          }}
          placeholder="acme.com"
          aria-label={`Website for ${displayName}`}
          className="w-44 shadow-2xs"
        />
      </span>
    );
  }

  const url = competitorUrl(competitor);
  return (
    <span className="inline-flex w-full min-w-0 items-center">
      <ToggleChip
        label={displayName}
        selected={competitor.selected}
        disabled={disabled}
        onToggle={onToggle}
        leading={
          <BrandLogo name={displayName} websiteUrl={primaryDomain} size="sm" className="-my-1" />
        }
        onEdit={() => {
          setDraft(primaryDomain);
          setIsEditing(true);
        }}
        editLabel={`Edit website for ${displayName}`}
      />
      {/* Kept for assistive tech and tests: the visible chip is a control, so
          it cannot also be the link to the competitor's site. */}
      {url ? (
        <a href={url} target="_blank" rel="noreferrer" className="sr-only">
          {url}
        </a>
      ) : null}
    </span>
  );
}

export function ReviewStep({
  domains,
  competitors,
  onToggleDomain,
  onToggleCompetitor,
  onEditCompetitorDomain,
  onAddCompetitor,
  maximumCompetitors,
}: Readonly<{
  domains: ReviewDomain[];
  competitors: ReviewCompetitor[];
  onToggleDomain: (index: number) => void;
  onToggleCompetitor: (index: number) => void;
  onEditCompetitorDomain: (index: number, domain: string) => void;
  onAddCompetitor: () => void;
  maximumCompetitors: number | undefined;
}>) {
  const selectedDomains = domains.filter((item) => item.selected).length;
  const selectedCompetitors = competitors.filter((item) => item.selected).length;
  const competitorLimitReached =
    maximumCompetitors === undefined || selectedCompetitors >= maximumCompetitors;

  return (
    <div className="grid md:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
      <ReviewSection
        title="Your websites"
        meta={domains.length > 0 ? `${selectedDomains} of ${domains.length}` : undefined}
        className="pt-0 md:pr-4"
      >
        {domains.length === 0 ? (
          <p className="text-muted text-sm font-medium">No websites were found.</p>
        ) : (
          <ChipRow>
            {domains.map((entry, index) => (
              <ToggleChip
                key={entry.domain}
                label={entry.domain}
                selected={entry.selected}
                onToggle={() => onToggleDomain(index)}
              />
            ))}
          </ChipRow>
        )}
      </ReviewSection>

      <ReviewSection
        title="Competitors"
        meta={`${selectedCompetitors} of ${maximumCompetitors ?? '…'} tracked`}
        className="border-border-subtle border-t pb-0 md:border-t-0 md:border-l md:pt-0 md:pl-4"
        action={
          <Button
            variant="tonal"
            size="sm"
            onClick={onAddCompetitor}
            disabled={competitorLimitReached}
          >
            <Plus className="size-3.5" aria-hidden />
            Add
          </Button>
        }
      >
        {competitors.length === 0 ? (
          <p className="text-muted text-sm font-medium">
            No competitors were confirmed. Add the companies you lose deals to.
          </p>
        ) : (
          <ChipRow className="grid grid-cols-2 items-start sm:grid-cols-3">
            {competitors.map((competitor, index) => (
              <CompetitorChip
                key={competitor.id}
                competitor={competitor}
                disabled={competitorLimitReached}
                onToggle={() => onToggleCompetitor(index)}
                onEditDomain={(domain) => onEditCompetitorDomain(index, domain)}
              />
            ))}
          </ChipRow>
        )}
      </ReviewSection>
    </div>
  );
}
