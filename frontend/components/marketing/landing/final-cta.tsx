import { ArrowRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';
import { DEMO_HREF } from '@/lib/marketing-content/nav';

import { ButtonLink } from '../primitives/button';
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
    <Section id="get-started" tone="paper" rhythm="base" aria-label="Get started">
      <Reveal className="bg-panel shadow-elevated mx-auto flex max-w-4xl flex-col items-center rounded-2xl p-8 text-center md:p-12">
        <div className="bg-accent-subtle/80 text-accent-text border-accent-border/80 inline-flex items-center gap-2 rounded-full border px-3.5 py-1 text-xs font-medium shadow-xs">
          <span className="bg-accent size-1.5 animate-pulse rounded-full" aria-hidden />
          <span>{cta.kicker}</span>
        </div>
        <h2 className="website-section-heading text-foreground mt-6 max-w-[24ch] text-balance">
          {cta.title}
        </h2>
        <p className="website-lead text-muted mt-4 max-w-[60ch]">{cta.body}</p>
        <div className="mt-8 flex flex-col justify-center gap-4 sm:flex-row sm:items-center">
          <ButtonLink
            href={DEMO_HREF}
            variant="primary"
            className="hover:shadow-card-hover w-full shadow-sm transition-shadow sm:w-auto"
          >
            {cta.primaryCta}
            <ArrowRight aria-hidden />
          </ButtonLink>
          <ButtonLink
            href="/pricing"
            variant="ghost"
            className="border-border/80 hover:bg-background-alt w-full border sm:w-auto"
          >
            {cta.secondaryCta}
          </ButtonLink>
        </div>
      </Reveal>
    </Section>
  );
}
