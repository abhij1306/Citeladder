'use client';

import { MinusCircle, Search } from 'lucide-react';

import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  EvidenceEmpty,
  EvidenceError,
  EvidenceFilteredEmpty,
  EvidenceSkeleton,
  ExecutionHeader,
  TruncationNotice,
  type EvidenceTabProps,
} from '@/components/visibility/evidence-states';
import type { VisibilityExecutionEvidence } from '@/lib/api/types';
import {
  countOnlyExplanation,
  groupByPrompt,
  queryTexts,
  type PromptGroup,
} from '@/lib/visibility/evidence';

const TITLE = 'Query Fanout';

/**
 * Query Fanout tab — frozen prompt text, provider-generated search queries,
 * search counts, and text-availability state per execution, CLIENT-grouped by
 * the frozen prompt for presentation only. It never claims a global prompt
 * total, a true average over the truncated window, or numbered pagination the
 * endpoint cannot support, and it does NOT duplicate the citation browser (that
 * lives in Mentions & Citations).
 *
 * Per-execution query states are distinct (plan §Query Fanout / states gallery):
 *   - `queries_available` → the actual stored query strings;
 *   - `count_only`        → "Query text unavailable; provider reported N searches";
 *   - `no_search`         → "No web searches performed for this execution".
 *
 * States: skeleton, retryable error, empty, filtered-empty, and a truncation
 * notice when the newest window overflowed.
 */
export function FanoutEvidence({ query, isFiltered, onClearFilters, limit }: EvidenceTabProps) {
  if (query.isLoading) {
    return <EvidenceSkeleton title={TITLE} />;
  }
  if (query.isError) {
    return <EvidenceError title={TITLE} onRetry={() => query.refetch()} />;
  }

  const items = query.data?.items ?? [];
  const truncated = query.data?.truncated ?? false;

  if (items.length === 0) {
    return isFiltered ? (
      <EvidenceFilteredEmpty
        title={TITLE}
        body="No executions match the selected run, engine, prompt, and date range. Widen the range or clear a filter."
        onClear={onClearFilters}
      />
    ) : (
      <EvidenceEmpty
        title={TITLE}
        heading="No query fanout yet"
        body="Once a run executes your prompts, the search queries each engine generated (and where text is unavailable) appear here, grouped by prompt."
      />
    );
  }

  const groups = groupByPrompt(items);

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3">
        <div className="grid gap-1">
          <CardTitle>{TITLE}</CardTitle>
          <p className="text-secondary text-sm">Per-execution search queries grouped by prompt.</p>
        </div>
        <Badge variant="neutral">
          {groups.length} {groups.length === 1 ? 'prompt' : 'prompts'}
        </Badge>
      </CardHeader>
      <CardContent className="grid gap-0 p-0">
        <div className="divide-border-subtle divide-y">
          {groups.map((group) => (
            <PromptGroupBlock key={group.promptSnapshotId} group={group} />
          ))}
        </div>
        {truncated ? <TruncationNotice limit={limit} /> : null}
      </CardContent>
    </Card>
  );
}

function PromptGroupBlock({ group }: Readonly<{ group: PromptGroup }>) {
  return (
    <section className="grid gap-3 px-[var(--card-padding)] py-4">
      <div className="flex items-start gap-2">
        <h3 className="text-foreground text-sm leading-relaxed font-semibold sm:text-base">
          {group.promptText}
        </h3>
      </div>
      <ul className="grid gap-3">
        {group.executions.map((item) => (
          <ExecutionRow key={item.analysis_id} item={item} />
        ))}
      </ul>
    </section>
  );
}

function ExecutionRow({ item }: Readonly<{ item: VisibilityExecutionEvidence }>) {
  return (
    <li className="border-border-subtle bg-well/20 grid gap-2.5 rounded-md border p-3.5">
      <ExecutionHeader
        item={item}
        trailing={
          <span className="mono text-secondary text-xs">
            {item.search_query_count} {item.search_query_count === 1 ? 'search' : 'searches'}
          </span>
        }
      />
      <QueryDetail item={item} />
    </li>
  );
}

function QueryDetail({ item }: Readonly<{ item: VisibilityExecutionEvidence }>) {
  if (item.state === 'queries_available') {
    const queries = queryTexts(item);
    return (
      <ul className="grid gap-1.5 pt-0.5">
        {queries.map((query, index) => (
          <li
            key={`${index}-${query}`}
            className="border-border-subtle bg-panel text-foreground flex items-center gap-2 rounded border px-3 py-1.5 font-mono text-xs"
          >
            <Search className="text-muted size-3 shrink-0" aria-hidden />
            <span className="break-all">{query}</span>
          </li>
        ))}
      </ul>
    );
  }

  if (item.state === 'count_only') {
    return (
      <div className="border-border-subtle bg-panel text-muted rounded border px-3 py-2 text-xs">
        {countOnlyExplanation(item)}
      </div>
    );
  }

  return (
    <div className="border-border-subtle bg-panel text-muted flex items-center gap-2 rounded border px-3 py-2 text-xs">
      <MinusCircle className="size-4 shrink-0" aria-hidden />
      <span>No web searches performed for this execution</span>
    </div>
  );
}
