import { ArrowRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';
import { DEMO_HREF } from '@/lib/marketing-content/nav';

import { ButtonLink } from '../primitives/button';
import { Eyebrow } from '../primitives/label';
import { Container } from '../primitives/section';
import { HeroAtmosphere } from './hero-atmosphere';
import { HeroEntrance } from './hero-entrance';
import { HeadlineRotatingWord } from './headline-rotating-word';
import { RotatingEngineLogos } from './rotating-engine-logos';

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
    <header className="mkt-field-hero mkt-grid-field -mt-mkt-nav pt-mkt-nav relative overflow-hidden">
      <HeroAtmosphere />
      <Container className="relative z-1 pt-20 pb-16 md:pt-28 md:pb-20">
        <HeroEntrance className="mx-auto max-w-5xl text-center">
          <div className="flex justify-center">
            <Eyebrow>{hook.eyebrow}</Eyebrow>
          </div>
          <h1 className="font-mkt-display text-mkt-d1 text-mkt-ink mx-auto mt-6 max-w-[32ch] text-balance">
            {hook.title}{' '}
            <em className="mkt-keyword not-italic">
              They ask <HeadlineRotatingWord /> instead.
            </em>
          </h1>
          <p className="text-mkt-lead text-mkt-ink-soft mx-auto mt-6 max-w-[80ch]">{hook.body}</p>
          <div className="mt-8 flex flex-col justify-center gap-3 sm:flex-row sm:items-center">
            <ButtonLink href={DEMO_HREF} intent="glass" size="lg" className="w-full sm:w-auto">
              {hook.primaryCta}
              <ArrowRight aria-hidden />
            </ButtonLink>
            <ButtonLink
              href="#how-it-works"
              intent="secondary"
              size="lg"
              className="w-full px-8 sm:w-auto"
            >
              {hook.secondaryCta}
            </ButtonLink>
          </div>
          <RotatingEngineLogos className="mt-8 md:mt-10" />
        </HeroEntrance>
      </Container>
    </header>
  );
}
