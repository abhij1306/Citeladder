import { WHAT_WE_MEASURE } from '@/lib/marketing-content/landing';

import { Section, SectionHeader } from '../primitives/section';
import { Reveal, StaggerGroup, StaggerItem } from '../primitives/reveal';

/**
 * The measurement disclosure, between the product beat and the proof beat.
 *
 * Every number elsewhere on the site is qualified by these four axes, so they
 * are stated once, plainly, rather than left implicit: which mode a run used,
 * which exact model produced an answer (or that an aggregate spans several),
 * whether retrieval was on, and what cadence means here.
 *
 * Cadence is deliberately described as an ALLOWANCE, not a schedule. No
 * dispatcher ships in this release, so any wording implying automatic runs
 * would promise behaviour the platform does not have.
 */
export function WhatWeMeasure() {
  return (
    <Section tone="paper" aria-labelledby="what-we-measure-title">
      <SectionHeader
        eyebrow="What we measure"
        title="Every number says how it was produced."
        lead="A score without its measurement conditions is not evidence. These four travel with every figure, in the app and in every export."
        headingId="what-we-measure-title"
      />
      <StaggerGroup className="grid gap-5 md:grid-cols-2">
        {WHAT_WE_MEASURE.map((item) => (
          <StaggerItem key={item.term} className="h-full">
            <div className="bg-panel shadow-card h-full rounded-lg p-8">
              <h3 className="font-display text-foreground text-xl">{item.term}</h3>
              <p className="text-muted mt-4 text-base">{item.detail}</p>
            </div>
          </StaggerItem>
        ))}
      </StaggerGroup>
      <Reveal>
        <p className="text-muted mt-8 max-w-[90ch] text-sm">{WHAT_WE_MEASURE_NOTE}</p>
      </Reveal>
    </Section>
  );
}

const WHAT_WE_MEASURE_NOTE =
  'Trends are partitioned by mode, model and retrieval state — points measured under different ' +
  'conditions are never folded into one line, because that line would describe no real run.';
