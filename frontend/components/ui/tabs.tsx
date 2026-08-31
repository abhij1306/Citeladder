'use client';

import type { ReactNode } from 'react';
import { createContext, useContext } from 'react';
import * as TabsPrimitive from '@radix-ui/react-tabs';

import { cn } from '@/lib/utils';

type TabItem<T extends string> = { value: T; label: ReactNode; disabled?: boolean };
const ActiveTabContext = createContext<string | null>(null);

export type TabsProps<T extends string> = {
  value: T;
  onValueChange: (value: T) => void;
  items: readonly TabItem<T>[];
  ariaLabel: string;
  children?: ReactNode;
  className?: string;
  rootClassName?: string;
  onIntent?: (value: T) => void;
};

export function Tabs<T extends string>({
  value,
  onValueChange,
  items,
  ariaLabel,
  children,
  className,
  rootClassName,
  onIntent,
}: Readonly<TabsProps<T>>) {
  return (
    <ActiveTabContext value={value}>
      <TabsPrimitive.Root
        value={value}
        onValueChange={(next) => onValueChange(next as T)}
        className={rootClassName}
      >
        <TabsPrimitive.List
          aria-label={ariaLabel}
          className={cn(
            'border-border relative flex w-full max-w-full flex-nowrap gap-1 overflow-x-auto border-b [scrollbar-width:none] [&::-webkit-scrollbar]:hidden',
            className,
          )}
        >
          {items.map((item) => (
            <TabsPrimitive.Trigger
              key={item.value}
              value={item.value}
              disabled={item.disabled}
              onMouseEnter={() => onIntent?.(item.value)}
              onFocus={() => onIntent?.(item.value)}
              className="focus-ring text-secondary hover:bg-background-alt hover:text-foreground data-[state=active]:text-accent-text relative inline-flex h-10 shrink-0 items-center rounded-t-[var(--radius-control)] px-3 text-sm font-medium whitespace-nowrap transition-colors disabled:opacity-50"
            >
              {item.label}
              {item.value === value ? (
                <span className="bg-accent absolute inset-x-2 bottom-0 h-0.5 rounded-full" />
              ) : null}
            </TabsPrimitive.Trigger>
          ))}
        </TabsPrimitive.List>
        {children}
      </TabsPrimitive.Root>
    </ActiveTabContext>
  );
}

export function TabPanel({
  value,
  className,
  children,
  forceMount,
}: Readonly<{ value: string; className?: string; children: ReactNode; forceMount?: true }>) {
  const activeValue = useContext(ActiveTabContext);
  return (
    <TabsPrimitive.Content
      value={value}
      forceMount={forceMount}
      hidden={activeValue !== value}
      className={cn('outline-none', className)}
    >
      {children}
    </TabsPrimitive.Content>
  );
}
