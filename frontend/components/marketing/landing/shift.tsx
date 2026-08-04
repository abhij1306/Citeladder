import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { StaggerGroup, StaggerItem } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';

/**
 * The problem, stated as three sharp facts. No cards, no wallpaper — a big
 * numbered statement per fact, set at full width so the type carries the
 * hierarchy instead of a boxed panel. This is the beat that turns the hook's
 * claim into a mechanism the buyer recognises from their own behaviour.
 */
export function Shift() {
  const { shift } = LANDING_CONTENT;
  return (
    <Section id="why" tone="paper" rhythm="base" aria-labelledby="shift-title">
      <SectionHeader eyebrow={shift.kicker} title={shift.title} headingId="shift-title" />
      <StaggerGroup className="grid gap-12 lg:grid-cols-3">
        {shift.facts.map((fact) => (
          <StaggerItem key={fact.num}>
            <p className="text-accent-text font-mono text-xs tabular-nums">{fact.num}</p>
            <h3 className="font-display text-foreground mt-5 max-w-[28ch] text-xl">{fact.title}</h3>
            <p className="text-muted mt-5 max-w-[56ch] text-base">{fact.body}</p>
          </StaggerItem>
        ))}
      </StaggerGroup>
    </Section>
  );
}
