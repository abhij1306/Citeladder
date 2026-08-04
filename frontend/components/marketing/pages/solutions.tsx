import {
  ArrowRight,
  Briefcase,
  Building2,
  Check,
  Megaphone,
  Rocket,
  ShoppingBag,
} from 'lucide-react';

import { DEMO_CTA, DEMO_HREF } from '@/lib/marketing-content/nav';
import { SOLUTION_SEGMENTS, SOLUTIONS_HERO } from '@/lib/marketing-content/solutions';
import { cn } from '@/lib/utils';

import { ButtonLink, TextLink } from '../primitives/button';
import { Meta } from '../primitives/label';
import { PageHero } from '../primitives/page-hero';
import { Section } from '../primitives/section';
import { Reveal } from '../primitives/reveal';
import { SolutionEvidencePanel } from '../scenes/evidence-panel';

/**
 * `/solutions` — five audience segments, each alternating copy and an
 * evidence panel. The section ids (`agencies`, `in-house`, `founders`,
 * `commerce`, `pr`) are the targets of the nav's Solutions dropdown and the
 * footer, so they are part of the route's contract.
 */
const SEGMENT_ICONS = {
  agencies: Briefcase,
  'in-house': Building2,
  founders: Rocket,
  commerce: ShoppingBag,
  pr: Megaphone,
} as const;

export function SolutionsHero() {
  return (
    <PageHero
      centered
      eyebrow={SOLUTIONS_HERO.eyebrow}
      title={SOLUTIONS_HERO.title}
      accent={SOLUTIONS_HERO.accent}
      lead={SOLUTIONS_HERO.lead}
    >
      <nav aria-label="Solutions by team" className="mt-8 flex flex-wrap justify-center gap-4">
        {SOLUTION_SEGMENTS.map(({ id, label }) => {
          const Icon = SEGMENT_ICONS[id as keyof typeof SEGMENT_ICONS];
          return (
            <a
              key={id}
              href={`#${id}`}
              className="border-border-subtle bg-panel text-foreground shadow-card hover:border-border hover:shadow-card-hover inline-flex items-center gap-4 rounded-md border px-5 py-4 text-sm font-semibold transition-[border-color,box-shadow] duration-200"
            >
              <Icon aria-hidden strokeWidth={1.8} className="text-muted size-4" />
              {label}
            </a>
          );
        })}
      </nav>
    </PageHero>
  );
}

export function SolutionSegments() {
  return (
    <>
      {SOLUTION_SEGMENTS.map((segment, index) => (
        <Section
          key={segment.id}
          id={segment.id}
          tone={index % 2 ? 'sunken' : 'paper'}
          rhythm="base"
          aria-label={segment.label}
        >
          <Reveal
            className={cn(
              'grid items-center gap-10 lg:grid-cols-2 lg:gap-16',
              // Alternating sides stop five consecutive segments from reading
              // as one long list.
              index % 2 === 1 && '[&>*:first-child]:lg:order-2',
            )}
          >
            <div>
              <Meta as="p">{segment.eyebrow}</Meta>
              <h2 className="font-display text-foreground mt-5 max-w-[32ch] text-3xl">
                {segment.title}
              </h2>

              <Meta as="p" className="mt-8 mb-4">
                The pain
              </Meta>
              <ul className="grid gap-4">
                {segment.pains.map((pain) => (
                  <li key={pain} className="text-muted flex gap-4 text-sm">
                    <span aria-hidden className="text-muted">
                      —
                    </span>
                    {pain}
                  </li>
                ))}
              </ul>

              <Meta as="p" className="mt-8 mb-4">
                How CiteLadder maps
              </Meta>
              <ul className="grid gap-4">
                {segment.mappings.map((mapping) => (
                  <li key={mapping} className="text-muted flex gap-4 text-sm">
                    <Check
                      aria-hidden
                      strokeWidth={2.5}
                      className="text-success-text mt-2 size-4 shrink-0"
                    />
                    {mapping}
                  </li>
                ))}
              </ul>

              <div className="mt-8">
                <TextLink href={DEMO_HREF}>
                  {segment.cta}
                  <ArrowRight aria-hidden />
                </TextLink>
              </div>
            </div>

            <SolutionEvidencePanel scene={segment.scene} />
          </Reveal>
        </Section>
      ))}
    </>
  );
}

export function SolutionsCta() {
  return (
    <Section tone="paper" rhythm="base" aria-label="Get started">
      <Reveal className="mx-auto max-w-5xl text-center">
        <h2 className="font-display text-foreground mx-auto mb-5 max-w-[32ch] text-4xl">
          Bring your team the version of the truth it reports in.
        </h2>
        <p className="text-muted mx-auto max-w-[80ch] text-lg">
          One observation field, five ways of reading it. We will walk through the one that matches
          how you are measured.
        </p>
        <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
          <ButtonLink href={DEMO_HREF} className="w-full sm:w-auto">
            {DEMO_CTA}
            <ArrowRight aria-hidden />
          </ButtonLink>
          <ButtonLink href="/pricing" variant="ghost" className="w-full sm:w-auto">
            See pricing
          </ButtonLink>
        </div>
      </Reveal>
    </Section>
  );
}
