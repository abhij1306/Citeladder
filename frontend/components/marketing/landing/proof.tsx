import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { Reveal, StaggerGroup, StaggerItem } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';

function SpotlightCard({
  children,
  className = '',
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`border-border bg-panel shadow-card hover:bg-background-alt rounded-lg border p-5 transition-[background-color,box-shadow] ${className}`}
    >
      {children}
    </div>
  );
}

/**
 * The "so how is this real" beat — the three steps as cursor-spotlight cards.
 */
export function Proof() {
  const { proof } = LANDING_CONTENT;

  return (
    <Section id="how-it-works" tone="sunken" rhythm="base" aria-labelledby="proof-title">
      <SectionHeader
        eyebrow={proof.kicker}
        title={proof.title}
        lead={proof.intro}
        headingId="proof-title"
      />
      <StaggerGroup className="grid gap-6 md:grid-cols-2 xl:grid-cols-4">
        {proof.steps.map((step) => (
          <StaggerItem key={step.num} className="relative">
            <SpotlightCard className="h-full">
              <p className="text-muted font-mono text-xs uppercase">
                {step.num} / {step.kicker}
              </p>
              <h3 className="font-display text-foreground mt-4 text-xl">{step.title}</h3>
              <p className="text-muted mt-4 max-w-[50ch] text-sm">{step.body}</p>
            </SpotlightCard>
          </StaggerItem>
        ))}
      </StaggerGroup>
      <Reveal className="mt-12">
        <p className="text-foreground border-accent max-w-[80ch] border-l-2 pl-5 text-base font-semibold">
          {proof.standard}
        </p>
      </Reveal>
    </Section>
  );
}
