'use client';

import { Suspense } from 'react';

import { AnalyticsScreen, AnalyticsSkeleton } from '@/components/analytics/analytics-screen';
import { TooltipProvider } from '@/components/ui/tooltip';

export default function AiReferralsPage() {
  return (
    <TooltipProvider>
      <Suspense fallback={<AnalyticsSkeleton />}>
        <AnalyticsScreen />
      </Suspense>
    </TooltipProvider>
  );
}
