import type { LucideIcon } from 'lucide-react';

import { ICONS } from '@/lib/icons';

/**
 * Sidebar navigation model (F5, simplified): two groups — Analyze / Improve —
 * with twelve live items, all navigable. Icons come from the canonical map
 * (`@/lib/icons`) so nav glyphs stay consistent with the rest of the app.
 * This is data-only so the sidebar component stays presentational and the nav
 * is unit-testable.
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
    title: 'Home',
    items: [{ label: 'Command center', href: '/projects', icon: ICONS.setup }],
  },
  {
    title: 'Analyze',
    items: [
      { label: 'Visibility', href: '/visibility', icon: ICONS.visibility },
      { label: 'AI Referrals', href: '/analytics', icon: ICONS.analytics },
      { label: 'Traffic', href: '/traffic', icon: ICONS.traffic },
      // Single prompts surface: read view by default, manage mode in-page.
      { label: 'Prompts', href: '/prompts', icon: ICONS.prompts },
      // Commerce workspace: catalog + product visibility + attribution in one
      // surface. The href stays `/products`; only the label changed.
      { label: 'Commerce', href: '/products', icon: ICONS.products },
      { label: 'Runs', href: '/runs', icon: ICONS.runs },
    ],
  },
  {
    title: 'Resolve',
    items: [
      { label: 'Site health', href: '/site-health', icon: ICONS.siteHealth },
      { label: 'Issues', href: '/issues', icon: ICONS.issues },
      { label: 'Recommended actions', href: '/opportunities', icon: ICONS.opportunities },
    ],
  },
  {
    title: 'Improve',
    items: [
      { label: 'Content', href: '/content', icon: ICONS.content },
      { label: 'Brand knowledge', href: '/knowledge-base', icon: ICONS.knowledgeBase },
    ],
  },
];
