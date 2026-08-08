import type { LucideIcon } from 'lucide-react';

import { ICONS } from '@/lib/icons';

/**
 * Sidebar navigation model — the four-layer architecture, flat.
 *
 * frontend-growth-intelligence.md §4: the sidebar IS the architecture. Six
 * destinations, no verb grouping, two levels of navigation maximum. Within a
 * layer, sub-surfaces are tabs on the layer route rather than sidebar children.
 *
 * The old model grouped twelve items by verb (Home / Analyze / Resolve /
 * Improve), which cut across the architecture: `/site-health` and `/issues` sat
 * under "Resolve" but belong to Site, while `/visibility`, `/traffic`,
 * `/analytics`, `/prompts` and `/runs` were split across "Analyze" and all
 * belong to Demand.
 *
 * Migration rule (§3): every deep link keeps working. Routes that have not
 * moved yet are reached as tabs on their layer route, so no href here 404s.
 * Icons come from the canonical map (`@/lib/icons`). Data-only so the sidebar
 * stays presentational and the nav is unit-testable.
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
  items: NavItem[];
};

/**
 * The five destinations the mobile bar shows, by href. Derived from
 * `NAV_GROUPS` below rather than hand-listed in `app-shell.tsx`, which is how
 * the mobile bar kept the verb grouping (Analyze / Resolve / Improve) for a
 * full migration after the sidebar had moved on.
 */
const MOBILE_NAV_HREFS = ['/projects', '/site', '/content', '/demand', '/agent'] as const;

export const NAV_GROUPS: NavGroup[] = [
  {
    // One flat group: a titled group per item would re-introduce the second
    // level §4 removes.
    title: 'Workspace',
    items: [
      { label: 'Overview', href: '/projects', icon: ICONS.overview },
      { label: 'Site', href: '/site', icon: ICONS.site },
      { label: 'Content', href: '/content', icon: ICONS.content },
      { label: 'Demand', href: '/demand', icon: ICONS.demand },
      // Commerce keeps its own view (§3): it is a distinct workspace, not a
      // tab inside Demand.
      { label: 'Commerce', href: '/products', icon: ICONS.products },
      { label: 'Growth Agent', href: '/agent', icon: ICONS.agent },
      { label: 'Reports', href: '/reports', icon: ICONS.reports },
    ],
  },
];

const NAV_ITEMS = NAV_GROUPS.flatMap((group) => group.items);

/**
 * The mobile bar's five slots, in `MOBILE_NAV_HREFS` order. One source of
 * truth with the sidebar: a label or icon change lands in both.
 */
export const MOBILE_NAV_ITEMS: NavItem[] = MOBILE_NAV_HREFS.map((href) => {
  const item = NAV_ITEMS.find((candidate) => candidate.href === href);
  if (!item) throw new Error(`MOBILE_NAV_HREFS references a missing destination: ${href}`);
  return item;
});
