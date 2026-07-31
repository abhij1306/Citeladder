import { ArrowRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';
import { DEMO_HREF } from '@/lib/marketing-content/nav';

import { ButtonLink } from '../primitives/button';
import { Eyebrow } from '../primitives/label';
import { Section } from '../primitives/section';
import { Reveal } from '../primitives/reveal';

/**
 * The close. One big line and a single primary action, full width. Named as a
 * landmark region so the CTA is reachable directly from a screen-reader
 * landmark list rather than only by scrolling the page.
 */
export function FinalCta() {
  const { cta } = LANDING_CONTENT;
  return (
    <Section id="get-started" tone="field" rhythm="loose" aria-label="Get started">
      <Reveal className="mx-auto max-w-5xl">
        <Eyebrow>{cta.kicker}</Eyebrow>
        <h2 className="font-mkt-display text-mkt-d1 text-mkt-ink mt-6 max-w-[32ch]">{cta.title}</h2>
        <p className="text-mkt-lead text-mkt-ink-soft mt-6 max-w-[80ch]">{cta.body}</p>
        <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
          <ButtonLink href={DEMO_HREF} intent="primary" className="w-full sm:w-auto">
            {cta.primaryCta}
            <ArrowRight aria-hidden />
          </ButtonLink>
          <ButtonLink href="/pricing" intent="secondary" className="w-full sm:w-auto">
            {cta.secondaryCta}
          </ButtonLink>
        </div>
      </Reveal>
    </Section>
  );
}
