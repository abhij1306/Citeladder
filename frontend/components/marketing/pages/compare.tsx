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
 * claims about other people's products, and the honest-framing rule (every
 * unverified cell stays blank and says so) has to be visible to the reader,
 * not just enforced in the data.
 */

export function CompareIndex() {
  return (
    <>
      <PageHero
        centered
        eyebrow="Comparisons"
        title="How Searchify"
        accent="compares."
        lead="Side-by-side notes on Searchify and other AI visibility tools — what each covers, how scoring works, and where the evidence lives. Maintained by the Searchify team, marked wherever we still need to verify."
      />

      <Section tone="surface" rhythm="tight" aria-label="Competitors">
        <div className="border-mkt-line-soft mb-6 flex items-center justify-between gap-4 border-b pb-4">
          <Meta as="p">Choose a tool</Meta>
          <Meta>{COMPETITORS.length} comparisons</Meta>
        </div>

        {COMPETITORS.length === 0 ? (
          <p className="border-mkt-line rounded-mkt-lg text-mkt-sm text-mkt-ink-muted border border-dashed p-10 text-center">
            Comparison research is in progress. We publish pages only after every claim is verified.
          </p>
        ) : (
          <StaggerGroup className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {COMPETITORS.map((competitor) => (
              <StaggerItem key={competitor.slug} className="h-full">
                <Link
                  href={`/compare/${competitor.slug}`}
                  className="bg-mkt-surface rounded-mkt-lg shadow-card hover:shadow-card-hover flex h-full flex-col p-6 transition-[box-shadow,transform] duration-200 hover:-translate-y-0.5"
                >
                  <span className="flex items-center gap-3">
                    <span
                      aria-hidden
                      className="border-mkt-line bg-mkt-surface text-mkt-ink font-mkt-display text-mkt-body grid size-10 place-items-center rounded-sm border font-bold"
                    >
                      {competitor.name.charAt(0)}
                    </span>
                    <span className="text-mkt-body text-mkt-ink font-semibold">
                      {competitor.name}
                    </span>
                  </span>
                  {competitor.tagline && (
                    <span className="text-mkt-sm text-mkt-ink-muted mt-4 block">
                      {competitor.tagline}
                    </span>
                  )}
                  <span className="text-mkt-sm text-mkt-proof mt-auto flex items-center gap-2 pt-6 font-semibold">
                    Searchify vs {competitor.name}
                    <ArrowRight className="size-4" aria-hidden />
                  </span>
                </Link>
              </StaggerItem>
            ))}
          </StaggerGroup>
        )}
      </Section>

      <Section tone="sunken" rhythm="loose" aria-labelledby="compare-fair-title">
        <SectionHeader
          kicker="How we compare fairly"
          title="Compared honestly, in the open."
          intro="Where a competitor fact is not verified first-party, the cell stays blank and says so."
          headingId="compare-fair-title"
        />
        <Reveal className="grid gap-4 lg:grid-cols-[1.1fr_0.9fr]">
          <div className="rounded-mkt-lg bg-mkt-surface shadow-card p-8">
            <p className="text-mkt-body text-mkt-ink-soft max-w-[80ch]">
              Searchify scores deterministically — explicit analyzer and scoring-rule versions ride
              with every projection, so every claim on these pages can be traced back to persisted
              evidence.
            </p>
            <ul className="mt-6 grid gap-3">
              {FAIRNESS_POINTS.map((point) => (
                <li key={point} className="text-mkt-sm text-mkt-ink-soft flex gap-3">
                  <Check
                    aria-hidden
                    strokeWidth={2.5}
                    className="text-mkt-evidence-text mt-0.5 size-4 shrink-0"
                  />
                  {point}
                </li>
              ))}
            </ul>
          </div>

          <div className="rounded-mkt-lg bg-mkt-paper-raised shadow-card p-8">
            <Meta as="p" className="mb-5">
              Searchify at a glance
            </Meta>
            <dl className="grid gap-0">
              {FACT_ROWS.map((row) => (
                <div
                  key={row.key}
                  className="border-mkt-line-soft grid grid-cols-[7rem_minmax(0,1fr)] gap-4 border-b py-3 last:border-b-0 last:pb-0"
                >
                  <dt className="text-mkt-sm text-mkt-ink-muted">{row.key}</dt>
                  <dd className="text-mkt-sm text-mkt-ink m-0">{row.value}</dd>
                </div>
              ))}
            </dl>
          </div>
        </Reveal>
      </Section>

      <Section tone="field" rhythm="loose" aria-label="Get started">
        <Reveal className="mx-auto max-w-5xl text-center">
          <h2 className="font-mkt-display text-mkt-d2 text-mkt-ink mx-auto mb-5 max-w-[32ch]">
            Don’t compare pages. Compare evidence.
          </h2>
          <p className="text-mkt-lead text-mkt-ink-soft mx-auto max-w-[80ch]">
            Run the same prompts across ChatGPT, Gemini and Claude — and read the raw responses
            yourself.
          </p>
          <div className="mt-8 flex flex-col items-center justify-center gap-3 sm:flex-row">
            <ButtonLink href={DEMO_HREF} className="w-full sm:w-auto">
              {DEMO_CTA}
              <ArrowRight aria-hidden />
            </ButtonLink>
            <ButtonLink href="/faq" intent="secondary" className="w-full sm:w-auto">
              Read the FAQ
            </ButtonLink>
          </div>
        </Reveal>
      </Section>
    </>
  );
}
