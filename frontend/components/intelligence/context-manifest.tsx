import { cn } from '@/lib/utils';

import { EvidenceLink, type EvidenceRef } from './evidence-link';

/**
 * ContextManifest — included and omitted artifact counts and IDs for any agent
 * or generation task.
 *
 * §7.5: this is what makes "selective context" inspectable rather than a
 * claim. The omitted side is the point — a manifest that lists only what was
 * included tells the user nothing about what the agent could not see, and
 * "truncated" and "deliberately excluded" are different failures.
 */
export type ManifestEntry = {
  id: string;
  label: string;
  /** Resolves to the artifact, when the caller has a route for it. */
  evidence?: EvidenceRef;
};

export type ContextManifestModel = {
  included: readonly ManifestEntry[];
  /** Artifacts left out, each with the reason it was left out. */
  omitted: readonly (ManifestEntry & { reason: string })[];
  /** Artifacts included but cut short — partial context, not full context. */
  truncated?: readonly ManifestEntry[];
  /** Contradictions knowingly carried into the task. */
  contradictions?: readonly ManifestEntry[];
};

function ManifestSection({
  title,
  entries,
  emptyText,
}: Readonly<{
  title: string;
  entries: readonly (ManifestEntry & { reason?: string })[];
  emptyText: string;
}>) {
  return (
    <section className="flex flex-col gap-1.5">
      <p className="text-subtle text-2xs font-medium tracking-wide uppercase">
        {title} · {entries.length}
      </p>
      {entries.length === 0 ? (
        <p className="text-muted text-xs">{emptyText}</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {entries.map((entry) => (
            <li key={entry.id} className="flex flex-col gap-0.5">
              <span className="text-foreground text-xs">{entry.label}</span>
              {entry.reason ? <span className="text-muted text-2xs">{entry.reason}</span> : null}
              {entry.evidence ? <EvidenceLink evidence={entry.evidence} /> : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

export type ContextManifestProps = {
  manifest: ContextManifestModel;
  className?: string;
};

export function ContextManifest({ manifest, className }: Readonly<ContextManifestProps>) {
  const { included, omitted, truncated = [], contradictions = [] } = manifest;

  return (
    <div
      className={cn(
        'border-border-subtle bg-panel flex flex-col gap-4 rounded-lg border p-4',
        className,
      )}
    >
      <ManifestSection
        title="Included"
        entries={included}
        emptyText="No artifacts were included in this task's context."
      />
      <ManifestSection
        title="Omitted"
        entries={omitted}
        emptyText="Nothing was omitted."
      />
      {truncated.length > 0 ? (
        <ManifestSection
          title="Truncated"
          entries={truncated}
          emptyText="Nothing was truncated."
        />
      ) : null}
      {contradictions.length > 0 ? (
        <ManifestSection
          title="Contradictions carried in"
          entries={contradictions}
          emptyText="No contradictions were carried in."
        />
      ) : null}
    </div>
  );
}
