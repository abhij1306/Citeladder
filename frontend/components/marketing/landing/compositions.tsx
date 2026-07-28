import { ArrowRight } from 'lucide-react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { Badge } from '../primitives/badge';
import { EngineDot } from '../primitives/engine-chip';
import { Meta } from '../primitives/label';
import { Section, SectionHeader } from '../primitives/section';
import { Reveal } from '../primitives/reveal';
import { ExampleDataNote, Panel, WallpaperPanel } from '../scenes/wallpaper-panel';

/**
 * One connected example: a buyer question produces an observable pattern,
 * which resolves into a concrete action. Keeping the three stages inside one
 * surface makes the causal chain legible instead of presenting a collage.
 */
export function Compositions() {
  const { query, strategy } = LANDING_CONTENT.compositions;

  return (
    <Section tone="sunken" rhythm="loose" aria-labelledby="strategy-workflow-title">
      <SectionHeader
        kicker={strategy.tag}
        title="From buyer question to next best action."
        intro={strategy.body}
        headingId="strategy-workflow-title"
      />

      <Reveal>
        <WallpaperPanel className="min-w-0 p-3 sm:p-5 lg:p-6">
          <div className="mb-3 flex items-center justify-between gap-3 px-1">
            <Meta as="p" className="text-mkt-ink-muted">
              Example workflow / one observed pattern
            </Meta>
            <ExampleDataNote />
          </div>

          <Panel className="lg:divide-mkt-line-soft relative grid min-w-0 overflow-hidden lg:grid-cols-3 lg:divide-x">
            <article
              className="mkt-flow-stage flex min-w-0 flex-col p-5 sm:p-6"
              data-flow-stage="1"
            >
              <Meta as="p" className="text-mkt-ink-muted whitespace-nowrap">
                01 / Buyer question
              </Meta>
              <div className="mt-5">
                <h3 className="font-mkt-display text-mkt-ink sm:text-mkt-d4 text-lg font-medium">
                  “{query.cards[0]}”
                </h3>
                <div className="mt-5 flex flex-wrap gap-2">
                  <Badge tone="neutral">Comparison</Badge>
                  <Badge tone="neutral">Enterprise</Badge>
                </div>
              </div>
            </article>

            <div className="border-mkt-line bg-mkt-surface absolute top-1/2 left-1/3 z-2 hidden size-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border lg:grid">
              <ArrowRight
                className="mkt-flow-arrow text-mkt-ink-muted size-4"
                data-flow-arrow="1"
                aria-hidden
              />
            </div>
            <MobileArrow />

            <article
              className="mkt-flow-stage flex min-w-0 flex-col p-5 sm:p-6"
              data-flow-stage="2"
            >
              <Meta as="p" className="text-mkt-ink-muted whitespace-nowrap">
                02 / Observed pattern
              </Meta>
              <div className="mt-5">
                <div className="grid gap-3">
                  <div className="flex items-center justify-between gap-3">
                    <EngineDot engine="openai" />
                    <Badge tone="warn">Brand missing</Badge>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <EngineDot engine="gemini" />
                    <Badge tone="proof">Competitor cited</Badge>
                  </div>
                  <div className="flex items-center justify-between gap-3">
                    <EngineDot engine="claude" />
                    <Badge tone="warn">Brand missing</Badge>
                  </div>
                </div>
                <p className="text-mkt-sm text-mkt-ink-soft mt-5">
                  Your category is visible, but your proof is not reaching the answer.
                </p>
              </div>
            </article>

            <div className="border-mkt-line bg-mkt-surface absolute top-1/2 left-2/3 z-2 hidden size-8 -translate-x-1/2 -translate-y-1/2 place-items-center rounded-full border lg:grid">
              <ArrowRight
                className="mkt-flow-arrow text-mkt-ink-muted size-4"
                data-flow-arrow="2"
                aria-hidden
              />
            </div>
            <MobileArrow />

            <article
              className="mkt-flow-stage bg-mkt-paper-raised flex min-w-0 flex-col p-5 sm:p-6"
              data-flow-stage="3"
            >
              <Meta as="p" className="text-mkt-ink-muted whitespace-nowrap">
                03 / Next action
              </Meta>
              <div className="mt-5">
                <h3 className="font-mkt-display text-mkt-ink sm:text-mkt-d4 text-lg font-medium">
                  Publish an enterprise comparison page.
                </h3>
                <Badge tone="good" className="mt-4">
                  High priority
                </Badge>
                <ul className="text-mkt-sm text-mkt-ink-soft mt-5 grid gap-2">
                  <li>Answer the decision criteria buyers compare.</li>
                  <li>Add evidence engines can cite directly.</li>
                  <li>Re-run the same question and measure the change.</li>
                </ul>
              </div>
            </article>
          </Panel>
        </WallpaperPanel>
      </Reveal>
    </Section>
  );
}

function MobileArrow() {
  return (
    <div className="border-mkt-line-soft grid place-items-center border-y py-2 lg:hidden">
      <ArrowRight className="text-mkt-ink-muted size-4 rotate-90" aria-hidden />
    </div>
  );
}
