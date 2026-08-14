import type { LucideIcon } from 'lucide-react';

import { ICONS } from '@/lib/icons';

/**
 * Sidebar navigation model. The three intelligence systems are the stable
 * headings; their primary workspaces remain directly reachable beneath them.
 * Sub-surfaces inside a workspace stay in that workspace's tab row.
 */
export type NavItem = {
  label: string;
  href: string;
  icon: LucideIcon;
  /** Optional right-aligned count chip (e.g. open issues). */
  count?: number;
};

export type NavGroup = {
  title: string;
  items: readonly NavItem[];
};

/**
 * The five destinations the mobile bar shows, by href. Derived from
 * `NAV_GROUPS` below rather than hand-listed in `app-shell.tsx`, which is how
 * the mobile bar kept the verb grouping (Analyze / Resolve / Improve) for a
 * full migration after the sidebar had moved on.
 */
const MOBILE_NAV_HREFS = ['/projects', '/site', '/content', '/demand', '/agent'] as const;

export const NAV_GROUPS = [
  {
    title: 'Workspace',
    items: [
      { label: 'Overview', href: '/projects', icon: ICONS.overview },
      { label: 'Growth Agent', href: '/agent', icon: ICONS.agent },
    ],
  },
  {
    title: 'Site Health',
    items: [
      { label: 'Website', href: '/site', icon: ICONS.site },
      { label: 'Issues', href: '/issues', icon: ICONS.issues },
      { label: 'Opportunities', href: '/opportunities', icon: ICONS.opportunities },
      { label: 'Facts', href: '/knowledge-base', icon: ICONS.knowledgeBase },
    ],
  },
  {
    title: 'Content Intelligence',
    items: [{ label: 'Content', href: '/content', icon: ICONS.content }],
  },
  {
    title: 'Demand Intelligence',
    items: [
      { label: 'Search Demand', href: '/demand', icon: ICONS.demand },
      { label: 'AI Visibility', href: '/visibility', icon: ICONS.visibility },
      { label: 'AI Referrals', href: '/ai-referrals', icon: ICONS.analytics },
      { label: 'Traffic', href: '/traffic', icon: ICONS.traffic },
      { label: 'Prompts', href: '/prompts', icon: ICONS.prompts },
      { label: 'Commerce', href: '/products', icon: ICONS.products },
      { label: 'Runs', href: '/runs', icon: ICONS.runs },
    ],
  },
] as const satisfies readonly NavGroup[];

const NAV_ITEMS = NAV_GROUPS.flatMap<NavItem>((group) => group.items);

/**
 * The mobile bar's five slots, in `MOBILE_NAV_HREFS` order. One source of
 * truth with the sidebar: a label or icon change lands in both.
 */
export const MOBILE_NAV_ITEMS: NavItem[] = MOBILE_NAV_HREFS.map((href) => {
  const item = NAV_ITEMS.find((candidate) => candidate.href === href);
  if (!item) throw new Error(`MOBILE_NAV_HREFS references a missing destination: ${href}`);
  return item;
});
