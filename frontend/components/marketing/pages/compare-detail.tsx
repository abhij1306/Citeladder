import { ArrowLeft, ArrowRight, Info } from 'lucide-react';
import Link from 'next/link';

import type { Competitor } from '@/lib/marketing-content/compare';
import { DEMO_CTA, DEMO_HREF } from '@/lib/marketing-content/nav';

import { Badge } from '../primitives/badge';
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
 * Honest framing: the Searchify column is real copy grounded in this repo's
 * source code; a competitor cell renders only owner-verified facts, and every
 * unverified cell says so explicitly via <UnverifiedCell /> — the page would
 * rather show a gap than a guess. h2–h6 may not contain the product name
 * (heading-query convention).
 */

/** The fixed unverified state — takes no string from the content module. */
function UnverifiedCell() {
  return (
    <span className="border-mkt-line text-mkt-ink-muted text-mkt-sm inline-block rounded-sm border border-dashed px-2 py-1">
      Not verified by us
    </span>
  );
}

export function CompareDetailView({ competitor }: Readonly<{ competitor: Competitor }>) {
  return (
    <>
      <header className="pt-16 pb-12 md:pt-24 md:pb-16">
        <Container>
          <Reveal className="max-w-5xl">
            <Link
              href="/compare"
              className="text-mkt-sm text-mkt-ink-muted hover:text-mkt-ink mb-8 inline-flex items-center gap-2 font-semibold transition-colors"
            >
              <ArrowLeft className="size-4" aria-hidden />
              All comparisons
            </Link>
            <div>
              <Eyebrow>Comparison</Eyebrow>
            </div>
            <h1 className="font-mkt-display text-mkt-d1 text-mkt-ink mt-6 mb-6 max-w-[32ch]">
              Searchify vs <em className="mkt-keyword not-italic">{competitor.name}.</em>
            </h1>
            <p className="text-mkt-lead text-mkt-ink-soft max-w-[80ch]">
              Two ways to measure brand presence in AI answers. The Searchify column comes straight
              from our docs and source code; the {competitor.name} column stays marked until we
              verify each row.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              {competitor.tagline && <Badge>{competitor.tagline}</Badge>}
              {competitor.lastReviewed ? (
                <Badge>Last reviewed · {competitor.lastReviewed}</Badge>
              ) : (
                <Badge tone="warn">Not independently verified</Badge>
              )}
            </div>
          </Reveal>
        </Container>
      </header>

      <Section tone="surface" rhythm="tight" aria-label="Quick facts">
        <div className="border-mkt-line-soft mb-6 flex flex-wrap items-center justify-between gap-3 border-b pb-4">
          <Meta as="p">Quick facts</Meta>
          <Meta>Searchify column sourced from our source code</Meta>
        </div>
        <Reveal className="rounded-mkt-lg bg-mkt-surface shadow-card overflow-hidden">
          {/* Wider than a phone: scrolls inside its own box so the page body
              never scrolls sideways. */}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[44rem] border-collapse text-left align-top">
              <thead>
                <tr className="border-mkt-line-soft bg-mkt-paper-raised border-b">
                  <th scope="col" className="text-mkt-meta text-mkt-ink-muted p-4 uppercase">
                    Dimension
                  </th>
                  <th scope="col" className="text-mkt-meta text-mkt-proof p-4 uppercase">
                    Searchify
                  </th>
                  <th scope="col" className="text-mkt-meta text-mkt-ink-muted p-4 uppercase">
                    {competitor.name}
                  </th>
                </tr>
              </thead>
              <tbody>
                {competitor.rows.map((row) => (
                  <tr key={row.dimension} className="border-mkt-line-soft border-b last:border-b-0">
                    <td className="text-mkt-sm text-mkt-ink w-52 p-4 align-top font-semibold">
                      {row.dimension}
                    </td>
                    <td className="text-mkt-sm text-mkt-ink-soft p-4 align-top">{row.searchify}</td>
                    <td className="text-mkt-sm text-mkt-ink-soft p-4 align-top">
                      {row.competitor ? row.competitor : <UnverifiedCell />}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Reveal>

        <p className="border-mkt-amber-line bg-mkt-amber-soft text-mkt-sm text-mkt-ink-soft rounded-mkt-sm mt-4 flex gap-3 border p-4">
          <Info
            aria-hidden
            strokeWidth={1.9}
            className="text-mkt-amber-text mt-0.5 size-4 shrink-0"
          />
          {competitor.verified ? (
            <span>
              This comparison is maintained by the Searchify team. Last reviewed{' '}
              {competitor.lastReviewed}. Vendor capabilities change; re-check before quoting.
            </span>
          ) : (
            <span>
              This comparison is maintained by the Searchify team. We have not independently
              verified this vendor’s current capabilities. The Searchify column is grounded in our
              own source code; the {competitor.name} column stays blank until we check each row
              first-party — we would rather show a gap than a guess.
            </span>
          )}
        </p>
      </Section>

      {/* The verdict block renders only from an owner-supplied verdict — no
          narrative slots, no instruction text. */}
      {competitor.verdict && (
        <Section tone="paper" aria-label="Our verdict">
          <div className="max-w-[90ch]">
            <h2 className="font-mkt-display text-mkt-d4 text-mkt-ink">Our verdict.</h2>
            <p className="text-mkt-body text-mkt-ink-soft mt-4">{competitor.verdict}</p>
          </div>
        </Section>
      )}

      <Section tone="field" rhythm="loose" aria-label="Get started">
        <Reveal className="mx-auto max-w-5xl text-center">
          <h2 className="font-mkt-display text-mkt-d2 text-mkt-ink mx-auto mb-5 max-w-[32ch]">
            See your own numbers instead.
          </h2>
          <p className="text-mkt-lead text-mkt-ink-soft mx-auto max-w-[80ch]">
            Walk through your category with us — your prompts, your competitors, the raw answers
            behind every score.
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
