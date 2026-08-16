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
  emphasis = false,
  children,
}: Readonly<{
  title: string;
  meta?: React.ReactNode;
  action?: React.ReactNode;
  /** The answer everything downstream is derived from. */
  emphasis?: boolean;
  children: React.ReactNode;
}>) {
  return (
    <section className="space-y-1.5 py-2.5 first:pt-0 last:pb-0">
      <div className="flex min-h-5 items-center justify-between gap-3">
        {/* `website-label` — 14px, the screen's baseline, and the named role
            rather than a raw size. Section titles are structure, not display
            type: a heading two steps up the scale made a four-question form
            read like four separate pages. Colour and weight are stated here
            because the role defaults to muted. */}
        <h2
          className={cn(
            'website-label',
            emphasis ? 'text-foreground font-semibold' : 'text-secondary font-medium',
          )}
        >
          {title}
        </h2>
        <div className="flex shrink-0 items-center gap-2">
          {meta ? <span className="text-subtle text-xs tabular-nums">{meta}</span> : null}
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
const chipBase =
  'group inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-sm leading-5 transition-colors';
const chipSelected = 'border-accent bg-accent-subtle text-foreground font-medium';
const chipIdle =
  'border-border-strong/70 text-muted hover:border-border-bold hover:text-foreground';

function ChipMark({ selected, idle }: Readonly<{ selected: boolean; idle?: React.ReactNode }>) {
  return (
    <span aria-hidden className="flex size-3.5 shrink-0 items-center justify-center">
      {selected ? <Check className="text-accent-text size-3.5" strokeWidth={2.5} /> : idle}
    </span>
  );
}

/** One mutually exclusive option, rendered as a radio the whole chip toggles. */
export function ChoiceChip({
  label,
  selected,
  onSelect,
  name,
}: Readonly<{ label: string; selected: boolean; onSelect: () => void; name: string }>) {
  return (
    <label
      className={cn(
        chipBase,
        'focus-within:ring-accent cursor-pointer focus-within:ring-2 focus-within:ring-offset-1',
        selected ? chipSelected : chipIdle,
      )}
    >
      <input type="radio" name={name} className="sr-only" checked={selected} onChange={onSelect} />
      <ChipMark selected={selected} />
      {label}
    </label>
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
    <span
      className={cn(
        chipBase,
        'max-w-full pr-1.5',
        selected ? chipSelected : chipIdle,
        disabled && !selected && 'opacity-60',
      )}
    >
      <button
        type="button"
        onClick={onToggle}
        disabled={disabled && !selected}
        aria-pressed={selected}
        className="flex min-w-0 cursor-pointer items-center gap-1.5 disabled:cursor-not-allowed"
      >
        <ChipMark
          selected={selected}
          idle={<Plus className="size-3.5 opacity-50 group-hover:opacity-100" />}
        />
        {/* The visible label IS the accessible name, and `aria-pressed` carries
            the state. An `aria-label` of "Include Peer 6" moved the state into
            the name, so the same control announced a different name depending
            on whether it was on — and a voice-control user could not say the
            word they could see. */}
        <span className="truncate">{label}</span>
      </button>
      {onEdit ? (
        <button
          type="button"
          onClick={onEdit}
          aria-label={editLabel ?? `Edit ${label}`}
          className="text-subtle hover:text-foreground hover:bg-active shrink-0 cursor-pointer rounded-full p-1 transition-colors"
        >
          <Pencil className="size-3" aria-hidden />
        </button>
      ) : null}
    </span>
  );
}
