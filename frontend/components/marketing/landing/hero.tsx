import { ArrowRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';
import { DEMO_CTA, DEMO_HREF } from '@/lib/marketing-content/nav';

import { ButtonLink } from '../primitives/button';
import { ALL_ENGINES, EngineWordmark } from '../primitives/engine-chip';
import { Eyebrow } from '../primitives/label';
import { Marquee } from '../primitives/marquee';
import { Container } from '../primitives/section';
import { Reveal } from '../primitives/reveal';

/**
 * A centred text opener that deliberately stops short of the fold: the copy
 * takes the upper band, and the two counter-moving strips fill the space that
 * was previously empty at the bottom of the first screen.
 *
 * The strips run in OPPOSITE directions on purpose — engines travelling right,
 * buyer prompts travelling left. They are the two axes the product crosses, so
 * sharing one direction would read as a single list. Being full-bleed, they
 * sit outside `Container`, which is why the copy carries its own.
 */
export function Hero() {
  const { hero, engines } = LANDING_CONTENT;
  return (
    <header className="flex min-h-[calc(100svh-var(--spacing-mkt-nav))] flex-col">
      <div className="flex flex-1 items-center py-12">
        <Container>
          <Reveal className="mx-auto max-w-4xl text-center">
            <Eyebrow>{hero.eyebrow}</Eyebrow>
            <h1 className="font-mkt-display text-mkt-d1 text-mkt-ink mkt-display-w mx-auto mt-5 mb-5 max-w-[18ch]">
              {hero.title} <em className="text-mkt-accent-display not-italic">{hero.accent}</em>
            </h1>
            <p className="text-mkt-lead text-mkt-ink-soft mx-auto max-w-[46ch]">{hero.body}</p>
            <div className="mt-7 flex flex-col items-center justify-center gap-2.5 sm:flex-row">
              <ButtonLink href={DEMO_HREF} className="w-full sm:w-auto">
                {DEMO_CTA}
                <ArrowRight className="size-3.5" aria-hidden />
              </ButtonLink>
              <ButtonLink href="#platform" intent="secondary" className="w-full sm:w-auto">
                {hero.secondaryCta}
              </ButtonLink>
            </div>
          </Reveal>
        </Container>
      </div>

      {/* Both strips sit directly on the paper — no cards, no borders, no
          fills. The generous per-item spacing is deliberate: with only six
          providers, tight gaps would fit two repeats on a wide screen and the
          loop would be obvious. */}
      <div className="shrink-0 pb-12">
        <div className="grid gap-7">
          {/* Six wide-spaced items are a short list, so this needs more copies
              than the prompts to stay overflowed on a large display. */}
          <Marquee direction="right" speed={52} copies={8} label="Answer engines Searchify covers">
            {ALL_ENGINES.map((engine) => (
              <EngineWordmark key={engine} engine={engine} className="me-24 shrink-0" />
            ))}
          </Marquee>

          <Marquee direction="left" speed={64} label="Example buyer questions">
            {engines.promptSamples.map((prompt) => (
              <span
                key={prompt}
                className="text-mkt-ink-muted text-mkt-sm me-12 inline-flex shrink-0 items-center italic"
              >
                “{prompt}”
              </span>
            ))}
          </Marquee>
        </div>
      </div>
    </header>
  );
}
