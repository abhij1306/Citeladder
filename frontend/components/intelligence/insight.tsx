import type { ReactNode } from 'react';

import { eyebrowClasses } from '@/components/ui/eyebrow';
import { cn } from '@/lib/utils';

import { EvidenceLink, type EvidenceRef } from './evidence-link';
import { ProvenanceChip, type Provenance } from './provenance-chip';

/**
 * Insight — the reusable unit the product model produces.
 *
 * The anatomy is fixed by docs/design.md: priority + source layer, claim,
 * evidence, why this matters, potential impact, two actions. One
 * implementation, used identically in Site, Content, Demand, and the Growth
 * Agent — a layer that invents its own finding card breaks the product's
 * coherence, which is why this file exports no variant knobs for layout.
 *
 * Two rules are enforced in code rather than by review:
 *  - An insight with no resolvable evidence does not render (returns null).
 *  - "Why this matters" is grounded text supplied by the caller from a pack
 *    expectation, demand signal, or contradiction. This component never
 *    synthesizes one, and never renders a causal claim.
 */

/** The four layers. The chip is how a user learns which system found this. */
export type InsightLayer = 'site' | 'content' | 'demand' | 'agent';

const LAYER_LABEL: Record<InsightLayer, string> = {
  site: 'Site',
  content: 'Content',
  demand: 'Demand',
  agent: 'Growth Agent',
};

/** Deterministic priority bands — from the priority formula, never a model. */
export type InsightPriority = 'high' | 'medium' | 'low';

const PRIORITY_COPY: Record<InsightPriority, string> = {
  high: 'High priority',
  medium: 'Medium priority',
  low: 'Low priority',
};

/** Paired with the text label, never the sole signal (design.md, WCAG 1.4.1). */
const PRIORITY_TONE: Record<InsightPriority, string> = {
  high: 'bg-danger-bg text-danger-text',
  medium: 'bg-warning-bg text-warning-text',
  low: 'bg-neutral-bg text-secondary',
};

const IMPACT_COPY: Record<InsightPriority, string> = {
  high: 'High',
  medium: 'Medium',
  low: 'Low',
};

export type InsightModel = {
  /** Server ID. The same insight in two places is the same ID and cache key. */
  id: string;
  layer: InsightLayer;
  priority: InsightPriority;
  /** One sentence, specific, quantified where a count exists. */
  claim: string;
  /** Scope, selector, observation time — always resolves to persisted evidence. */
  evidence: EvidenceRef | null;
  /** Grounded in a pack expectation, demand signal, or contradiction. */
  whyThisMatters: string;
  /** From the deterministic priority formula, not a model. */
  potentialImpact: InsightPriority;
  provenance?: Provenance;
};

export type InsightProps = {
  insight: InsightModel;
  /** The "act" action. Inspect is always the evidence link. */
  action?: ReactNode;
  className?: string;
  hideWhyThisMatters?: boolean;
};

export function Insight({
  insight,
  action,
  className,
  hideWhyThisMatters = false,
}: Readonly<InsightProps>) {
  // §5: does not render without resolvable evidence. A claim we cannot open is
  // not an insight, and degrading to a plain-text card would be exactly the
  // unevidenced conclusion this system exists to prevent.
  if (!insight.evidence) return null;

  return (
    <article
      data-insight-id={insight.id}
      data-layer={insight.layer}
      className={cn(
        'bg-panel border-border shadow-card flex flex-col gap-3 rounded-sm border p-4 sm:p-[var(--card-padding)]',
        className,
      )}
    >
      {/* 1. Priority and source layer */}
      <div className="flex items-center justify-between gap-3">
        <span
          className={cn(
            'text-2xs inline-flex items-center rounded px-1.5 py-0.5 font-semibold',
            PRIORITY_TONE[insight.priority],
          )}
        >
          {PRIORITY_COPY[insight.priority]}
        </span>
        <span className={cn(eyebrowClasses, 'text-subtle')}>{LAYER_LABEL[insight.layer]}</span>
      </div>

      {/* 2. Claim */}
      <h3 className="font-display text-foreground text-sm leading-[1.35] font-semibold text-balance">
        {insight.claim}
      </h3>

      {/* 3. Evidence */}
      <div className="flex flex-col gap-1">
        <p className={cn(eyebrowClasses, 'text-subtle')}>Evidence</p>
        <EvidenceLink evidence={insight.evidence} />
      </div>

      {/* 4. Why this matters */}
      {!hideWhyThisMatters ? (
        <div className="flex flex-col gap-1">
          <p className={cn(eyebrowClasses, 'text-subtle')}>Why this matters</p>
          <p className="text-muted text-xs leading-relaxed">{insight.whyThisMatters}</p>
        </div>
      ) : null}

      {/* 5. Potential impact */}
      <div className="border-border-subtle flex items-center justify-between border-t pt-3">
        <span className={cn(eyebrowClasses, 'text-subtle')}>Potential impact</span>
        <span className="font-display text-foreground text-xs font-semibold">
          {IMPACT_COPY[insight.potentialImpact]}
        </span>
      </div>

      {/* 6. Two actions: inspect (evidence) and act (caller-supplied). */}
      {action || insight.provenance ? (
        <div className="flex flex-wrap items-center justify-between gap-2">
          {insight.provenance ? <ProvenanceChip provenance={insight.provenance} /> : <span />}
          {action}
        </div>
      ) : null}
    </article>
  );
}
