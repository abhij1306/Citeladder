import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { StaggerGroup, StaggerItem } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';
import { LANDING_ICONS } from './landing-icons';

export function Workflow() {
  const { workflow } = LANDING_CONTENT;
  return (
    <Section id="how-it-works" tone="sunken" rhythm="base" aria-labelledby="workflow-title">
      <SectionHeader
        eyebrow={workflow.kicker}
        title={workflow.title}
        lead={workflow.lead}
        align="center"
        headingId="workflow-title"
      />
      <div className="relative">
        {/* Connector — a Pale-Silver rule behind the discs, joining the four
            steps on wide screens. The discs' band-coloured ring masks it at
            each icon so the line reads as connecting them. */}
        <div
          aria-hidden
          className="bg-border absolute top-6 right-[12.5%] left-[12.5%] hidden h-px xl:block"
        />
        <StaggerGroup className="relative grid gap-x-6 gap-y-10 sm:grid-cols-2 xl:grid-cols-4">
          {workflow.steps.map((step) => {
            const Icon = LANDING_ICONS[step.icon];
            return (
              <StaggerItem key={step.num} className="flex flex-col items-center text-center">
                <span className="bg-accent text-accent-fg ring-background-alt flex size-12 items-center justify-center rounded-full ring-8">
                  <Icon className="size-5" strokeWidth={1.75} aria-hidden />
                </span>
                <span className="text-subtle mt-5 font-mono text-xs tabular-nums">{step.num}</span>
                <h3 className="website-small-heading text-foreground mt-1">{step.label}</h3>
                <p className="website-body text-muted mt-2 max-w-[34ch]">{step.desc}</p>
              </StaggerItem>
            );
          })}
        </StaggerGroup>
      </div>
    </Section>
  );
}
