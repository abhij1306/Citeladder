'use client';

/**
 * Selection primitives for onboarding review.
 *
 * Onboarding is a confirmation step, not an authoring step. People will click
 * to accept or reject something we already worked out; they will not compose
 * prose about their own company in a textarea. Every control here is therefore
 * a choice, and free text appears only as a deliberate escape hatch.
 *
 * The review screen used to speak three visual dialects at once — bare chip
 * fieldsets, then bordered cards with uppercase micro-labels and count badges,
 * then blue link-coloured chips that were secretly buttons. Nothing said which
 * controls belonged together or which answer mattered most. One section
 * primitive and one chip shape are what make it read as a single form.
 */

import { Check, Pencil, Plus } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { FilterChip } from '@/components/ui/filter-chip';
import { cn } from '@/lib/utils';

/**
 * One question in the review form.
 *
 * `meta` carries a count or hint; `action` an affordance such as "Add".
 * Both sit on the title's baseline rather than inside the answer area, so the
 * eye can run down the titles and find a question without reading chips.
 */
export function ReviewSection({
  title,
  meta,
  action,
  className,
  children,
}: Readonly<{
  title: string;
  meta?: React.ReactNode;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}>) {
  return (
    <section className={cn('space-y-1.5 py-2.5', className)}>
      <div className="flex min-h-5 items-center justify-between gap-2">
        <h2 className="text-foreground text-sm font-semibold">{title}</h2>
        <div className="flex shrink-0 items-center gap-2">
          {meta ? (
            <span className="text-muted text-xs font-medium tabular-nums">{meta}</span>
          ) : null}
          {action}
        </div>
      </div>
      {children}
    </section>
  );
}

/** The row a set of chips lives in, so every group wraps identically. */
export function ChipRow({ children }: Readonly<{ children: React.ReactNode }>) {
  return <div className="flex flex-wrap items-center gap-1.5">{children}</div>;
}

/**
 * Shared chip geometry.
 *
 * The icon slot is ALWAYS rendered, empty when unselected. Showing the check
 * only once selected changed the chip's width on click, so picking an option
 * reflowed the whole row and the neighbour you were about to compare against
 * moved out from under the cursor.
 */
function ChipMark({ selected, idle }: Readonly<{ selected: boolean; idle?: React.ReactNode }>) {
  return (
    <span aria-hidden className="flex size-3.5 shrink-0 items-center justify-center">
      {selected ? <Check className="text-accent-text size-3.5" strokeWidth={2.5} /> : idle}
    </span>
  );
}

/**
 * An include/exclude chip for a discovered suggestion.
 *
 * An excluded chip is rendered MUTED rather than dropped. Hiding it made every
 * exclusion permanent — and discovery legitimately returns more suggestions
 * than the cap pre-selects, so the extras were unreachable before the user ever
 * touched anything. A review step whose choices cannot be undone is not one.
 *
 * `onEdit` is an explicit pencil, not a click on the label. The label used to
 * open an inline domain field with a `title` tooltip as its only hint, while
 * looking exactly like a hyperlink — two undiscoverable affordances wearing one
 * borrowed appearance.
 */
export function ToggleChip({
  label,
  selected,
  onToggle,
  disabled = false,
  onEdit,
  editLabel,
}: Readonly<{
  label: string;
  selected: boolean;
  onToggle: () => void;
  /** True when selecting this would exceed the cap. Excluding stays available. */
  disabled?: boolean;
  onEdit?: () => void;
  editLabel?: string;
}>) {
  return (
    <span className="inline-flex max-w-full items-center gap-1">
      <FilterChip
        active={selected}
        onClick={onToggle}
        disabled={disabled && !selected}
        className="group min-w-0"
      >
        <ChipMark
          selected={selected}
          idle={<Plus className="size-3.5 opacity-40 group-hover:opacity-90" />}
        />
        {/* The visible label IS the accessible name, and `aria-pressed` carries
            the state. An `aria-label` of "Include Peer 6" moved the state into
            the name, so the same control announced a different name depending
            on whether it was on — and a voice-control user could not say the
            word they could see. */}
        <span className="truncate">{label}</span>
      </FilterChip>
      {onEdit ? (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          onClick={onEdit}
          aria-label={editLabel ?? `Edit ${label}`}
          className="size-6 shrink-0"
        >
          <Pencil className="size-3" aria-hidden />
        </Button>
      ) : null}
    </span>
  );
}
