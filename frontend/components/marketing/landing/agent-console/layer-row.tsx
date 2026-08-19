import { cn } from '@/lib/utils';

import { LANDING_ICONS } from '../landing-icons';

import type { SCRIPT } from './data';

/**
 * A layer, as a row rather than a card: an icon, a name, what it emits. The
 * active row is carried by an accent wash and its filled mark, never a border.
 */
export function LayerRow({
  step,
  index,
  active,
  reduce,
  onSelect,
}: Readonly<{
  step: (typeof SCRIPT)[number];
  index: number;
  active: boolean;
  reduce: boolean;
  onSelect: (index: number) => void;
}>) {
  const Icon = LANDING_ICONS[step.icon];

  return (
    <button
      type="button"
      onClick={() => onSelect(index)}
      aria-pressed={active}
      /* Each row is a real card, so the copy sits ON a surface rather than
         floating on the section background. Resting state is the sunken grey
         well; the selected row lifts to a white panel with the accent border —
         the tonal jump is what makes "which layer is streaming" readable at a
         glance, rather than relying on the status text alone. */
      className={cn(
        'focus-visible:ring-accent/60 group flex w-full items-start gap-3.5 rounded-sm border px-4 py-5 text-left transition-[background-color,border-color,box-shadow] duration-300 focus-visible:ring-2 focus-visible:outline-none xl:my-auto',
        active
          ? 'bg-panel border-accent-border shadow-card'
          : 'bg-well border-border-subtle hover:bg-panel hover:border-border hover:shadow-xs',
      )}
    >
      <span
        className={cn(
          'flex size-9 shrink-0 items-center justify-center rounded-sm transition-colors duration-300',
          active
            ? 'bg-accent text-inverse shadow-xs'
            : // On the grey resting card the chip needs a white fill to read as
              // a chip at all; `bg-background-alt` would blend into the card.
              'bg-panel border-border-subtle text-subtle group-hover:text-accent-text border',
        )}
      >
        <Icon className="size-4.5" strokeWidth={1.75} aria-hidden />
      </span>

      <span className="min-w-0 flex-1">
        <span
          className={cn(
            'font-display block text-sm font-semibold transition-colors duration-300',
            active ? 'text-accent-text' : 'text-foreground',
          )}
        >
          {step.name}
        </span>
        <span className="text-muted mt-1 block text-xs leading-relaxed">{step.role}</span>
        <span
          className={cn(
            'text-2xs mt-2 inline-flex items-center gap-1.5 font-semibold transition-opacity duration-300',
            active ? 'text-accent-text opacity-100' : 'text-subtle opacity-0 xl:opacity-100',
          )}
        >
          <span
            className={cn(
              'size-1.5 rounded-full',
              active ? 'bg-accent' : 'bg-border-strong',
              active && !reduce && 'animate-pulse',
            )}
            aria-hidden
          />
          {active ? 'Streaming to agent' : 'Idle'}
        </span>
      </span>
    </button>
  );
}
