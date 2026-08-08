'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { LayerTabs, type LayerTab } from '@/components/layout/layer-tabs';
import { TrafficScreen } from '@/components/traffic/traffic-screen';
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
  { id: 'visibility', label: 'Visibility' },
  { id: 'traffic', label: 'Traffic' },
  { id: 'signals', label: 'Demand signals' },
];

function DemandTabPanel() {
  const tab = useSearchParams().get('tab') ?? 'visibility';

  if (tab === 'visibility') return <VisibilityDashboard />;
  if (tab === 'traffic') return <TrafficScreen />;

  return (
    <div className="border-border-subtle bg-panel rounded-lg border p-8">
      <p className="text-foreground text-sm font-medium">Not yet available</p>
      <p className="text-muted mt-2 max-w-[60ch] text-sm leading-relaxed">
        Demand signals with their time window, source coverage, and the join that produced them.
      </p>
    </div>
  );
}

export default function DemandPage() {
  return (
    <TooltipProvider>
      <div className="flex flex-col gap-6">
        <Suspense fallback={null}>
          <LayerTabs tabs={TABS} />
          <DemandTabPanel />
        </Suspense>
      </div>
    </TooltipProvider>
  );
}
