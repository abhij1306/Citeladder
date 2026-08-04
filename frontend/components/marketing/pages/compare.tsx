import { ArrowRight, Check } from 'lucide-react';
import Link from 'next/link';

import { COMPETITORS, FACT_ROWS, FAIRNESS_POINTS } from '@/lib/marketing-content/compare';
import { DEMO_CTA, DEMO_HREF } from '@/lib/marketing-content/nav';

import { ButtonLink } from '../primitives/button';
import { Meta } from '../primitives/label';
import { PageHero } from '../primitives/page-hero';
import { Section, SectionHeader } from '../primitives/section';
import { Reveal, StaggerGroup, StaggerItem } from '../primitives/reveal';

/**
 * `/compare` — the comparison index. Competitor cards render from the content
 * module; the "how we compare fairly" band exists because these pages make
 * claims about other people's products, so our own sourcing discipline
 * (deterministic, evidence-first, on the reader's own keys) is stated openly
 * on the page.
 */

export function CompareIndex() {
  return (
    <>
      <PageHero
        centered
        eyebrow="Comparisons"
        title="How CiteLadder"
        accent="compares."
        lead="Side-by-side notes on CiteLadder and four other AI visibility tools — what each covers, how scoring works, and where the evidence lives. Reviewed on 2026-08-01."
      />

      <Section tone="paper" rhythm="tight" aria-label="Competitors">
        <div className="border-border-subtle mb-8 flex items-center justify-between gap-5 border-b pb-5">
          <Meta as="p">Choose a tool</Meta>
          <Meta>{COMPETITORS.length} comparisons</Meta>
        </div>

        {COMPETITORS.length === 0 ? (
          <p className="border-border-subtle text-muted rounded-lg border border-dashed p-10 text-center text-sm">
            Comparison notes are published as each vendor review completes.
          </p>
        ) : (
          <StaggerGroup className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
            {COMPETITORS.map((competitor) => (
              <StaggerItem key={competitor.slug} className="h-full">
                <Link
                  href={`/compare/${competitor.slug}`}
                  className="bg-panel shadow-card hover:shadow-card-hover flex h-full flex-col rounded-lg p-8 transition-[box-shadow,transform] duration-200 hover:-translate-y-0.5"
                >
                  <span className="flex items-center gap-4">
                    <span
                      aria-hidden
                      className="border-border-subtle bg-panel text-foreground font-display grid size-10 place-items-center rounded-md border text-base font-semibold"
                    >
                      {competitor.name.charAt(0)}
                    </span>
                    <span className="text-foreground text-base font-semibold">
                      {competitor.name}
                    </span>
                  </span>
                  <span className="text-muted mt-5 block text-sm">{competitor.tagline}</span>
                  <span className="text-accent-text mt-auto flex items-center gap-3 pt-8 text-sm font-semibold">
                    CiteLadder vs {competitor.name}
                    <ArrowRight className="size-4" aria-hidden />
                  </span>
                </Link>
              </StaggerItem>
            ))}
          </StaggerGroup>
        )}
      </Section>

      <Section tone="sunken" rhythm="base" aria-labelledby="compare-fair-title">
        <SectionHeader
          eyebrow="How we compare fairly"
          title="Compared honestly, in the open."
          lead="Every competitor fact on these pages comes from the vendor's own public site, with the review date on the page."
          headingId="compare-fair-title"
        />
        <Reveal className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="bg-panel shadow-card rounded-lg p-8">
            <p className="text-muted max-w-[80ch] text-base">
              CiteLadder scores deterministically — explicit analyzer and scoring-rule versions ride
              with every projection, so every claim on these pages can be traced back to persisted
              evidence.
            </p>
            <ul className="mt-8 grid gap-4">
              {FAIRNESS_POINTS.map((point) => (
                <li key={point} className="text-muted flex gap-4 text-sm">
                  <Check
                    aria-hidden
                    strokeWidth={2.5}
                    className="text-success-text mt-2 size-4 shrink-0"
                  />
                  {point}
                </li>
              ))}
            </ul>
          </div>

          <div className="bg-background-alt shadow-card rounded-lg p-8">
            <Meta as="p" className="mb-5">
              CiteLadder at a glance
            </Meta>
            <dl className="grid gap-0">
              {FACT_ROWS.map((row) => (
                <div
                  key={row.key}
                  className="border-border-subtle grid grid-cols-[7rem_minmax(0,1fr)] gap-5 border-b py-4 last:border-b-0 last:pb-0"
                >
                  <dt className="text-muted text-sm">{row.key}</dt>
                  <dd className="text-foreground m-0 text-sm">{row.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </Reveal>
      </Section>

      <Section tone="paper" rhythm="base" aria-label="Get started">
        <Reveal className="mx-auto max-w-5xl text-center">
          <h2 className="font-display text-foreground mx-auto mb-5 max-w-[32ch] text-4xl">
            Don’t compare pages. Compare evidence.
          </h2>
          <p className="text-muted mx-auto max-w-[80ch] text-lg">
            Run the same prompts across ChatGPT, Gemini and Claude — and read the raw responses
            yourself.
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
