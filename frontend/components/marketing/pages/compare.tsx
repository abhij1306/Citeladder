import { ArrowRight, Check } from 'lucide-react';
import Link from 'next/link';

import { COMPETITORS, FACT_ROWS, FAIRNESS_POINTS } from '@/lib/marketing-content/compare';
import { DEMO_CTA, DEMO_HREF } from '@/lib/marketing-content/nav';

import { ButtonLink } from '../primitives/button';
import { Meta } from '../primitives/label';
import { PageHero } from '../primitives/page-hero';
import { Section } from '../primitives/section';
import { Reveal, StaggerGroup, StaggerItem } from '../primitives/reveal';

/**
 * `/compare` — comparison index. Competitor rows are a ledger, not a card
 * grid: name, one-line position, link. Fairness claims sit as a strip above a
 * compact glance table — no nested feature boxes.
 */

export function CompareIndex() {
  return (
    <>
      <PageHero
        centered
        eyebrow="Comparisons"
        title="How CiteLadder"
        accent="compares."
        lead="Side-by-side notes on engines, scoring, evidence and keys. Reviewed 2026-08-01."
      />

      <Section tone="paper" rhythm="tight" aria-label="Competitors">
        <div className="mb-5 flex items-center justify-between gap-4">
          <Meta as="p">Choose a tool</Meta>
          <Meta>{COMPETITORS.length} comparisons</Meta>
        </div>

        {COMPETITORS.length === 0 ? (
          <p className="website-body border-border-subtle text-muted rounded-lg border border-dashed p-8 text-center">
            Comparison notes publish as each vendor review completes.
          </p>
        ) : (
          <StaggerGroup className="border-border-subtle divide-border-subtle bg-panel divide-y overflow-hidden rounded-[var(--radius-card)] border">
            {COMPETITORS.map((competitor) => (
              <StaggerItem key={competitor.slug}>
                <Link
                  href={`/compare/${competitor.slug}`}
                  className="hover:bg-accent-soft group flex items-center gap-5 px-5 py-4 transition-colors duration-200 md:px-6 md:py-5"
                >
                  <span
                    aria-hidden
                    className="bg-accent-soft text-accent-text font-display grid size-9 shrink-0 place-items-center rounded-md text-sm font-medium"
                  >
                    {competitor.name.charAt(0)}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="text-foreground block text-base font-medium">
                      {competitor.name}
                    </span>
                    <span className="text-muted mt-1 block text-sm">{competitor.tagline}</span>
                  </span>
                  <span className="text-accent-text hidden items-center gap-2 text-sm font-medium sm:inline-flex">
                    vs {competitor.name}
                    <ArrowRight
                      className="size-4 transition-transform duration-200 group-hover:translate-x-0.5"
                      aria-hidden
                    />
                  </span>
                  <ArrowRight className="text-accent-text size-4 shrink-0 sm:hidden" aria-hidden />
                </Link>
              </StaggerItem>
            ))}
          </StaggerGroup>
        )}
      </Section>

      <Section tone="sunken" rhythm="tight" aria-labelledby="compare-fair-title">
        <Reveal className="mb-6 max-w-3xl">
          <h2 id="compare-fair-title" className="website-section-heading text-foreground">
            Compared honestly.
          </h2>
          <p className="website-body-lg text-muted mt-3">
            Competitor facts come from each vendor’s public site. Ours come from this codebase.
          </p>
        </Reveal>

        <ul className="mb-8 grid gap-3 md:grid-cols-3">
          {FAIRNESS_POINTS.map((point) => (
            <li
              key={point}
              className="text-foreground md:border-border-subtle flex gap-3 text-sm font-medium md:block md:border-l md:pl-4"
            >
              <Check
                aria-hidden
                strokeWidth={2.5}
                className="text-accent-text mt-0.5 size-4 shrink-0 md:mt-0 md:mb-2"
              />
              <span className="text-muted font-normal md:block">{point}</span>
            </li>
          ))}
        </ul>

        <Reveal>
          <Meta as="p" className="mb-3">
            At a glance
          </Meta>
          <dl className="border-border-subtle divide-border-subtle grid divide-y border-t sm:grid-cols-2 sm:gap-x-8 sm:divide-y-0">
            {FACT_ROWS.map((row) => (
              <div
                key={row.key}
                className="sm:border-border-subtle grid grid-cols-[7rem_minmax(0,1fr)] gap-3 py-3 sm:border-t"
              >
                <dt className="text-muted text-sm">{row.key}</dt>
                <dd className="text-foreground m-0 text-sm">{row.value}</dd>
              </div>
            ))}
          </dl>
        </Reveal>
      </Section>

      <Section tone="paper" rhythm="base" aria-label="Get started">
        <Reveal className="mx-auto max-w-3xl text-center">
          <h2 className="website-section-heading text-foreground mx-auto mb-3 max-w-[28ch]">
            Don’t compare pages. Compare evidence.
          </h2>
          <p className="website-body-lg text-muted mx-auto max-w-[56ch]">
            Same prompts across ChatGPT, Gemini and Claude — raw responses included.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <ButtonLink href={DEMO_HREF} className="w-full sm:w-auto">
              {DEMO_CTA}
              <ArrowRight aria-hidden />
            </ButtonLink>
            <ButtonLink href="/faq" variant="ghost" className="w-full sm:w-auto">
              Read the FAQ
            </ButtonLink>
          </div>
        </Reveal>
      </Section>
    </>
  );
}
