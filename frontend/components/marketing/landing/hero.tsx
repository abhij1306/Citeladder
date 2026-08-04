import { ArrowRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';
import { DEMO_HREF } from '@/lib/marketing-content/nav';

import { ButtonLink, IconButtonLink } from '../primitives/button';
import { Eyebrow } from '../primitives/label';
import { Container } from '../primitives/section';
import { HeroEntrance } from './hero-entrance';
import { RotatingEngineLogos } from './rotating-engine-logos';
import { BrandAtmosphere } from '@/components/ui/brand-atmosphere';

/**
 * The hook — a centred opener standing on the atmospheric field.
 *
 * This was a two-column split: copy left, panel right, on flat cream. It read
 * as dull for a structural reason, not a motion one — the first screen had no
 * colour, no depth and a hard 26rem ceiling on the headline, so the biggest
 * type on the site was boxed into half the viewport while the other half held
 * a single white card. Centring the claim lets the display step actually be a
 * display step, and the field behind it gives the screen light to sit in.
 *
 * The ambient panel now sits BELOW the claim rather than beside it, where it
 * reads as the product moment the headline just promised. It stays
 * decorative-by-construction; the labelled product canvas is further down the
 * page. No fake screenshots: the panel shows the same illustrative questions
 * the rest of the page uses and never claims to be a real result.
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
            <IconButtonLink
              href={DEMO_HREF}
              title={hook.primaryCta}
              icon={<ArrowRight aria-hidden />}
              className="self-center"
            />
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
