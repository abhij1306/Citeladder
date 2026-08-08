import type { Opportunity } from '@/lib/api/types';

import type { InsightLayer, InsightModel, InsightPriority } from './insight';

/**
 * Adapter: a persisted opportunity → the shared insight object (§5).
 *
 * Opportunities are the projection that already carries everything the insight
 * anatomy needs — title, severity, deterministic priority, evidence counts and
 * a target. Mapping here rather than in each screen keeps one insight shape
 * across the layers, which is the whole point of the component.
 */

/** Severity is the deterministic band; nothing is inferred from a model. */
function priorityFrom(severity: string): InsightPriority {
  if (severity === 'critical' || severity === 'high') return 'high';
  if (severity === 'medium') return 'medium';
  return 'low';
}

/**
 * Opportunity types map to the layer that owns the finding. The backend enum
 * is closed (`visibility | site | traffic | topic`), so this is exhaustive
 * rather than prefix-matched; `site` is the fallback because a finding with no
 * clearer owner is a property of the site.
 */
const TYPE_LAYER: Record<Opportunity['opportunity_type'], InsightLayer> = {
  visibility: 'demand',
  traffic: 'demand',
  topic: 'content',
  site: 'site',
};

/** Falls back to counts when the backend has no user-facing target label. */
function evidenceLabel(opportunity: Opportunity): string {
  if (opportunity.target_label) return opportunity.target_label;

  const { count, kinds } = opportunity.evidence_summary;
  const noun = count === 1 ? 'item' : 'items';
  const suffix = kinds.length > 0 ? ` · ${kinds.join(', ')}` : '';
  return `${count} ${noun}${suffix}`;
}

export function insightFromOpportunity(opportunity: Opportunity): InsightModel {
  const priority = priorityFrom(opportunity.severity);
  const hasEvidence = opportunity.evidence_summary.count > 0;

  return {
    id: opportunity.id,
    layer: TYPE_LAYER[opportunity.opportunity_type],
    priority,
    claim: opportunity.title,
    // §5: no insight renders without resolvable evidence. An opportunity with
    // zero evidence rows is exactly that case, so it yields null here and the
    // component drops it rather than showing an unbacked claim.
    evidence: hasEvidence
      ? {
          href: `/opportunities?opportunity=${opportunity.id}`,
          label: evidenceLabel(opportunity),
        }
      : null,
    whyThisMatters: `Rule ${opportunity.rule_id} flagged this on the ${opportunity.opportunity_type} surface.`,
    potentialImpact: priority,
  };
}
