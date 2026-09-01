'use client';

import { Suspense } from 'react';

import { OnboardingScreen } from '@/components/onboarding/onboarding-screen';

export function OnboardingPageClient() {
  return (
    <Suspense fallback={null}>
      <OnboardingScreen />
    </Suspense>
  );
}
