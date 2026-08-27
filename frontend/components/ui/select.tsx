import type { ComponentPropsWithoutRef, Ref } from 'react';

import { inputClasses } from '@/components/ui/input';
import { cn } from '@/lib/utils';

/**
 * Select (§8) — the shared single-choice control.
 *
 * A native <select> on purpose: it is one value out of a list, it must stay
 * keyboard- and screen-reader-native, and on touch it should open the
 * platform picker. The Radix `Dropdown` set is for menus of ACTIONS, and
 * `MarketSelect` is a searchable combobox for long lists; neither is this.
 *
 * It exists because Commerce hand-rolled `bg-input h-8 rounded-sm border px-2
 * text-sm` inline instead — a literal height instead of `--control-height`, a
 * plain hairline instead of the ADS border, and no focus ring at all. The
 * control recipe belongs in one place; `input.tsx` already documents that a
 * native select consumes `inputClasses`.
 *
 * The chevron is drawn here rather than left to the UA default so the control
 * matches Input's geometry on every platform; `appearance-none` removes the
 * native arrow and the extra right padding makes room for ours.
 */
export function Select({
  className,
  wrapperClassName,
  ref,
  children,
  ...props
}: Readonly<
  ComponentPropsWithoutRef<'select'> & {
    ref?: Ref<HTMLSelectElement>;
    /** Sizing for the control as a whole. Defaults to shrink-to-content, so a
     * select dropped into a toolbar does not stretch across the row. */
    wrapperClassName?: string;
  }
>) {
  return (
    <div className={cn('relative inline-grid', wrapperClassName)}>
      <select ref={ref} className={cn(inputClasses, 'appearance-none pr-8', className)} {...props}>
        {children}
      </select>
      <svg
        aria-hidden
        viewBox="0 0 16 16"
        className="text-muted pointer-events-none absolute top-1/2 right-2.5 size-4 -translate-y-1/2"
      >
        <path
          d="M4 6l4 4 4-4"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        />
      </svg>
    </div>
  );
}
