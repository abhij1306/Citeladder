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
    <div className="product-app bg-panel text-foreground selection:bg-accent selection:text-accent-fg relative h-screen max-h-screen w-full overflow-hidden antialiased min-[900px]:grid min-[900px]:grid-cols-12">
      <OnboardingSidebar step={flow.step} />
      {/* Vertical padding deliberately matches OnboardingSidebar (`p-[var(--card-padding)] xl:p-10`).
          The two columns share one ramp so the stage heading and the rail title
          sit on the same baseline by construction, at every width, rather than
          by a per-breakpoint constant. Horizontal padding is free to differ;
          only the vertical ramp is load-bearing. */}
      <div className="bg-panel relative col-span-12 flex h-screen max-h-screen flex-col justify-between overflow-hidden p-[var(--page-section-gap)] min-[900px]:col-span-7 lg:col-span-8">
        <OnboardingMobileHeader step={flow.step} />
        <main
          id="main"
          className={cn(
            // Top padding is scoped BELOW the 900px split so that above it the
            // only `padding-top` in play is the step alignment. Tailwind orders
            // arbitrary `min-[...]` variants ahead of the named breakpoints, so
            // a plain `py-*`/`pt-*` here outranks `min-[900px]:pt-*` no matter
            // which is written first — which is why the step alignment silently
            // never rendered at all before. Bottom padding keeps its ramp.
            'mx-auto flex min-h-0 w-full flex-1 flex-col overflow-y-auto pb-2 text-sm max-[899px]:pt-3 sm:pb-3 lg:pb-4',
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
