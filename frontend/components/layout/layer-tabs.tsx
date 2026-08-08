'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';

import { cn } from '@/lib/utils';

/**
 * Tabs for a layer route (§4).
 *
 * Within a layer, sub-surfaces are tabs on the layer route rather than sidebar
 * children — two levels of navigation is the limit. Tab state lives in `?tab=`
 * so a tab is linkable, refresh-safe, and back-button-correct; the plan calls
 * out losing state on refresh as a real bug elsewhere in the app.
 */
export type LayerTab = {
  id: string;
  label: string;
};

export function LayerTabs({
  tabs,
  className,
}: Readonly<{ tabs: readonly LayerTab[]; className?: string }>) {
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const active = searchParams.get('tab') ?? tabs[0]?.id;

  return (
    <div role="tablist" className={cn('border-border-subtle flex gap-1 border-b', className)}>
      {tabs.map((tab) => {
        const isActive = tab.id === active;
        return (
          <Link
            key={tab.id}
            href={`${pathname}?tab=${tab.id}`}
            role="tab"
            aria-selected={isActive}
            className={cn(
              'focus-ring -mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors',
              isActive
                ? 'border-accent text-foreground'
                : 'text-muted hover:text-foreground border-transparent',
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </div>
  );
}
