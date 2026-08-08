import Link from 'next/link';
import { ArrowUpRight } from 'lucide-react';

import { cn } from '@/lib/utils';

/**
 * EvidenceLink — the path from a derived number to the artifact it came from.
 *
 * The rule this enforces (frontend-growth-intelligence.md §5): every derived
 * number or claim opens its persisted source, and there is no conclusion
 * without a path to evidence. A caller that cannot supply an href has, by
 * definition, an unresolvable claim — so `href` is required rather than
 * optional, and the "no evidence" case is handled by not rendering the
 * conclusion at all (see `Insight`), not by rendering a dead link.
 */
export type EvidenceRef = {
  /** Route to the persisted artifact — a crawl, import row, or engine answer. */
  href: string;
  /** What the evidence is: "47 pages · /products/*", "GSC import · 12 Jun". */
  label: string;
  /** Optional observation time, rendered as supporting context. */
  observedAt?: string;
};

export type EvidenceLinkProps = {
  evidence: EvidenceRef;
  className?: string;
};

export function EvidenceLink({ evidence, className }: Readonly<EvidenceLinkProps>) {
  return (
    <Link
      href={evidence.href}
      className={cn(
        'text-accent-text inline-flex items-center gap-1 text-xs font-medium underline-offset-2 hover:underline',
        className,
      )}
    >
      <span>{evidence.label}</span>
      {evidence.observedAt ? (
        <span className="text-subtle font-normal">· {evidence.observedAt}</span>
      ) : null}
      <ArrowUpRight aria-hidden className="size-3 shrink-0" />
    </Link>
  );
}
