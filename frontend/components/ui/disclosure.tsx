'use client';

import type { ReactNode } from 'react';
import * as CollapsiblePrimitive from '@radix-ui/react-collapsible';
import { ChevronDown } from 'lucide-react';

export type DisclosureProps = {
  title: ReactNode;
  children: ReactNode;
  open?: boolean;
  defaultOpen?: boolean;
  onOpenChange?: (open: boolean) => void;
  className?: string;
};

export function Disclosure({
  title,
  children,
  open,
  defaultOpen = false,
  onOpenChange,
  className,
}: Readonly<DisclosureProps>) {
  return (
    <CollapsiblePrimitive.Root
      open={open}
      defaultOpen={defaultOpen}
      onOpenChange={onOpenChange}
      className={className}
    >
      <CollapsiblePrimitive.Trigger className="focus-ring hover:bg-background-alt group flex min-h-[var(--control-height)] w-full items-center justify-between gap-3 rounded-[var(--radius-control)] px-2 text-left text-sm font-medium">
        {title}
        <ChevronDown
          className="text-muted size-4 shrink-0 transition-transform duration-[var(--transition-fast)] group-data-[state=open]:rotate-180"
          aria-hidden
        />
      </CollapsiblePrimitive.Trigger>
      <CollapsiblePrimitive.Content className="disclosure-content overflow-hidden">
        <div className="pt-2">{children}</div>
      </CollapsiblePrimitive.Content>
    </CollapsiblePrimitive.Root>
  );
}
