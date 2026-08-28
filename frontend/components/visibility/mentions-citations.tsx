'use client';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import {
  EvidenceEmpty,
  EvidenceError,
  EvidenceFilteredEmpty,
  EvidenceSkeleton,
  ExecutionHeader,
  TruncationNotice,
  type EvidenceTabProps,
} from '@/components/visibility/evidence-states';
import { ExternalLink } from 'lucide-react';
import { classificationBadgeValue, classificationLabel } from '@/lib/runs/status';
import type { VisibilityExecutionEvidence } from '@/lib/api/types';
import { totalCitationCount, totalMentionCount } from '@/lib/visibility/evidence';

const TITLE = 'Mentions & Citations';

function safeUrl(value?: string): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === 'http:' || url.protocol === 'https:' ? url.toString() : null;
  } catch {
    return null;
  }
}

/**
 * Mentions & Citations tab — persisted brand/competitor mention rows and
 * classified citation records, grouped by execution, with selected-run / prompt
 * / engine context and task/analysis/artifact provenance. It renders only
 * PERSISTED rows (never inferred) and does NOT render a generated-query list —
 * that belongs to Query Fanout.
 *
 * States: skeleton, retryable error, empty (no persisted evidence), filtered
 * empty, and a truncation notice when the newest window overflowed.
 */
export function MentionsCitations({ query, isFiltered, onClearFilters, limit }: EvidenceTabProps) {
  if (query.isLoading) {
    return <EvidenceSkeleton title={TITLE} />;
  }
  if (query.isError) {
    return <EvidenceError title={TITLE} onRetry={() => query.refetch()} />;
  }

  const items = query.data?.items ?? [];
  const truncated = query.data?.truncated ?? false;

  // Only the executions that actually carry persisted mention/citation rows.
  const withEvidence = items.filter(
    (item) => item.mentions.length > 0 || item.citations.length > 0,
  );

  if (withEvidence.length === 0) {
    return isFiltered ? (
      <EvidenceFilteredEmpty
        title={TITLE}
        body="No persisted mentions or citations match the selected run, engine, prompt, and date range. Widen the range or clear a filter."
        onClear={onClearFilters}
      />
    ) : (
      <EvidenceEmpty
        title={TITLE}
        heading="No mentions or citations yet"
        body="Once a run executes your prompts, the brand and competitor mentions and the sources cited in each answer appear here."
      />
    );
  }

  const mentionCount = totalMentionCount(withEvidence);
  const citationCount = totalCitationCount(withEvidence);

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="grid gap-1">
          <CardTitle>{TITLE}</CardTitle>
          <p className="text-secondary text-sm">
            Persisted mentions and classified citations, grouped by execution.
          </p>
        </div>
        <Badge variant="neutral">
          {mentionCount} mentions · {citationCount} citations
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-0 p-0">
        <ul className="divide-border-subtle divide-y">
          {withEvidence.map((item) => (
            <ExecutionEvidenceRow key={item.analysis_id} item={item} />
          ))}
        </ul>
        {truncated ? <TruncationNotice limit={limit} /> : null}
      </CardContent>
    </Card>
  );
}

function ExecutionEvidenceRow({ item }: Readonly<{ item: VisibilityExecutionEvidence }>) {
  return (
    <li className="hover:bg-panel-tonal/40 grid gap-3 px-[var(--card-padding)] py-4 transition-colors">
      <div className="border-border-subtle bg-well/20 grid gap-1.5 rounded-md border p-3">
        <p className="text-foreground text-sm leading-relaxed font-medium">
          {item.prompt_text || 'Untitled prompt'}
        </p>
        <ExecutionHeader item={item} />
      </div>

      {item.mentions.length > 0 ? (
        <div className="grid gap-1.5">
          <p className={eyebrowClasses}>Mentions</p>
          <div className="flex flex-wrap gap-1.5">
            {item.mentions.map((mention) => (
              <Badge
                key={`${mention.artifact_id ?? item.analysis_id}:${mention.analyzer_version}:${mention.kind}:${mention.name}:${mention.first_offset ?? 'na'}`}
                variant="classification"
                value={mention.kind === 'brand' ? 'owned' : 'competitor'}
              >
                {mention.name || (mention.kind === 'brand' ? 'Brand' : 'Competitor')}
              </Badge>
            ))}
          </div>
        </div>
      ) : null}

      {item.citations.length > 0 ? (
        <div className="grid gap-1.5">
          <p className={eyebrowClasses}>Citations</p>
          <ul className="divide-border-subtle border-border-subtle bg-panel divide-y rounded-md border">
            {item.citations.map((citation) => {
              const href = safeUrl(citation.url);
              return (
                <li
                  key={`${item.analysis_id}-${citation.ordinal}-${citation.url}`}
                  className="flex items-center justify-between gap-3 px-3 py-2"
                >
                  <div className="min-w-0 flex-1">
                    {href ? (
                      <a
                        href={href}
                        target="_blank"
                        rel="noreferrer"
                        className="text-foreground hover:text-accent-text inline-flex max-w-full items-center gap-1.5 text-xs font-medium transition-colors hover:underline"
                      >
                        <span className="truncate">
                          {citation.title?.trim() || citation.domain || citation.url}
                        </span>
                        <ExternalLink className="size-3 shrink-0" aria-hidden />
                      </a>
                    ) : (
                      <span className="text-foreground block truncate text-xs font-medium">
                        {citation.title?.trim() || citation.domain || citation.url}
                      </span>
                    )}
                    {citation.domain && citation.title ? (
                      <span className="text-muted text-2xs block truncate">{citation.domain}</span>
                    ) : null}
                  </div>
                  <Badge
                    className="shrink-0"
                    variant="classification"
                    value={classificationBadgeValue(citation.classification)}
                  >
                    {classificationLabel(citation.classification)}
                  </Badge>
                </li>
              );
            })}
          </ul>
        </div>
      ) : null}
    </li>
  );
}
