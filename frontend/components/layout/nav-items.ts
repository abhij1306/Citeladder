import type { LucideIcon } from 'lucide-react';

import { ICONS } from '@/lib/icons';

export type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  count?: number;
  queryMatch?: { key: string; values: readonly string[]; defaultValue?: string };
};

export type NavGroup = {
  title: 'Overview' | 'Analyze' | 'Act' | 'Track';
  href: string;
  icon: LucideIcon;
  items: readonly NavItem[];
};

export const NAV_GROUPS = [
  {
    title: 'Overview',
    href: '/projects',
    icon: ICONS.overview,
    items: [{ label: 'Overview', href: '/projects', icon: ICONS.overview }],
  },
  {
    title: 'Analyze',
    href: '/site?tab=pages',
    icon: ICONS.site,
    items: [
      {
        label: 'Website',
        href: '/site?tab=pages',
        icon: ICONS.site,
        queryMatch: { key: 'tab', values: ['pages'], defaultValue: 'pages' },
      },
      { label: 'Issues', href: '/issues', icon: ICONS.issues },
      { label: 'Search Demand', href: '/demand', icon: ICONS.demand },
      { label: 'Traffic', href: '/traffic', icon: ICONS.traffic },
      { label: 'Commerce Suite', href: '/products', icon: ICONS.products },
    ],
  },
  {
    title: 'Act',
    href: '/opportunities',
    icon: ICONS.opportunities,
    items: [
      { label: 'Opportunities', href: '/opportunities', icon: ICONS.opportunities },
      { label: 'Content', href: '/content', icon: ICONS.content },
    ],
  },
  {
    title: 'Track',
    href: '/visibility?tab=trends',
    icon: ICONS.visibility,
    items: [
      { label: 'Prompts', href: '/prompts', icon: ICONS.prompts },
      {
        label: 'AI Visibility',
        href: '/visibility?tab=trends',
        icon: ICONS.visibility,
        queryMatch: { key: 'tab', values: ['trends'], defaultValue: 'trends' },
      },
      { label: 'Runs', href: '/runs', icon: ICONS.runs },
      { label: 'AI Referrals', href: '/ai-referrals', icon: ICONS.analytics },
    ],
  },
] as const satisfies readonly NavGroup[];

export const MOBILE_NAV_ITEMS = NAV_GROUPS.map(({ title, href, icon }) => ({
  label: title,
  href,
  icon,
}));

export function isNavItemActive(
  pathname: string,
  searchParams: URLSearchParams,
  item: NavItem,
): boolean {
  const target = new URL(item.href, 'https://citeladder.local');
  const pathMatches = pathname === target.pathname || pathname.startsWith(`${target.pathname}/`);
  if (!pathMatches) return false;
  if (!item.queryMatch) return true;
  const current = searchParams.get(item.queryMatch.key) ?? item.queryMatch.defaultValue ?? '';
  return item.queryMatch.values.includes(current);
}

export function activeStation(pathname: string, searchParams: URLSearchParams): NavGroup {
  return (
    NAV_GROUPS.find((group) =>
      group.items.some((item) => isNavItemActive(pathname, searchParams, item)),
    ) ?? NAV_GROUPS[0]
  );
}
