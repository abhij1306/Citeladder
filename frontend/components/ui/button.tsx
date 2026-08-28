'use client';

import type { ComponentPropsWithoutRef, Ref } from 'react';
import type { VariantProps } from 'class-variance-authority';

import { Slot } from '@radix-ui/react-slot';

import { cn } from '@/lib/utils';
import { buttonVariants } from './button-variants';

export type ButtonProps = ComponentPropsWithoutRef<'button'> &
  VariantProps<typeof buttonVariants> & {
    /** Render the child element as the button (Radix Slot) instead of a <button>. */
    asChild?: boolean;
    ref?: Ref<HTMLButtonElement>;
  };

export function Button({
  className,
  variant,
  size,
  asChild = false,
  type,
  ref,
  ...props
}: Readonly<ButtonProps>) {
  const Comp = asChild ? Slot : 'button';
  const opensPopup = props['aria-haspopup'] !== undefined;
  return (
    <Comp
      ref={ref}
      // A real <button> defaults to type="button" (avoid accidental submits);
      // when asChild we forward whatever the caller renders.
      type={asChild ? undefined : (type ?? 'button')}
      data-button-variant={variant ?? 'primary'}
      data-button-size={size ?? 'md'}
      className={cn(buttonVariants({ variant, size }), opensPopup && 'active:scale-100', className)}
      {...props}
    />
  );
}
