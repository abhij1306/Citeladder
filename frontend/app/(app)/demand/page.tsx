'use client';

import { Suspense } from 'react';
import Link from 'next/link';
import { useSearchParams } from 'next/navigation';

import { LayerTabs, type LayerTab } from '@/components/layout/layer-tabs';
import { DemandProjection } from '@/components/demand/demand-projection';
import { VisibilityDashboard } from '@/components/visibility/visibility-dashboard';
import { TooltipProvider } from '@/components/ui/tooltip';

/**
 * Demand Intelligence (§7.4) — mostly regrouping.
 *
 * `/visibility` and `/traffic` keep their shipped screens under the new
 * grouping and still resolve at their own routes (§3 migration rule).
 * Prompts and Runs stay on their own routes for now rather than being embedded
 * here: `/prompts` already owns `?tab=`-shaped search params for its manage
 * mode, and nesting it under this route's `?tab=` would collide. §11 schedules
 * that URL-contract change for the prompts move itself.
 *
 * Demand signals and the coverage panel land with stage 3.
 */
const TABS: readonly LayerTab[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'search', label: 'Search Demand' },
  { id: 'journeys', label: 'Journeys' },
  { id: 'prompts', label: 'Prompts' },
  { id: 'visibility', label: 'AI Visibility' },
  { id: 'evidence', label: 'Evidence' },
];

/**
 * Demand surfaces that keep their own routes for now. Linked rather than
 * embedded: `/prompts` owns `?tab=`-shaped params for its manage mode and
 * would collide with this route's, and `/runs` and `/analytics` have their own
 * deep-link contracts (§3 keeps every one of them working).
 */
const RELATED = [
  {
    href: '/agent?task=demand_analysis&objective=Explain%20the%20current%20Demand%20signals%20and%20coverage.',
    label: 'Explain with Growth Agent',
  },
  { href: '/prompts', label: 'Prompts' },
  { href: '/traffic', label: 'Traffic' },
  { href: '/analytics', label: 'AI referrals' },
  { href: '/runs', label: 'Runs' },
] as const;

function DemandTabPanel() {
  const tab = useSearchParams().get('tab') ?? 'overview';

  if (tab === 'visibility') return <VisibilityDashboard />;
  if (tab === 'search') return <DemandProjection panel="search" />;
  if (tab === 'journeys') return <DemandProjection panel="journeys" />;
  if (tab === 'evidence') return <DemandProjection panel="evidence" />;
  if (tab === 'prompts') return <DemandProjection panel="prompts" />;
  return <DemandProjection panel="overview" />;
}

export default function DemandPage() {
  return (
    <TooltipProvider>
      <div className="flex flex-col gap-6">
        <Suspense fallback={null}>
          <LayerTabs tabs={TABS} />
          <DemandTabPanel />
        </Suspense>
        <nav aria-label="Related demand surfaces" className="flex flex-wrap items-center gap-4">
          {RELATED.map((item) => (
            <Link
              key={item.href}
              href={item.href}
              className="text-accent-text text-sm font-medium underline-offset-2 hover:underline"
            >
              {item.label}
            </Link>
          ))}
        </nav>
      </div>
    </TooltipProvider>
  );
}
