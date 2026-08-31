import type { ComponentPropsWithoutRef, ReactNode, Ref } from 'react';

import { cn } from '@/lib/utils';

/**
 * Control-height input (§8, --control-height = 32px); focus = --focus-ring via
 * `.focus-ring` plus the semantic focused border (`focus:border-accent`). Text-like
 * controls consume `inputClasses`; selection is owned by the shared Select.
 *
 * The field text is `text-sm` (14/20), the product body default, so what the
 * user types reads as primary body text next to the labels above it.
 *
 * The fill is the shared input surface, so the
 * field reads as an inset well on a white card. Hover deepens the
 * hairline to border-strong rather than tinting it brand blue: blue on hover
 * pre-empts the focus signal, which owns blue on its own.
 */
export const inputClasses =
  'focus-ring h-[var(--control-height)] w-full rounded-[var(--radius-control)] border border-border-strong/80 bg-input px-2.5 text-sm text-foreground transition-[border-color,box-shadow] placeholder:text-muted hover:border-border-bold focus:border-accent aria-invalid:border-danger disabled:cursor-not-allowed disabled:opacity-50';

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
  containerClassName,
  startContent,
  endContent,
  size = 'md',
  ref,
  ...props
}: Readonly<
  Omit<ComponentPropsWithoutRef<'input'>, 'size'> & {
    size?: keyof typeof inputSizes;
    /** Leading content rendered inside the shared input frame. */
    startContent?: ReactNode;
    /** Trailing content rendered inside the shared input frame. */
    endContent?: ReactNode;
    /** Layout for the frame; `className` continues to target the native input. */
    containerClassName?: string;
    ref?: Ref<HTMLInputElement>;
  }
>) {
  if (!startContent && !endContent) {
    return <input ref={ref} className={cn(inputClasses, inputSizes[size], className)} {...props} />;
  }

  return (
    <div
      className={cn(
        'border-border-strong/80 bg-input focus-within:border-accent focus-within:shadow-[var(--focus-ring)] has-[[aria-invalid=true]]:border-danger flex h-[var(--control-height)] w-full items-center gap-2 rounded-[var(--radius-control)] border px-2.5 transition-[border-color,box-shadow] hover:border-border-bold',
        size === 'lg' && 'h-[var(--control-height-lg)] px-3',
        props.disabled && 'cursor-not-allowed opacity-50',
        containerClassName,
      )}
    >
      {startContent ? (
        <span className="text-muted flex shrink-0 items-center">{startContent}</span>
      ) : null}
      <input
        ref={ref}
        className={cn(
          'placeholder:text-muted min-w-0 flex-1 bg-transparent text-sm text-foreground outline-none focus-visible:outline-none! disabled:cursor-not-allowed',
          className,
        )}
        {...props}
      />
      {endContent ? <span className="flex shrink-0 items-center">{endContent}</span> : null}
    </div>
  );
}
