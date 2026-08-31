import type { ComponentPropsWithoutRef, Ref } from 'react';

import { cn } from '@/lib/utils';

/**
 * Control-height input (§8, --control-height = 32px); focus = --focus-ring via
 * `.focus-ring` plus the ADS focused border (`focus:border-accent`). Text-like
 * controls consume `inputClasses`; selection is owned by the shared Select.
 *
 * The field text is `text-sm` (14/20) — the ADS body default, so what the
 * user types reads as primary body text next to the labels above it.
 *
 * The fill is the shared input surface, so the
 * field reads as an inset well on a white card (ΔE76 4.66) instead of
 * vanishing into it (0.00, the Phase 1 regression). Hover deepens the
 * hairline to border-strong rather than tinting it brand blue: blue on hover
 * pre-empts the focus signal, which owns blue on its own.
 */
export const inputClasses =
  'focus-ring h-[var(--control-height)] w-full rounded-[var(--radius-control)] border border-border-strong/80 bg-input px-2.5 text-sm text-foreground transition-[border-color,box-shadow] placeholder:text-muted hover:border-border-bold focus:border-accent aria-invalid:border-danger disabled:cursor-not-allowed disabled:opacity-50';

const textareaClasses =
  'focus-ring min-h-24 w-full resize-y rounded-[var(--radius-control)] border border-border-strong/80 bg-input p-2.5 text-sm text-foreground transition-[border-color,box-shadow] placeholder:text-muted hover:border-border-bold focus:border-accent aria-invalid:border-danger disabled:cursor-not-allowed disabled:opacity-50';

/**
 * The roomier field used on the standalone auth and onboarding screens, where a
 * form is the whole page rather than one control in a dense table.
 *
 * A TOKEN, never a literal height. `--control-height-lg` rises to the 44px
 * touch minimum on a narrow viewport exactly as `--control-height` does, so a
 * hardcoded `h-10` here would silently shrink the app's most important form
 * below the touch target on the devices most likely to use it.
 */
const inputSizes = {
  md: '',
  lg: 'h-[var(--control-height-lg)] px-3',
} as const;

export function Input({
  className,
  size = 'md',
  ref,
  ...props
}: Readonly<
  Omit<ComponentPropsWithoutRef<'input'>, 'size'> & {
    size?: keyof typeof inputSizes;
    ref?: Ref<HTMLInputElement>;
  }
>) {
  return <input ref={ref} className={cn(inputClasses, inputSizes[size], className)} {...props} />;
}

export function Textarea({
  className,
  ref,
  ...props
}: Readonly<ComponentPropsWithoutRef<'textarea'> & { ref?: Ref<HTMLTextAreaElement> }>) {
  return <textarea ref={ref} className={cn(textareaClasses, className)} {...props} />;
}
