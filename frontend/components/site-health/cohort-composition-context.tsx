import type { SiteHealthOverview } from '@/lib/api/types';
import { pageKindLabel } from '@/lib/site-health/page-kinds';

type CohortComposition = SiteHealthOverview['trend']['cohort_composition'];

export function CohortCompositionContext({
  reason,
  composition,
}: Readonly<{
  reason: string;
  composition: CohortComposition;
}>) {
  if (reason !== 'cohort_composition_changed') return null;
  const addedKinds =
    composition.added_page_kinds.length === 0
      ? 'None'
      : composition.added_page_kinds.map(pageKindLabel).join(', ');
  const removedKinds =
    composition.removed_page_kinds.length === 0
      ? 'None'
      : composition.removed_page_kinds.map(pageKindLabel).join(', ');

  return (
    <div className="border-border-subtle bg-background-alt grid gap-2 rounded-md border p-3 text-xs">
      <p className="text-foreground font-medium">Scored cohort composition changed.</p>
      <p className="text-secondary">
        Added page kinds: {addedKinds}. Removed page kinds: {removedKinds}. Score movement is not
        split into quality versus cohort effects.
      </p>
      <dl className="grid gap-2 sm:grid-cols-2">
        <CompositionRow label="Previous counts" counts={composition.previous_page_count_by_kind} />
        <CompositionRow label="Current counts" counts={composition.current_page_count_by_kind} />
      </dl>
    </div>
  );
}

function CompositionRow({
  label,
  counts,
}: Readonly<{ label: string; counts: Readonly<Partial<Record<string, number>>> }>) {
  const rows = Object.entries(counts).sort(([left], [right]) => left.localeCompare(right));
  return (
    <div className="grid gap-0.5">
      <dt className="text-muted">{label}</dt>
      <dd className="text-secondary tabular-nums">
        {rows.length === 0
          ? 'No scored page kinds'
          : rows.map(([kind, count]) => `${pageKindLabel(kind)} ${count}`).join(' · ')}
      </dd>
    </div>
  );
}
