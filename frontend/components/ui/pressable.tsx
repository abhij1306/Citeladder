'use client';

import type { ButtonHTMLAttributes, Ref } from 'react';

import { cn } from '@/lib/utils';

export type PressableProps = ButtonHTMLAttributes<HTMLButtonElement> & {
  ref?: Ref<HTMLButtonElement>;
};

/** Accessible behavior for rows and cards that must not look like buttons. */
export function Pressable({ className, type = 'button', ref, ...props }: Readonly<PressableProps>) {
  return (
    <button
      ref={ref}
      type={type}
      className={cn(
        'focus-ring w-full rounded-[var(--radius-control)] text-left transition-[background-color,transform] duration-[var(--transition-fast)] ease-[var(--ease-standard)] active:scale-[0.995] disabled:pointer-events-none disabled:opacity-60',
        className,
      )}
      {...props}
    />
  );
}
