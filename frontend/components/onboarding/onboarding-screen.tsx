'use client';

import { cn } from '@/lib/utils';

import { useOnboardingFlow } from './onboarding-flow';
import {
  OnboardingMobileHeader,
  OnboardingSidebar,
  STEP_MAIN_ALIGNMENT,
} from './onboarding-layout';
import { BrandStage, DiscoveryStage, ReviewStage } from './onboarding-stages';

/** The onboarding transaction coordinator; each visual stage owns its own UI. */
export function OnboardingScreen() {
  const flow = useOnboardingFlow();
  const stage =
    flow.step === 0 ? (
      <BrandStage form={flow.form} isAdditional={flow.isAdditional} onSubmit={flow.submitBrand} />
    ) : flow.step === 1 ? (
      <DiscoveryStage
        brandName={flow.brand?.brand_name}
        discovery={flow.discovery}
        onEdit={() => flow.setStep(0)}
        onReview={() => flow.setStep(2)}
      />
    ) : (
      <ReviewStage flow={flow} />
    );

  return (
    <div className="website-type bg-panel text-foreground selection:bg-accent selection:text-accent-fg relative h-screen max-h-screen w-full overflow-hidden antialiased min-[900px]:grid min-[900px]:grid-cols-12">
      <OnboardingSidebar step={flow.step} />
      <div className="bg-panel relative col-span-12 flex h-screen max-h-screen flex-col justify-between overflow-hidden p-6 min-[900px]:col-span-7 sm:px-8 sm:py-6 lg:col-span-8 lg:px-10 lg:py-8 xl:py-10">
        <OnboardingMobileHeader step={flow.step} />
        <main
          id="main"
          className={cn(
            'mx-auto flex min-h-0 w-full flex-1 flex-col overflow-y-auto py-2 text-sm sm:py-3 lg:py-4',
            flow.step === 2 ? 'max-w-6xl' : 'max-w-xl',
            STEP_MAIN_ALIGNMENT[flow.step],
          )}
        >
          <div className="p-1 sm:p-2">{stage}</div>
        </main>
      </div>
    </div>
  );
}
