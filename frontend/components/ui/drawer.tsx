'use client';

import * as DialogPrimitive from '@radix-ui/react-dialog';
import { X } from 'lucide-react';
import { useInsertionEffect, useRef, type ReactNode } from 'react';

import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/** Accessible right-side sheet for contextual evidence and detail. */
export function Drawer({
  open,
  onOpenChange,
  title,
  description,
  children,
  footer,
  className,
  bodyClassName,
  closeLabel = 'Close drawer',
}: Readonly<{
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  className?: string;
  bodyClassName?: string;
  closeLabel?: string;
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
        <DialogPrimitive.Overlay className="drawer-overlay bg-overlay-scrim z-overlay fixed inset-0" />
        <DialogPrimitive.Content
          onCloseAutoFocus={(event) => {
            const returnTarget = returnFocusRef.current;
            if (!returnTarget?.isConnected) return;
            event.preventDefault();
            returnTarget.focus();
            returnFocusRef.current = null;
          }}
          className={cn(
            'drawer-panel border-border-subtle bg-elevated shadow-modal-value z-modal fixed inset-y-0 right-0 flex w-full max-w-180 flex-col rounded-l-[var(--radius-overlay)] border-l focus:outline-none',
            className,
          )}
        >
          <header className="border-border-subtle flex items-start justify-between gap-3 border-b px-[var(--modal-padding)] py-4">
            <div className="min-w-0">
              <DialogPrimitive.Title className="text-foreground text-heading-sm truncate">
                {title}
              </DialogPrimitive.Title>
              {description ? (
                <DialogPrimitive.Description className="text-muted mt-0.5 text-xs">
                  {description}
                </DialogPrimitive.Description>
              ) : null}
            </div>
            <DialogPrimitive.Close asChild>
              <Button variant="ghost" size="icon" aria-label={closeLabel}>
                <X className="size-4" aria-hidden />
              </Button>
            </DialogPrimitive.Close>
          </header>
          <div
            className={cn(
              'min-h-0 flex-1 overflow-x-hidden overflow-y-auto overscroll-contain px-[var(--modal-padding)] py-4',
              bodyClassName,
            )}
          >
            {children}
          </div>
          {footer}
        </DialogPrimitive.Content>
      </DialogPrimitive.Portal>
    </DialogPrimitive.Root>
  );
}
