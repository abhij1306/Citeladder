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

/**
 * Severity is the deterministic band; nothing is inferred from a model. Typed
 * against the backend enum rather than `string`, so a new severity member is a
 * compile error here instead of silently landing in the `low` bucket.
 */
function priorityFrom(severity: Opportunity['severity']): InsightPriority {
  if (severity === 'critical' || severity === 'high') return 'high';
  if (severity === 'medium') return 'medium';
  return 'low';
}

/**
 * Opportunity types map to the layer that owns the finding. The backend enum
 * is closed (`visibility | site | traffic | topic`), so this is exhaustive
 * rather than prefix-matched — extend it when that enum grows.
 */
const TYPE_LAYER: Record<Opportunity['opportunity_type'], InsightLayer> = {
  visibility: 'demand',
  commerce: 'demand',
  traffic: 'demand',
  topic: 'content',
  site: 'site',
};

/**
 * Why the finding matters, per layer. Deliberately NOT keyed by `rule_id`:
 * that is an open, namespaced string (`aeo.*`, `technical.*`, `feed.*`) owned
 * by several backend subsystems, so a mapping here would be a guess that goes
 * stale the moment a rule is added — and a missing key would render nothing
 * where an explanation was promised.
 *
 * The per-rule explanation the backend does hold is `remediation`, and that
 * only exists on the opportunity DETAIL projection, not on the list rows this
 * adapter maps. Until the list carries it, this says what the layer means and
 * leaves the specifics to the evidence link, rather than exposing `rule_id`
 * and `opportunity_type` — internal identifiers no user can act on.
 */
const LAYER_REASON: Record<InsightLayer, string> = {
  site: 'Site Health expects this on pages of this kind, and the crawl did not find it.',
  content: 'Demand exists for this topic and your published content does not cover it.',
  demand: 'This was measured against the demand signals and coverage recorded for your project.',
  agent: 'The agent raised this while working through your project evidence.',
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
  // `site` is the fallback because a finding with no clearer owner is a
  // property of the site. Explicit rather than trusting the lookup: the enum is
  // closed today, but a backend member added ahead of this map would otherwise
  // hand `LAYER_LABEL` an undefined layer and render an empty chip.
  const layer = TYPE_LAYER[opportunity.opportunity_type] ?? 'site';

  return {
    id: opportunity.id,
    layer,
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
    whyThisMatters: LAYER_REASON[layer],
    potentialImpact: priority,
  };
}
