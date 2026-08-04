import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { StaggerGroup, StaggerItem } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';

/**
 * The problem, stated as three plain facts. Spacing and a shared rule carry
 * the hierarchy; status colors and decorative product wallpaper are reserved
 * for actual state and product scenes.
 */
export function Shift() {
  const { shift } = LANDING_CONTENT;
  return (
    <Section id="why" tone="paper" rhythm="base" aria-labelledby="shift-title">
      <SectionHeader eyebrow={shift.kicker} title={shift.title} headingId="shift-title" />
      <StaggerGroup className="border-border-subtle grid gap-8 border-t pt-8 lg:grid-cols-3 lg:gap-10">
        {shift.facts.map((fact) => (
          <StaggerItem key={fact.label}>
            <p className="text-accent-text text-xs font-semibold tracking-wide uppercase">
              {fact.label}
            </p>
            <h3 className="font-display text-foreground mt-4 max-w-[28ch] text-xl">{fact.title}</h3>
            <p className="text-muted mt-3 max-w-[48ch] text-base">{fact.body}</p>
          </StaggerItem>
        ))}
      </StaggerGroup>
    </Section>
  );
}
