'use client';

import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { useInsertionEffect, useRef, type ReactNode } from 'react';

import { cn } from '@/lib/utils';
import { Button } from './button';

/**
 * Dialog (§8) — Radix modal. Scrim = --overlay-scrim, surface = bg-elevated,
 * shadow-modal, and the shared overlay radius. Header, body, and footer use
 * the modal-padding rhythm and include a built-in close button.
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
  const returnFocusRef = useRef<HTMLElement | null>(null);
  const wasOpenRef = useRef(false);

  useInsertionEffect(() => {
    if (open && !wasOpenRef.current) {
      const activeElement = document.activeElement;
      returnFocusRef.current =
        activeElement instanceof HTMLElement &&
        activeElement !== document.body &&
        activeElement !== document.documentElement &&
        activeElement.isConnected
          ? activeElement
          : null;
    }
    wasOpenRef.current = open;
  }, [open]);

  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      <DialogPrimitive.Portal>
        <DialogPrimitive.Overlay className="dialog-overlay bg-overlay-scrim z-overlay fixed inset-0" />
        <DialogPrimitive.Content
          onCloseAutoFocus={(event) => {
            const returnTarget = returnFocusRef.current;
            if (!returnTarget?.isConnected) return;
            event.preventDefault();
            returnTarget.focus();
            returnFocusRef.current = null;
          }}
          className={cn(
            'dialog-panel border-border-subtle bg-elevated shadow-modal-value z-modal fixed top-1/2 left-1/2 flex max-h-5/6 w-[42rem] max-w-[calc(100vw-2rem)] min-w-0 -translate-x-1/2 -translate-y-1/2 flex-col box-border rounded-[var(--radius-overlay)] border focus:outline-none',
            className,
          )}
        >
          <header className="border-border-subtle flex items-start justify-between gap-4 border-b px-[var(--modal-padding)] pt-[var(--modal-padding)] pb-4">
            <div className="grid min-w-0 gap-1">
              <DialogPrimitive.Title className="text-foreground text-xl font-medium tracking-tight">
                {title}
              </DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description className="text-secondary text-sm leading-relaxed">
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
          <div className="min-h-0 flex-1 overflow-auto overscroll-contain px-[var(--modal-padding)] py-4">
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
