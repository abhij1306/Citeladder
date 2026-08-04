import { ArrowLeft, ArrowRight, Info } from 'lucide-react';
import Link from 'next/link';

import type { Competitor } from '@/lib/marketing-content/compare';
import { DEMO_CTA, DEMO_HREF } from '@/lib/marketing-content/nav';

import { Badge } from '@/components/ui/badge';
import { ButtonLink } from '../primitives/button';
import { Eyebrow, Meta } from '../primitives/label';
import { Container, Section } from '../primitives/section';
import { Reveal } from '../primitives/reveal';

/**
 * `/compare/[competitor]` view. The route's default export is a thin async
 * wrapper (Next 16 `params` is a Promise); it resolves the slug and hands the
 * content-module entry here, so this view stays sync and tests render it
 * directly.
 *
 * Every row ships with both cells written (see the module's sourcing rule);
 * the editorial blocks are the verdict and an honest "where {name} fits
 * better". h2–h6 may not contain the product name (heading-query
 * convention) — the better-fit heading below uses the competitor's name, not
 * ours.
 */

export function CompareDetailView({ competitor }: Readonly<{ competitor: Competitor }>) {
  return (
    <>
      <header className="pt-16 pb-12 md:pt-30 md:pb-16">
        <Container>
          <Reveal className="max-w-5xl">
            <Link
              href="/compare"
              className="text-muted hover:text-foreground mb-8 inline-flex items-center gap-3 text-sm font-semibold transition-colors"
            >
              <ArrowLeft className="size-4" aria-hidden />
              All comparisons
            </Link>
            <div>
              <Eyebrow>Comparison</Eyebrow>
            </div>
            <h1 className="font-display text-foreground mt-8 mb-8 max-w-[32ch] text-5xl">
              CiteLadder vs <em className="citeladder-keyword not-italic">{competitor.name}.</em>
            </h1>
            <p className="text-muted max-w-[80ch] text-lg">
              Two ways to measure brand presence in AI answers — engine coverage, how scoring works,
              and where the evidence lives.
            </p>
            <div className="mt-8 flex flex-wrap gap-4">
              <Badge>{competitor.tagline}</Badge>
              <Badge>Last reviewed · {competitor.lastReviewed}</Badge>
            </div>
          </Reveal>
        </Container>
      </header>

      <Section tone="paper" rhythm="tight" aria-label="Quick facts">
        <div className="border-border-subtle mb-8 flex flex-wrap items-center justify-between gap-4 border-b pb-5">
          <Meta as="p">Quick facts</Meta>
          <Meta>CiteLadder column sourced from our source code</Meta>
        </div>
        <Reveal className="bg-panel shadow-card overflow-hidden rounded-lg">
          {/* Wider than a phone: scrolls inside its own box so the page body
              never scrolls sideways. */}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[44rem] border-collapse text-left align-top">
              <thead>
                <tr className="border-border-subtle bg-background-alt border-b">
                  <th scope="col" className="text-muted p-5 text-xs uppercase">
                    Dimension
                  </th>
                  <th scope="col" className="text-accent-text p-5 text-xs uppercase">
                    CiteLadder
                  </th>
                  <th scope="col" className="text-muted p-5 text-xs uppercase">
                    {competitor.name}
                  </th>
                </tr>
              </thead>
              <tbody>
                {competitor.rows.map((row) => (
                  <tr key={row.dimension} className="border-border-subtle border-b last:border-b-0">
                    <td className="text-foreground w-52 p-5 align-top text-sm font-semibold">
                      {row.dimension}
                    </td>
                    <td className="text-muted p-5 align-top text-sm">{row.citeladder}</td>
                    <td className="text-muted p-5 align-top text-sm">{row.competitor}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Reveal>

        <p className="border-warning-border bg-warning-bg text-muted mt-5 flex gap-4 rounded-md border p-5 text-sm">
          <Info aria-hidden strokeWidth={1.9} className="text-warning-text mt-2 size-4 shrink-0" />
          <span>
            Maintained by the CiteLadder team from each vendor’s public pages. Last reviewed{' '}
            {competitor.lastReviewed}. Vendor capabilities change — re-check before quoting.
          </span>
        </p>
      </Section>

      <Section tone="paper" aria-label="Verdict and fit">
        <Reveal className="grid gap-5 lg:grid-cols-2">
          <div className="bg-panel shadow-card rounded-lg p-8">
            <h2 className="font-display text-foreground text-2xl">Our verdict.</h2>
            <p className="text-muted mt-5 text-base">{competitor.verdict}</p>
          </div>
          <div className="bg-background-alt shadow-card rounded-lg p-8">
            <h2 className="font-display text-foreground text-2xl">
              Where {competitor.name} fits better.
            </h2>
            <p className="text-muted mt-5 text-base">{competitor.betterFit}</p>
          </div>
        </Reveal>
      </Section>

      <Section tone="paper" rhythm="base" aria-label="Get started">
        <Reveal className="mx-auto max-w-5xl text-center">
          <h2 className="font-display text-foreground mx-auto mb-5 max-w-[32ch] text-4xl">
            See your own numbers instead.
          </h2>
          <p className="text-muted mx-auto max-w-[80ch] text-lg">
            Walk through your category with us — your prompts, your competitors, the raw answers
            behind every score.
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
