'use client';

import Link from 'next/link';

import { FlowActions, FlowShell, type FlowStep } from '@/components/auth/flow-shell';
import { Button } from '@/components/ui/button';

import { hasConfirmedIcp } from './icp-confirmation';
import { useOnboardingFlow } from './onboarding-flow';
import { BrandStage, DiscoveryStage, ReviewStage } from './onboarding-stages';

const STEPS: readonly FlowStep[] = [
  { id: 'brand', label: 'Basics' },
  { id: 'discovery', label: 'Research' },
  { id: 'review', label: 'Confirm' },
];

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
      />
    ) : (
      <ReviewStage flow={flow} />
    );

  return (
    <FlowShell
      mainLabel="Project setup"
      steps={STEPS}
      currentStep={flow.step}
      exitHref={flow.isAdditional ? '/projects' : '/'}
      measure={flow.step === 2 ? 'wide' : 'default'}
      actions={<OnboardingActions flow={flow} />}
    >
      {stage}
    </FlowShell>
  );
}

function OnboardingActions({ flow }: Readonly<{ flow: ReturnType<typeof useOnboardingFlow> }>) {
  if (flow.step === 0) {
    return (
      <FlowActions
        secondary={
          flow.isAdditional ? (
            <Button asChild variant="ghost" size="md">
              <Link href="/projects">Cancel</Link>
            </Button>
          ) : undefined
        }
        primary={
          <Button type="submit" form="onboarding-brand-form" size="md">
            Continue
          </Button>
        }
      />
    );
  }

  if (flow.step === 1) {
    const discoveryReady =
      !flow.discovery.isRunning && flow.discovery.discovery?.status === 'ready';
    return (
      <FlowActions
        secondary={
          <Button variant="ghost" size="md" onClick={() => flow.setStep(0)}>
            Back
          </Button>
        }
        primary={
          <Button size="md" onClick={() => flow.setStep(2)} disabled={!discoveryReady}>
            {flow.discovery.isRunning ? 'Searching…' : 'Review'}
          </Button>
        }
      />
    );
  }

  return (
    <FlowActions
      wide
      secondary={
        <Button
          variant="ghost"
          size="md"
          onClick={() => flow.setStep(1)}
          disabled={flow.isCompleting}
        >
          Back
        </Button>
      }
      primary={
        <Button
          size="md"
          onClick={() => flow.complete.mutate()}
          pending={flow.isCompleting}
          pendingLabel="Creating…"
          disabled={
            flow.completionFailed || !flow.hasSelectedDomain || !hasConfirmedIcp(flow.profile)
          }
        >
          Create project
        </Button>
      }
    />
  );
}
