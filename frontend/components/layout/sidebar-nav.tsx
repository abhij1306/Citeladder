'use client';

import Link from 'next/link';
import { usePathname, useSearchParams } from 'next/navigation';

import { eyebrowClasses } from '@/components/ui/eyebrow';
import { cn } from '@/lib/utils';

import {
  MOBILE_NAV_ITEMS,
  NAV_GROUPS,
  activeStation,
  isNavItemActive,
  type NavGroup,
  type NavItem,
} from './nav-items';

function NavLink({ item, active }: Readonly<{ item: NavItem; active: boolean }>) {
  const Icon = item.icon;
  return (
    <Link
      href={item.href}
      aria-current={active ? 'page' : undefined}
      className={cn(
        'relative flex h-[var(--nav-item-height)] items-center gap-2.5 rounded-[var(--radius-control)] px-2.5 text-sm font-medium transition-colors duration-150',
        active
          ? 'bg-panel text-accent-text'
          : 'text-secondary hover:bg-panel hover:text-foreground',
      )}
    >
      <Icon
        className={cn('size-4 shrink-0', active ? 'text-accent opacity-100' : 'opacity-80')}
        aria-hidden
      />
      <span className="min-w-0 flex-1 truncate">{item.label}</span>
    </Link>
  );
}

function StationLinks({
  group,
  compact = false,
}: Readonly<{ group: NavGroup; compact?: boolean }>) {
  const pathname = usePathname() ?? '';
  const searchParams = useSearchParams();
  const items = group.items;
  if (compact) {
    return (
      <nav aria-label={`${group.title} destinations`} className="overflow-x-auto md:hidden">
        <ul className="flex min-w-max gap-1 px-[var(--content-gutter)] py-2">
          {items.map((item) => (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={isNavItemActive(pathname, searchParams, item) ? 'page' : undefined}
                className={cn(
                  'focus-ring inline-flex min-h-11 items-center rounded-[var(--radius-control)] px-3 text-sm font-medium',
                  isNavItemActive(pathname, searchParams, item)
                    ? 'bg-active text-foreground'
                    : 'text-secondary',
                )}
              >
                {item.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>
    );
  }
  return (
    <ul className="flex flex-col gap-0.5">
      {items.map((item) => (
        <li key={item.href}>
          <NavLink item={item} active={isNavItemActive(pathname, searchParams, item)} />
        </li>
      ))}
    </ul>
  );
}

export function SidebarNav({ className }: Readonly<{ className?: string }>) {
  return (
    <nav aria-label="Primary" className={cn('flex flex-col gap-3', className)}>
      {NAV_GROUPS.map((group) => {
        const showHeading = group.title !== 'Overview';
        return (
          <div key={group.title} className="flex flex-col gap-0">
            {showHeading ? (
              <p className={cn(eyebrowClasses, 'px-1 pb-0.5 text-sm')}>{group.title}</p>
            ) : null}
            <StationLinks group={group} />
          </div>
        );
      })}
    </nav>
  );
}

export function MobileStationNavigation() {
  const pathname = usePathname() ?? '';
  const searchParams = useSearchParams();
  const group = activeStation(pathname, searchParams);
  return <StationLinks group={group} compact />;
}

export function MobilePrimaryNavigation() {
  const pathname = usePathname() ?? '';
  const searchParams = useSearchParams();
  const current = activeStation(pathname, searchParams);
  return (
    <nav
      className="border-border bg-panel safe-bottom fixed inset-x-0 bottom-0 z-30 grid h-16 grid-cols-5 border-t md:hidden"
      aria-label="Primary mobile navigation"
    >
      {MOBILE_NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        const active = item.label === current.title;
        return (
          <Link
            key={item.href}
            href={item.href}
            aria-current={active ? 'page' : undefined}
            className={cn(
              'text-xs flex min-w-0 flex-col items-center justify-center gap-1 font-medium',
              active ? 'text-accent-text' : 'text-muted hover:text-accent-text',
            )}
          >
            <Icon className="size-4" aria-hidden />
            <span className="truncate">{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
