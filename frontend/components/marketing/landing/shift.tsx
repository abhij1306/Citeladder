import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { StaggerGroup, StaggerItem } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';
import { LANDING_ICONS } from './landing-icons';

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
        {shift.facts.map((fact) => {
          const Icon = LANDING_ICONS[fact.icon];
          return (
            <StaggerItem key={fact.label} className="h-full">
              <article className="bg-panel shadow-card hover:shadow-card-hover group flex h-full flex-col justify-between rounded-xl p-6 transition-[box-shadow,transform] duration-300 hover:-translate-y-0.5 md:p-7">
                <div>
                  <div className="flex items-center justify-between">
                    <span className="bg-accent-subtle/80 text-accent-text border-accent-border/60 flex size-9 items-center justify-center rounded-lg border shadow-xs">
                      <Icon className="size-4.5" strokeWidth={1.75} aria-hidden />{' '}
                    </span>
                    <span className="bg-accent-subtle/50 text-accent-text border-accent-border/40 text-2xs rounded-full border px-2.5 py-0.5 font-mono font-semibold tracking-wider uppercase">
                      {fact.label}
                    </span>
                  </div>
                  <h3 className="website-small-heading text-foreground group-hover:text-accent-text mt-5 max-w-[28ch] transition-colors">
                    {fact.title}
                  </h3>
                  <p className="website-body text-muted mt-3 max-w-[48ch]">{fact.body}</p>
                </div>
              </article>
            </StaggerItem>
          );
        })}
      </StaggerGroup>
    </Section>
  );
}
