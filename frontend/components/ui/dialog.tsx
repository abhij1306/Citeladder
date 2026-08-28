'use client';

import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';
import { Button } from './button';

/**
 * Dialog (§8) — Radix modal. Scrim = --overlay-scrim, surface = bg-elevated,
 * shadow-modal, --radius-lg (12px = the ADS modal rung). Header/body/footer
 * slots padded on the ADS modal rhythm (24px inline; 24/16 block); built-in
 * close button.
 */
export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  className,
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
}>) {
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="bg-overlay-scrim z-overlay fixed inset-0" />
        <DialogPrimitive.Content
          className={cn(
            'border-border-subtle bg-elevated shadow-modal-value z-modal fixed top-1/2 left-1/2 flex max-h-5/6 w-full max-w-2xl -translate-x-1/2 -translate-y-1/2 flex-col rounded-[var(--radius-overlay)] border focus:outline-none',
            className,
          )}
        >
          <header className="border-border-subtle flex items-start justify-between gap-4 border-b px-[var(--modal-padding)] pt-[var(--modal-padding)] pb-4">
            <div className="grid min-w-0 gap-1">
              <DialogPrimitive.Title className="text-foreground text-lg">
                {title}
              </DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description className="text-secondary text-sm">
                  {description}
                </DialogPrimitive.Description>
              ) : null}
            </div>
            <DialogPrimitive.Close asChild>
              <Button variant="ghost" size="icon" aria-label="Close dialog">
                <X className="size-4" aria-hidden />
              </Button>
            </DialogPrimitive.Close>
          </header>
          <div className="min-h-0 flex-1 overflow-auto overscroll-contain px-[var(--modal-padding)] py-1">
            {children}
          </div>
          {footer ? (
            <footer className="border-border-subtle flex items-center justify-end gap-2 border-t px-[var(--modal-padding)] pt-4 pb-[var(--modal-padding)]">
              {footer}
            </footer>
          ) : null}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
