import { ChevronRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { StaggerGroup, StaggerItem } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';
import { LANDING_ICONS } from './landing-icons';

/**
 * Use cases — six business contexts, each with an icon, a name, and concrete
 * checks it supports.
 */
export function Packs() {
  const { packs } = LANDING_CONTENT;
  return (
    <Section id="use-cases" tone="paper" rhythm="base" aria-labelledby="packs-title">
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
              <article className="bg-panel shadow-card hover:shadow-card-hover group flex h-full flex-col rounded-xl p-6 transition-[box-shadow,transform] duration-300 hover:-translate-y-0.5">
                <div className="flex items-center gap-3">
                  <span className="bg-accent-subtle/80 text-accent-text border-accent-border/60 flex size-9 items-center justify-center rounded-lg border shadow-xs">
                    <Icon className="size-4.5" strokeWidth={1.75} aria-hidden />
                  </span>
                  <h3 className="website-small-heading text-foreground group-hover:text-accent-text transition-colors">
                    {pack.name}
                  </h3>
                </div>
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
