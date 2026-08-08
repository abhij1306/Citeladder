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
