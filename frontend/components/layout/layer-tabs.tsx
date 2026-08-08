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
  const tabHref = (tabId: string) => {
    const params = new URLSearchParams(searchParams.toString());
    params.set('tab', tabId);
    return `${pathname}?${params.toString()}`;
  };

  return (
    /* The tab row is chrome, not content: with the redundant page title gone it
       leads the page, so it bleeds to the content gutter on both sides and its
       rule spans the full column — the Peec/Searchable reading, where the
       boundary separates chrome from content rather than boxing a strip.

       Navigation semantics, not tab semantics: these are links that change the
       URL and re-render the route, so `aria-current="page"` is the accurate
       state. `role="tablist"`/`role="tab"` would promise a tabpanel and
       arrow-key roving focus that URL-driven links do not implement. */
    <nav
      aria-label="Sub-surfaces"
      className={cn(
        'border-border -mx-[var(--content-gutter)] -mt-[var(--content-gutter)] mb-1 flex gap-1 overflow-x-auto border-b px-[var(--content-gutter)]',
        className,
      )}
    >
      {tabs.map((tab) => {
        const isActive = tab.id === active;
        return (
          <Link
            key={tab.id}
            href={tabHref(tab.id)}
            aria-current={isActive ? 'page' : undefined}
            className={cn(
              'focus-ring -mb-px shrink-0 border-b-2 px-3 py-2.5 text-sm font-medium transition-colors',
              isActive
                ? 'border-accent text-foreground'
                : 'text-muted hover:text-foreground hover:border-border-strong border-transparent',
            )}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
