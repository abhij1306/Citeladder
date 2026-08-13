'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { LayerTabs, type LayerTab } from '@/components/layout/layer-tabs';
import { DemandProjection } from '@/components/demand/demand-projection';
import { VisibilityDashboard } from '@/components/visibility/visibility-dashboard';
import { TooltipProvider } from '@/components/ui/tooltip';

const TABS: readonly LayerTab[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'search', label: 'Search Demand' },
  { id: 'visibility', label: 'AI Visibility' },
];

function DemandTabPanel() {
  const tab = useSearchParams().get('tab') ?? 'overview';

  if (tab === 'visibility') return <VisibilityDashboard />;
  if (tab === 'search') return <DemandProjection panel="search" />;
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
      </div>
    </TooltipProvider>
  );
}
