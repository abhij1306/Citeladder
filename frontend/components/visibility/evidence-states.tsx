'use client';

import Link from 'next/link';
import { Info, Inbox, RefreshCw, SearchX } from 'lucide-react';

import { Button } from '@/components/ui/button';
import { Card, CardContent, CardEyebrow, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { IconChip } from '@/components/ui/icon-chip';
import { displayHeadingLgClasses } from '@/components/ui/typography';
import { ICONS } from '@/lib/icons';

/**
 * Shared data-state presentations for the two evidence tabs (design.md states
 * gallery): loading skeleton, retryable error, empty (no executions yet),
 * filtered-empty, and the truncation notice. Both `mentions-citations.tsx` and
 * `fanout-evidence.tsx` reuse these so their states stay consistent.
 */

import type { ReactNode } from 'react';
import type { UseQueryResult } from '@tanstack/react-query';

import type { VisibilityExecutionEvidence, VisibilityEvidenceResponse } from '@/lib/api/types';
import { engineLabel } from '@/lib/providers/catalog';
import { formatExecutionDate, provenanceSummary } from '@/lib/visibility/evidence';

/** Props shared by both evidence tabs (Query Fanout, Mentions & Citations). */
export type EvidenceTabProps = Readonly<{
  query: UseQueryResult<VisibilityEvidenceResponse, unknown>;
  isFiltered: boolean;
  onClearFilters?: () => void;
  limit: number;
}>;

export function EvidenceSkeleton({ title }: Readonly<{ title: string }>) {
  return (
    <Card aria-hidden>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-3">
        <Skeleton className="h-24 w-full" />
        {[0, 1, 2].map((i) => (
          <div key={i} className="flex items-center gap-3">
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-4 w-12" />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

export function EvidenceError({
  title,
  onRetry,
}: Readonly<{ title: string; onRetry: () => void }>) {
  return (
    <Card>
      <CardContent>
        <div className="grid justify-items-center gap-3 py-10 text-center">
          <CardEyebrow>{title}</CardEyebrow>
          <IconChip className="bg-danger-bg text-danger-text">
            <ICONS.warning className="size-5" aria-hidden />
          </IconChip>
          <h3 className={displayHeadingLgClasses}>Couldn&apos;t load this evidence</h3>
          <p className="text-secondary max-w-xs text-sm">
            The request failed or timed out. Your filters are unchanged.
          </p>
          <Button variant="primary" size="sm" onClick={onRetry}>
            <RefreshCw className="size-4" aria-hidden />
            Retry
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function EvidenceEmpty({
  title,
  heading,
  body,
}: Readonly<{ title: string; heading: string; body: string }>) {
  return (
    <Card>
      <CardContent>
        {/* Midnight empty-state pattern: mono eyebrow + display heading + ghost CTA. */}
        <div className="grid justify-items-center gap-3 py-10 text-center">
          <CardEyebrow>{title}</CardEyebrow>
          <IconChip className="bg-neutral-bg text-muted">
            <Inbox className="size-5" aria-hidden />
          </IconChip>
          <h3 className={displayHeadingLgClasses}>{heading}</h3>
          <p className="text-secondary max-w-sm text-sm">{body}</p>
          <Button asChild variant="ghost" size="sm">
            <Link href="/runs">View Runs</Link>
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function EvidenceFilteredEmpty({
  title,
  body,
  onClear,
}: Readonly<{ title: string; body: string; onClear?: () => void }>) {
  return (
    <Card>
      <CardContent>
        <div className="grid justify-items-center gap-3 py-10 text-center">
          <CardEyebrow>{title}</CardEyebrow>
          <IconChip className="bg-neutral-bg text-muted">
            <SearchX className="size-5" aria-hidden />
          </IconChip>
          <h3 className={displayHeadingLgClasses}>No results match these filters</h3>
          <p className="text-secondary max-w-sm text-sm">{body}</p>
          {onClear ? (
            <Button variant="ghost" size="sm" onClick={onClear}>
              Clear filters
            </Button>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

export function TruncationNotice({ limit }: Readonly<{ limit: number }>) {
  return (
    <div className="border-border-subtle text-muted flex items-center gap-2 border-t px-4 py-2 text-xs">
      <Info className="size-4 shrink-0" aria-hidden />
      <span>Showing newest {limit} executions; refine filters to narrow results.</span>
    </div>
  );
}

/**
 * Shared per-execution header for both evidence tabs.
 *
 * Executions used to render as filled, bordered boxes nested inside the tab's
 * own card, each with a third layer of boxes around its citations/queries and a
 * line of raw truncated UUIDs across the top. That is three nested surfaces to
 * show one answer. An execution is now a ruled row, and its ids live behind one
 * "Provenance" disclosure instead of on the primary surface — they are audit
 * trail, not the evidence a reader came for.
 */
export function ExecutionHeader({
  item,
  trailing,
}: Readonly<{ item: VisibilityExecutionEvidence; trailing?: ReactNode }>) {
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
      <p className="text-muted text-xs">
        {formatExecutionDate(item.completed_at)}
        {item.repetition > 0 ? ` · repeat ${item.repetition + 1}` : ''}
      </p>
      <span className="text-muted flex items-center gap-2 text-xs">
        <span className="text-secondary font-medium">{engineLabel(item.logical_engine)}</span>
        <span>{item.transport_model}</span>
        {trailing}
      </span>
    </div>
  );
}

/** Collapsed task/analysis/artifact ids for one execution. */
export function ProvenanceDisclosure({ item }: Readonly<{ item: VisibilityExecutionEvidence }>) {
  return (
    <details className="text-muted text-xs">
      <summary className="focus-ring w-fit cursor-pointer rounded-sm">Provenance</summary>
      <p className="mt-1 font-mono">{provenanceSummary(item)}</p>
    </details>
  );
}
