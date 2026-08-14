'use client';

import { Suspense } from 'react';

import {
  AiReferralsScreen,
  AiReferralsSkeleton,
} from '@/components/ai-referrals/ai-referrals-screen';
import { TooltipProvider } from '@/components/ui/tooltip';

export default function AiReferralsPage() {
  return (
    <TooltipProvider>
      <Suspense fallback={<AiReferralsSkeleton />}>
        <AiReferralsScreen />
      </Suspense>
    </TooltipProvider>
  );
}
