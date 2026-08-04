import { ArrowRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';
import { DEMO_HREF } from '@/lib/marketing-content/nav';

import { ButtonLink } from '../primitives/button';
import { Eyebrow } from '../primitives/label';
import { Container } from '../primitives/section';
import { HeroEntrance } from './hero-entrance';
import { RotatingEngineLogos } from './rotating-engine-logos';
import { BrandAtmosphere } from '@/components/ui/brand-atmosphere';

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
    <header className="citeladder-field-hero citeladder-grid-field relative -mt-16 overflow-hidden pt-16">
      <BrandAtmosphere variant="hero" />
      <Container className="relative z-1 pt-20 pb-16 md:pt-28 md:pb-20">
        <HeroEntrance className="mx-auto max-w-5xl text-center">
          <div className="flex justify-center">
            <Eyebrow>{hook.eyebrow}</Eyebrow>
          </div>
          <h1 className="font-display text-foreground mx-auto mt-8 max-w-[32ch] text-5xl text-balance">
            {hook.title} <em className="text-accent-text not-italic">{hook.titleAccent}</em>
          </h1>
          <p className="text-muted mx-auto mt-8 max-w-[80ch] text-lg">{hook.body}</p>
          <div className="mt-8 flex flex-col justify-center gap-4 sm:flex-row sm:items-center">
            <ButtonLink href={DEMO_HREF} variant="primary" className="w-full sm:w-auto">
              {hook.primaryCta}
              <ArrowRight aria-hidden />
            </ButtonLink>
            <ButtonLink href="#how-it-works" variant="ghost" className="w-full sm:w-auto">
              {hook.secondaryCta}
            </ButtonLink>
          </div>
          <RotatingEngineLogos className="mx-auto mt-10 max-w-2xl" />
        </HeroEntrance>
      </Container>
    </header>
  );
}
