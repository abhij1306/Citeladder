import { ArrowRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { Reveal } from '../primitives/reveal';
import { Section, SectionHeader } from '../primitives/section';

/**
 * Evidence and provenance (§8.2) — the chain artifact → fact → insight → brief
 * → verification, beside a real insight object.
 *
 * Two reasons this section exists. The chain is the claim competitors cannot
 * copy and it was previously only implied by the page. The insight card is the
 * product's most recognisable artifact, and one real example is stronger proof
 * than another feature list.
 *
 * The card mirrors the anatomy of `components/intelligence/insight.tsx` rather
 * than importing it: that component takes a server-backed `InsightModel` with a
 * resolvable evidence href and refuses to render without one, which is exactly
 * right in the app and wrong on a static marketing page. Marketing also stays
 * monochrome-plus-blue, so the priority chip here is not the app's danger fill.
 */
export function EvidenceChain() {
  const { evidence } = LANDING_CONTENT;

  return (
    <Section id="evidence" tone="paper" rhythm="base" aria-labelledby="evidence-title">
      <SectionHeader
        eyebrow={evidence.kicker}
        title={evidence.title}
        lead={evidence.lead}
        headingId="evidence-title"
      />

      <div className="grid gap-10 xl:grid-cols-[1.1fr_0.9fr] xl:items-start xl:gap-12">
        {/* The chain, as an ordered list — the order is the substance, so it
            is a real <ol> rather than a stack of divs. The stagger primitives
            render fixed divs, so the reveal attribute is applied directly here
            rather than widening a shared primitive for one section. */}
        <ol data-citeladder-reveal="stagger" className="flex flex-col gap-3">
          {evidence.chain.map((link, index) => (
            <li
              key={link.step}
              className="border-border-subtle bg-panel shadow-card flex items-start gap-4 rounded-lg border p-4"
            >
              <span className="text-subtle mt-0.5 font-mono text-xs tabular-nums">
                {String(index + 1).padStart(2, '0')}
              </span>
              <div className="min-w-0">
                <p className="text-foreground text-sm font-semibold">{link.step}</p>
                <p className="text-muted mt-1 text-sm leading-relaxed">{link.detail}</p>
              </div>
              {index < evidence.chain.length - 1 ? (
                <ArrowRight aria-hidden className="text-subtle mt-0.5 size-4 shrink-0" />
              ) : null}
            </li>
          ))}
        </ol>

        {/* A real insight object, in the shared anatomy. */}
        <Reveal className="xl:sticky xl:top-24">
          <p className="text-subtle text-2xs mb-3 font-medium tracking-wide uppercase">
            What that produces
          </p>
          <article className="border-border bg-panel shadow-card flex flex-col gap-4 rounded-lg border p-5">
            <div className="flex items-center justify-between gap-3">
              <span className="bg-accent-subtle text-accent-text text-2xs inline-flex items-center rounded-sm px-1.5 py-0.5 font-medium tracking-wide uppercase">
                {evidence.sample.priority}
              </span>
              <span className="text-subtle text-2xs font-medium tracking-wide uppercase">
                {evidence.sample.layer}
              </span>
            </div>

            <h3 className="font-display text-foreground text-base leading-snug text-balance">
              {evidence.sample.claim}
            </h3>

            <div className="flex flex-col gap-1">
              <p className="text-subtle text-2xs font-medium tracking-wide uppercase">Evidence</p>
              <p className="text-accent-text text-xs font-medium">
                {evidence.sample.evidenceLabel}
              </p>
            </div>

            <div className="flex flex-col gap-1">
              <p className="text-subtle text-2xs font-medium tracking-wide uppercase">
                Why this matters
              </p>
              <p className="text-muted text-xs leading-relaxed">{evidence.sample.why}</p>
            </div>

            <div className="border-border-subtle flex items-center justify-between border-t pt-3">
              <span className="text-subtle text-2xs font-medium tracking-wide uppercase">
                Potential impact
              </span>
              <span className="text-foreground text-xs font-semibold">
                {evidence.sample.impact}
              </span>
            </div>

            <span className="text-subtle bg-well text-2xs w-fit rounded-sm px-1.5 py-0.5 font-medium tabular-nums">
              {evidence.sample.provenance}
            </span>
          </article>
        </Reveal>
      </div>
    </Section>
  );
}
