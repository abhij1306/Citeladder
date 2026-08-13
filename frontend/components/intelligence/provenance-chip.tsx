import { cn } from '@/lib/utils';

/**
 * ProvenanceChip — analyzer version and snapshot identity.
 *
 * §5 requires this on every projection surface. It exists so a number is
 * reproducible: two people looking at the same score can confirm they are
 * looking at the same rules over the same snapshot, which is the difference
 * between evidence and a dashboard.
 */
export type Provenance = {
  /** Analyzer/rule version that produced the projection. */
  analyzerVersion?: string;
  /** Snapshot or run identity the projection was computed over. */
  snapshotId?: string;
};

/** Renders the parts that exist; a missing part is omitted, never faked. */
function provenanceParts(provenance: Provenance): string[] {
  const parts: string[] = [];
  if (provenance.analyzerVersion) parts.push(`analyzer ${provenance.analyzerVersion}`);
  if (provenance.snapshotId) parts.push(`snapshot ${provenance.snapshotId}`);
  return parts;
}

export type ProvenanceChipProps = {
  provenance: Provenance;
  className?: string;
};

export function ProvenanceChip({ provenance, className }: Readonly<ProvenanceChipProps>) {
  const parts = provenanceParts(provenance);
  // An empty chip would assert provenance it does not have. Render nothing.
  if (parts.length === 0) return null;

  return (
    <span
      className={cn(
        'text-subtle bg-well text-2xs inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 font-medium tabular-nums',
        className,
      )}
      title="Rules and snapshot this projection was computed from"
    >
      {parts.join(' · ')}
    </span>
  );
}
