import { WHAT_WE_MEASURE, WHAT_WE_MEASURE_NOTE } from '@/lib/marketing-content/landing';

import { Section, SectionHeader } from '../primitives/section';
import { Reveal, StaggerGroup, StaggerItem } from '../primitives/reveal';

/**
 * Measurement disclosure — four axes, one line each.
 *
 * Kept terse on purpose: the terms themselves carry the meaning; the detail
 * only states the invariant a claim-guard test pins. Trends note stays below.
 */
export function WhatWeMeasure() {
  return (
    <Section tone="paper" aria-labelledby="what-we-measure-title">
      <SectionHeader
        eyebrow="What we measure"
        title="Every number says how it was produced."
        lead="Four conditions travel with every figure — in the app and in every export."
        headingId="what-we-measure-title"
      />
      <StaggerGroup className="border-border-subtle bg-panel shadow-card overflow-hidden rounded-lg border">
        <div className="grid md:grid-cols-2">
          {WHAT_WE_MEASURE.map((item, index) => (
            <StaggerItem key={item.term} className={cnMeasureCell(index)}>
              <h3 className="font-display text-foreground text-xl">{item.term}</h3>
              <p className="text-muted mt-3 max-w-[48ch] text-sm leading-relaxed">{item.detail}</p>
            </StaggerItem>
          ))}
        </div>
      </StaggerGroup>
      <Reveal>
        <p className="text-muted mt-6 max-w-[80ch] text-sm">{WHAT_WE_MEASURE_NOTE}</p>
      </Reveal>
    </Section>
  );
}

function cnMeasureCell(index: number): string {
  const edges = [
    'border-border-subtle border-b md:border-r',
    'border-border-subtle border-b',
    'border-border-subtle md:border-r max-md:border-b',
    '',
  ];
  return `bg-panel hover:bg-accent-soft p-6 transition-colors duration-200 md:p-8 ${edges[index]}`;
}
