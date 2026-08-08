'use client';

import { Badge } from '@/components/ui/badge';
import { PLACEHOLDER } from '@/lib/site-health/status';

/**
 * The industry-role chip, rendered beside — never instead of — the generic
 * `PageKindBadge`. The two answer different questions: `page_kind` is what the
 * page structurally IS, `industry_role` is what job it does in the active
 * industry pack.
 *
 * Three states the UI must keep distinct:
 *
 *   - no role data at all (pack classifier never ran)  -> `—`
 *   - an EXECUTED abstention (ran, declined to commit) -> "Unclassified" plus
 *     the specific reason, because "we looked and could not tell" is a real
 *     finding, not missing data;
 *   - a selected role -> the role label.
 *
 * Role IDs are pack-defined and namespaced (`education.admissions_overview`).
 * An unrecognized ID renders its own last segment humanized rather than a
 * fabricated label, so a new pack never needs a frontend release to display.
 */

const ABSTENTION_LABELS: Readonly<Record<string, string>> = {
  no_signal: 'No role signals on this page',
  schema_only: 'Only schema markup matched — no visible evidence',
  below_minimum_score: 'Signals too weak to assign a role',
  ambiguous_margin: 'Two roles scored too closely to separate',
  not_applicable: 'Not applicable to this corpus item',
  pack_not_eligible: 'Active pack does not cover this page',
  invalid_input: 'Page facts were unusable for classification',
};

export function abstentionLabel(reason: string | null | undefined): string {
  if (!reason) return 'Unclassified';
  return ABSTENTION_LABELS[reason] ?? 'Unclassified';
}

/**
 * Display text for a pack role ID.
 *
 * Deliberately the raw, fully-qualified ID. Stripping the namespace would
 * render `education.fees` and `commerce.fees` identically, and title-casing an
 * unreviewed ID presents a guess as a reviewed label. Until the API supplies
 * reviewed display labels, showing the exact ID a pack defined is the honest
 * option — and it is what the user needs to look the role up.
 */
export function industryRoleLabel(roleId: string): string {
  return roleId;
}

export function IndustryRoleBadge({
  roleId,
  abstentionReason,
}: Readonly<{
  roleId: string | null | undefined;
  abstentionReason?: string | null;
}>) {
  if (roleId) {
    return <Badge>{industryRoleLabel(roleId)}</Badge>;
  }
  // An executed abstention is reported as such; only genuinely absent data
  // falls through to the placeholder.
  if (abstentionReason) {
    // The REASON is the finding — "we looked and could not tell, because the
    // page had only schema markup" is actionable in a way that a bare
    // "Unclassified" is not. Hiding it behind hover would strand it on touch
    // devices and screen readers, so it is visible text.
    return (
      <span className="text-muted flex flex-col" title={abstentionLabel(abstentionReason)}>
        <span>Unclassified</span>
        <span className="text-2xs">{abstentionLabel(abstentionReason)}</span>
      </span>
    );
  }
  return <span className="text-muted">{PLACEHOLDER}</span>;
}
