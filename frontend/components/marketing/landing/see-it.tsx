import { ArrowRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';
import { DEMO_HREF } from '@/lib/marketing-content/nav';

import { ButtonLink } from '../primitives/button';
import { Reveal } from '../primitives/reveal';
import { ProductWindow } from '../scenes/product-window';
import { Section } from '../primitives/section';

/**
 * The scroll-driving beat: the product itself.
 *
 * This section used to render a second question→verdicts demo, which repeated
 * the hero's ambient panel almost exactly — the page asked the same question
 * twice and answered it the same way, so the scroll bought the reader nothing.
 * The hero states the PROBLEM (engines answer without you); this states the
 * ANSWER, and the answer is the product: a real workspace canvas with one
 * metric opened to the persisted artifact behind it.
 */
export function SeeIt() {
  const { seeIt } = LANDING_CONTENT;
  return (
    <Section id="see-it" tone="paper" rhythm="base" aria-labelledby="see-it-title">
      <Reveal className="mx-auto mb-8 max-w-5xl text-center md:mb-10">
        <p className="text-accent-text font-mono text-xs uppercase">{seeIt.kicker}</p>
        {/* No weight or tracking class here: the `text-4xl` rung owns both,
            and check-frontend-architecture fails the build if markup overrides
            them (the whole reason heading weight stays uniform site-wide). */}
        <h2 id="see-it-title" className="font-display text-foreground mt-3 text-4xl">
          {seeIt.title}
        </h2>
      </Reveal>
      <Reveal>
        <ProductWindow />
      </Reveal>
      <div className="mt-10 flex justify-center">
        <ButtonLink href={DEMO_HREF} variant="primary" className="w-full sm:w-auto">
          {seeIt.cta}
          <ArrowRight aria-hidden />
        </ButtonLink>
      </div>
    </Section>
  );
}
