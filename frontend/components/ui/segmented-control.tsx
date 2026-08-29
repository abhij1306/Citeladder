'use client';

import { useRef } from 'react';

import { segmentedItemVariants, segmentedTrackVariants } from '@/components/ui/segmented-variants';
import { cn } from '@/lib/utils';

/** Arrow keys that move the roving focus, and the direction each moves it. */
const ARROW_DELTA: Readonly<Record<string, number>> = {
  ArrowRight: 1,
  ArrowDown: 1,
  ArrowLeft: -1,
  ArrowUp: -1,
};

/**
 * SegmentedControl (F6) — a single-select segmented toggle used for
 * `benchmark_mode`. Radiogroup semantics so it is keyboard + screen-reader
 * accessible; selection is fully controlled by the caller (react-hook-form).
 *
 * Keyboard model is the APG radio-group one: the group holds a single tab stop
 * (only the checked radio is tabbable), and the arrow keys move focus AND
 * selection between options, wrapping at both ends. Both axes are bound because
 * the control is visually horizontal but wraps to more than one row at narrow
 * widths, where Up/Down is what a user reaches for.
 */
export function SegmentedControl<T extends string>({
  value,
  onChange,
  options,
  ariaLabel,
  id,
  'aria-describedby': describedBy,
  className,
  disabled = false,
}: Readonly<{
  value: T;
  onChange: (value: T) => void;
  options: readonly { value: T; label: string }[];
  ariaLabel?: string;
  id?: string;
  'aria-describedby'?: string;
  className?: string;
  disabled?: boolean;
}>) {
  const buttonsRef = useRef<Array<HTMLButtonElement | null>>([]);
  // With an off-list `value` nothing is checked, and a group where every option
  // is tabIndex={-1} is unreachable by keyboard — fall back to the first option.
  const selectedIndex = options.findIndex((option) => option.value === value);
  const tabStop = selectedIndex === -1 ? 0 : selectedIndex;

  const move = (from: number, delta: number) => {
    if (options.length === 0) return;
    const next = (from + delta + options.length) % options.length;
    onChange(options[next].value);
    buttonsRef.current[next]?.focus();
  };

  return (
    <div
      id={id}
      role="radiogroup"
      aria-label={ariaLabel}
      aria-describedby={describedBy}
      className={cn(segmentedTrackVariants(), className)}
    >
      {options.map((option, index) => {
        const selected = option.value === value;
        return (
          <button
            key={option.value}
            ref={(node) => {
              buttonsRef.current[index] = node;
            }}
            type="button"
            // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- Button-based radio keeps roving focus and the segmented-control visual contract.
            role="radio"
            aria-checked={selected}
            disabled={disabled}
            // Roving tabindex: Tab enters the group at the current selection and
            // leaves it again, rather than stepping through every option.
            tabIndex={index === tabStop ? 0 : -1}
            onClick={() => onChange(option.value)}
            onKeyDown={(event) => {
              const delta = ARROW_DELTA[event.key];
              if (delta === undefined) return;
              // Only once we know we are handling the key — otherwise this would
              // swallow page scrolling for arrows we do not act on.
              event.preventDefault();
              move(index, delta);
            }}
            className={segmentedItemVariants({ selected })}
          >
            {option.label}
          </button>
        );
      })}
    </div>
  );
}
