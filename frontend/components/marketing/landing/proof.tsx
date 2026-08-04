import { LANDING_CONTENT } from '@/lib/marketing-content/landing';
import { cn } from '@/lib/utils';

import { Reveal, StaggerGroup, StaggerItem } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';

/**
 * Operating loop — four stages in one ledger. Labels carry sequence without
 * borrowing status colors or turning each stage into a separate card.
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
      <StaggerGroup className="border-border-subtle bg-panel shadow-card grid overflow-hidden rounded-lg border md:grid-cols-2 xl:grid-cols-4">
        {proof.steps.map((step, index) => (
          <StaggerItem
            key={step.label}
            className={cn(
              'border-border-subtle p-6',
              index < proof.steps.length - 1 && 'max-md:border-b',
              index < 2 && 'md:max-xl:border-b',
              index % 2 === 0 && 'md:max-xl:border-r',
              index < proof.steps.length - 1 && 'xl:border-r',
            )}
          >
            <p className="text-accent-text text-xs font-semibold tracking-wide uppercase">
              {step.label}
            </p>
            <h3 className="font-display text-foreground mt-4 text-xl">{step.title}</h3>
            <p className="text-muted mt-3 text-sm leading-relaxed">{step.body}</p>
          </StaggerItem>
        ))}
      </StaggerGroup>
      <Reveal className="mt-10">
        <p className="text-foreground max-w-[72ch] text-base font-semibold">{proof.standard}</p>
      </Reveal>
    </Section>
  );
}
