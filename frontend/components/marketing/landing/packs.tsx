import { ChevronRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { StaggerGroup, StaggerItem } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';
import { LANDING_ICONS } from './landing-icons';

/**
 * Use cases — six industry packs, each an icon, a name, its maturity status, and
 * the concrete checks it ships. Status is `text-muted` (Pewter), which clears
 * WCAG AA on the paper band, not the lighter Silver Fog.
 */
export function Packs() {
  const { packs } = LANDING_CONTENT;
  return (
    <Section id="industry-packs" tone="sunken" rhythm="base" aria-labelledby="packs-title">
      <SectionHeader
        eyebrow={packs.kicker}
        title={packs.title}
        lead={packs.lead}
        headingId="packs-title"
      />
      <StaggerGroup className="grid gap-5 md:grid-cols-2 xl:grid-cols-3">
        {packs.items.map((pack) => {
          const Icon = LANDING_ICONS[pack.icon];
          return (
            <StaggerItem key={pack.name} className="h-full">
              <article className="bg-panel border-border shadow-card hover:shadow-card-hover group flex h-full flex-col rounded-xl border p-6 transition-[box-shadow,transform] duration-300 hover:-translate-y-0.5">
                <div className="flex items-center gap-3">
                  <span className="bg-accent-subtle/80 text-accent-text border-accent-border/60 flex size-9 items-center justify-center rounded-lg border shadow-xs">
                    <Icon className="size-4.5" strokeWidth={1.75} aria-hidden />
                  </span>
                  <h3 className="font-display text-foreground group-hover:text-accent-text text-base font-semibold transition-colors">
                    {pack.name}
                  </h3>
                </div>
                <p className="text-muted text-2xs mt-4 font-mono font-semibold tracking-wider uppercase">
                  {pack.status}
                </p>
                <ul className="mt-4 flex flex-col gap-2">
                  {pack.points.map((point) => (
                    <li
                      key={point}
                      className="text-secondary flex items-start gap-2 text-sm font-medium"
                    >
                      <ChevronRight
                        className="text-accent-text mt-0.5 size-3.5 shrink-0"
                        aria-hidden
                      />
                      <span>{point}</span>
                    </li>
                  ))}
                </ul>
              </article>
            </StaggerItem>
          );
        })}
      </StaggerGroup>
    </Section>
  );
}
