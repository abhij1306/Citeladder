import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { StaggerGroup, StaggerItem } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';
import { LANDING_ICONS } from './landing-icons';

/**
 * The problem, stated as one quiet evidence ledger rather than three cards.
 */
export function Shift() {
  const { shift } = LANDING_CONTENT;
  return (
    <Section id="why" tone="paper" rhythm="base" aria-labelledby="shift-title">
      <SectionHeader eyebrow={shift.kicker} title={shift.title} headingId="shift-title" />
      <StaggerGroup className="border-border-subtle divide-border-subtle grid border-y lg:grid-cols-3 lg:divide-x">
        {shift.facts.map((fact) => {
          const Icon = LANDING_ICONS[fact.icon];
          return (
            <StaggerItem key={fact.label} className="h-full">
              <article className="group flex h-full flex-col justify-between px-1 py-7 md:px-6 lg:first:pl-0 lg:last:pr-0">
                <div>
                  <div className="flex items-center gap-3">
                    <span className="bg-accent-subtle text-accent-text flex size-9 items-center justify-center rounded-[var(--radius-control)]">
                      <Icon className="size-4.5" strokeWidth={1.75} aria-hidden />{' '}
                    </span>
                    <span className="text-muted text-xs font-medium tracking-wide uppercase">
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
