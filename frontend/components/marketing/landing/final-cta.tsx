import { ArrowRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';
import { DEMO_CTA, DEMO_HREF } from '@/lib/marketing-content/nav';

import { ButtonLink } from '../primitives/button';
import { Eyebrow } from '../primitives/label';
import { Section } from '../primitives/section';
import { Reveal } from '../primitives/reveal';

/**
 * Closing band. Named as a landmark region so the CTA is reachable directly
 * from a screen-reader landmark list rather than only by scrolling the page.
 */
export function FinalCta() {
  const { finalCta } = LANDING_CONTENT;
  return (
    <Section rhythm="loose" divided aria-label="Get started">
      <Reveal className="mx-auto max-w-3xl text-center">
        <Eyebrow>{finalCta.kicker}</Eyebrow>
        <h2 className="font-mkt-display text-mkt-d2 text-mkt-ink mkt-display-w mx-auto mt-6 mb-5 max-w-[18ch]">
          {finalCta.title}
        </h2>
        <p className="text-mkt-lead text-mkt-ink-soft mx-auto max-w-[52ch]">{finalCta.body}</p>
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
