import { ArrowRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';
import { DEMO_HREF } from '@/lib/marketing-content/nav';

import { ButtonLink } from '../primitives/button';
import { Container } from '../primitives/section';
import { HeroEntrance } from './hero-entrance';
import { RotatingEngineLogos } from './rotating-engine-logos';

/**
 * The hook — a centred opener standing on the atmospheric field.
 *
 * Primary CTA matches the shared demo funnel (`DEMO_CTA` / Book a demo) so the
 * first action on the page is the same action every other marketing surface
 * offers. Secondary scrolls to the operating loop.
 */
export function Hero() {
  const { hook } = LANDING_CONTENT;
  return (
    <header className="bg-background-alt relative -mt-16 overflow-hidden pt-16">
      <Container className="relative z-1 pt-20 pb-18 md:pt-32 md:pb-24">
        <HeroEntrance className="mx-auto w-full max-w-5xl text-center">
          <div className="flex justify-center">
            <div className="bg-accent-subtle text-accent-text border-accent-border inline-flex items-center gap-2 rounded-full border px-3.5 py-1 text-xs font-medium">
              <span className="bg-accent size-1.5 rounded-full" aria-hidden />
              <span>{hook.eyebrow}</span>
            </div>
          </div>
          <h1 className="website-hero-display text-foreground mx-auto mt-6 max-w-[24ch] text-center text-balance">
            {hook.title}{' '}
            <em className="text-accent-text font-medium not-italic">{hook.titleAccent}</em>
          </h1>
          <p className="website-lead text-muted mx-auto mt-6 max-w-[64ch] text-center">
            {hook.body}
          </p>
          <div className="mt-8 flex flex-col justify-center gap-4 sm:flex-row sm:items-center">
            <ButtonLink href={DEMO_HREF} variant="primary" className="w-full sm:w-auto">
              {hook.primaryCta}
              <ArrowRight aria-hidden />
            </ButtonLink>
            <ButtonLink
              href="#how-it-works"
              variant="ghost"
              className="border-border/80 hover:bg-background-alt w-full border sm:w-auto"
            >
              {hook.secondaryCta}
            </ButtonLink>
          </div>
          <RotatingEngineLogos className="mx-auto mt-10 max-w-2xl" />
        </HeroEntrance>
      </Container>
    </header>
  );
}
