'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { ContentScreen } from '@/components/content/content-screen';
import { TooltipProvider } from '@/components/ui/tooltip';
import { DEMAND_SIGNAL_PARAM } from '@/lib/demand/content-brief';

function ContentSurface() {
  const searchParams = useSearchParams();
  return (
    <ContentScreen
      opportunityId={searchParams.get('opportunity_id')}
      demandSignalId={searchParams.get(DEMAND_SIGNAL_PARAM)}
    />
  );
}

export default function ContentPage() {
  return (
    // The skill picker explains each format through tooltips.
    <TooltipProvider>
      <Suspense fallback={null}>
        <ContentSurface />
      </Suspense>
    </TooltipProvider>
  );
}
