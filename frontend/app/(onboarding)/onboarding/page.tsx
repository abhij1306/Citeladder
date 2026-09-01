import type { Metadata } from 'next';

import { OnboardingPageClient } from './onboarding-page-client';

export const metadata: Metadata = {
  robots: { index: false, follow: false },
};

/**
 * `/onboarding` — project creation via AI auto-discovery. Replaces the retired
 * `/setup`, `/setup/new` and `/setup/[projectId]` routes.
 *
 * Wrapped in Suspense because the screen reads `useSearchParams` (`?new=1`),
 * which opts the subtree into client-side rendering.
 */
export default function OnboardingPage() {
  return <OnboardingPageClient />;
}
