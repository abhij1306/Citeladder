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
      <nav aria-label="Solutions by team" className="mt-8 flex flex-wrap justify-center gap-2.5">
        {SOLUTION_SEGMENTS.map(({ id, label }) => {
          const Icon = SEGMENT_ICONS[id as keyof typeof SEGMENT_ICONS];
          return (
            <a
              key={id}
              href={`#${id}`}
              className="border-mkt-line bg-mkt-surface text-mkt-ink hover:border-mkt-line-strong rounded-mkt-sm text-mkt-sm inline-flex items-center gap-2.5 border px-3.5 py-2.5 font-semibold transition-colors duration-200"
            >
              <Icon aria-hidden strokeWidth={1.8} className="text-mkt-ink-soft size-4" />
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
          tone={index % 2 ? 'sunken' : 'surface'}
          rhythm="loose"
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
              <h2 className="font-mkt-display text-mkt-d3 text-mkt-ink mt-4 max-w-[20ch]">
                {segment.title}
              </h2>

              <Meta as="p" className="mt-8 mb-3">
                The pain
              </Meta>
              <ul className="grid gap-2.5">
                {segment.pains.map((pain) => (
                  <li key={pain} className="text-mkt-sm text-mkt-ink-soft flex gap-3">
                    <span aria-hidden className="text-mkt-line-strong">
                      —
                    </span>
                    {pain}
                  </li>
                ))}
              </ul>

              <Meta as="p" className="mt-8 mb-3">
                How Searchify maps
              </Meta>
              <ul className="grid gap-2.5">
                {segment.mappings.map((mapping) => (
                  <li key={mapping} className="text-mkt-sm text-mkt-ink-soft flex gap-3">
                    <Check
                      aria-hidden
                      strokeWidth={2.5}
                      className="text-mkt-evidence-text mt-0.5 size-3.5 shrink-0"
                    />
                    {mapping}
                  </li>
                ))}
              </ul>

              <div className="mt-8">
                <TextLink href={DEMO_HREF}>
                  {segment.cta}
                  <ArrowRight className="size-3.5" aria-hidden />
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
    <Section tone="field" rhythm="loose" aria-label="Get started">
      <Reveal className="mx-auto max-w-3xl text-center">
        <h2 className="font-mkt-display text-mkt-d2 text-mkt-ink mx-auto mb-5 max-w-[18ch]">
          Bring your team the version of the truth it reports in.
        </h2>
        <p className="text-mkt-lead text-mkt-ink-soft mx-auto max-w-[52ch]">
          One observation field, five ways of reading it. We will walk through the one that matches
          how you are measured.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-2.5 sm:flex-row">
          <ButtonLink href={DEMO_HREF} className="w-full sm:w-auto">
            {DEMO_CTA}
            <ArrowRight className="size-3.5" aria-hidden />
          </ButtonLink>
          <ButtonLink href="/pricing" intent="secondary" className="w-full sm:w-auto">
            See pricing
          </ButtonLink>
        </div>
      </Reveal>
    </Section>
  );
}
