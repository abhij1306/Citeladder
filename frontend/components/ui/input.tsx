import type { ComponentPropsWithoutRef, Ref } from 'react';

import { cn } from '@/lib/utils';

/**
 * Control-height input (§8, --control-height = 32px); focus = --focus-ring via
 * `.focus-ring` plus the ADS focused border (`focus:border-accent`). Native
 * <select> controls consume `inputClasses` too, so the same treatment flows
 * to every select.
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
  'focus-ring h-[var(--control-height)] w-full rounded-sm border border-border bg-input px-2 text-sm text-foreground transition-[border-color,box-shadow] placeholder:text-muted hover:border-border-strong focus:border-accent aria-invalid:border-danger disabled:cursor-not-allowed disabled:opacity-50';

const textareaClasses =
  'focus-ring min-h-24 w-full resize-y rounded-sm border border-border bg-input p-2 text-sm text-foreground transition-[border-color,box-shadow] placeholder:text-muted hover:border-border-strong focus:border-accent aria-invalid:border-danger disabled:cursor-not-allowed disabled:opacity-50';

export function Input({
  className,
  ref,
  ...props
}: Readonly<ComponentPropsWithoutRef<'input'> & { ref?: Ref<HTMLInputElement> }>) {
  return <input ref={ref} className={cn(inputClasses, className)} {...props} />;
}

export function Textarea({
  className,
  ref,
  ...props
}: Readonly<ComponentPropsWithoutRef<'textarea'> & { ref?: Ref<HTMLTextAreaElement> }>) {
  return <textarea ref={ref} className={cn(textareaClasses, className)} {...props} />;
}
