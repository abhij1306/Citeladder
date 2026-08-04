import { ArrowLeft, ArrowRight } from 'lucide-react';
import Link from 'next/link';

import type { Competitor } from '@/lib/marketing-content/compare';
import { DEMO_CTA, DEMO_HREF } from '@/lib/marketing-content/nav';
import { cn } from '@/lib/utils';

import { ButtonLink } from '../primitives/button';
import { Eyebrow } from '../primitives/label';
import { Container, Section } from '../primitives/section';
import { Reveal } from '../primitives/reveal';

/**
 * `/compare/[competitor]` — compact header straight into the table. Editorial
 * blocks stay honest (verdict + better-fit) but short. h2–h6 must not contain
 * the product name; the better-fit heading uses the competitor's name only.
 */

export function CompareDetailView({ competitor }: Readonly<{ competitor: Competitor }>) {
  return (
    <>
      <header className="border-border-subtle border-b pt-16 pb-6 md:pb-8">
        <Container dense>
          <Reveal className="max-w-5xl">
            <Link
              href="/compare"
              className="text-muted hover:text-foreground mb-5 inline-flex items-center gap-2 text-sm font-semibold transition-colors"
            >
              <ArrowLeft className="size-4" aria-hidden />
              All comparisons
            </Link>
            <Eyebrow>Comparison · {competitor.lastReviewed}</Eyebrow>
            <h1 className="font-display text-foreground mt-4 max-w-[28ch] text-4xl text-balance md:text-5xl">
              CiteLadder vs <em className="text-accent-text not-italic">{competitor.name}</em>
            </h1>
            <p className="text-muted mt-3 max-w-[56ch] text-base">{competitor.tagline}</p>
          </Reveal>
        </Container>
      </header>

      <Section tone="paper" rhythm="tight" aria-label="Quick facts" dense>
        <Reveal className="border-border-subtle bg-panel shadow-card overflow-hidden rounded-lg border">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] border-collapse text-left">
              <thead>
                <tr className="border-border-subtle bg-background-alt border-b">
                  <th
                    scope="col"
                    className="text-muted px-4 py-3 text-xs font-semibold tracking-wide uppercase"
                  >
                    Dimension
                  </th>
                  <th
                    scope="col"
                    className="text-accent-text px-4 py-3 text-xs font-semibold tracking-wide uppercase"
                  >
                    CiteLadder
                  </th>
                  <th
                    scope="col"
                    className="text-muted px-4 py-3 text-xs font-semibold tracking-wide uppercase"
                  >
                    {competitor.name}
                  </th>
                </tr>
              </thead>
              <tbody>
                {competitor.rows.map((row, index) => (
                  <tr
                    key={row.dimension}
                    className={cn(
                      'border-border-subtle border-b last:border-b-0',
                      index % 2 === 1 && 'bg-background-alt/60',
                    )}
                  >
                    <th
                      scope="row"
                      className={cn(
                        'text-foreground w-36 px-4 py-2.5 align-top text-sm font-semibold',
                        index % 2 === 1 ? 'bg-background-alt' : 'bg-panel',
                      )}
                    >
                      {row.dimension}
                    </th>
                    <td className="text-foreground px-4 py-2.5 align-top text-sm leading-snug">
                      {row.citeladder}
                    </td>
                    <td className="text-muted px-4 py-2.5 align-top text-sm leading-snug">
                      {row.competitor}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Reveal>
        <p className="text-subtle mt-3 text-xs">
          Maintained by the CiteLadder team from each vendor’s public pages. Last reviewed{' '}
          {competitor.lastReviewed}. Re-check before quoting.
        </p>
      </Section>

      <Section tone="sunken" rhythm="tight" aria-label="Verdict and fit">
        <Reveal className="grid gap-8 md:grid-cols-2 md:gap-10">
          <div>
            <h2 className="font-display text-foreground text-xl">Our verdict</h2>
            <p className="text-muted mt-3 text-sm leading-relaxed">{competitor.verdict}</p>
          </div>
          <div>
            <h2 className="font-display text-foreground text-xl">
              Where {competitor.name} fits better
            </h2>
            <p className="text-muted mt-3 text-sm leading-relaxed">{competitor.betterFit}</p>
          </div>
        </Reveal>
      </Section>

      <Section tone="paper" rhythm="base" aria-label="Get started">
        <Reveal className="mx-auto max-w-3xl text-center">
          <h2 className="font-display text-foreground mx-auto mb-3 max-w-[28ch] text-3xl">
            See your own numbers instead.
          </h2>
          <p className="text-muted mx-auto max-w-[52ch] text-base">
            Your category, your prompts — raw answers behind every score.
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
