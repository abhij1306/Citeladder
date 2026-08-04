import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { StaggerGroup, StaggerItem } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';

/**
 * The problem, stated as three plain facts on quiet white cards. The shared
 * panel surface carries hierarchy without borrowing status or evidence colors.
 */
export function Shift() {
  const { shift } = LANDING_CONTENT;
  return (
    <Section id="why" tone="paper" rhythm="base" aria-labelledby="shift-title">
      <SectionHeader eyebrow={shift.kicker} title={shift.title} headingId="shift-title" />
      <StaggerGroup className="grid gap-5 lg:grid-cols-3">
        {shift.facts.map((fact) => (
          <StaggerItem key={fact.label} className="h-full">
            <article className="bg-panel shadow-card h-full rounded-lg p-6 md:p-7">
              <p className="text-accent-text text-xs font-semibold tracking-wide uppercase">
                {fact.label}
              </p>
              <h3 className="font-display text-foreground mt-4 max-w-[28ch] text-xl">
                {fact.title}
              </h3>
              <p className="text-muted mt-3 max-w-[48ch] text-base">{fact.body}</p>
            </article>
          </StaggerItem>
        ))}
      </StaggerGroup>
    </Section>
  );
}
