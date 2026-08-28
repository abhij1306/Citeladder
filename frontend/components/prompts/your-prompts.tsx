'use client';

import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, Search } from 'lucide-react';
import Link from 'next/link';
import { Fragment, useMemo, useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { LaunchAuditButton } from '@/components/runs/launch-audit-button';
import { Badge } from '@/components/ui/badge';
import { buttonVariants } from '@/components/ui/button-variants';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import { Input } from '@/components/ui/input';
import { scoreBand, scoreBandText } from '@/components/ui/score-band';
import { Skeleton } from '@/components/ui/skeleton';
import { displayHeadingLgClasses } from '@/components/ui/typography';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { queryKeys } from '@/lib/api/query-keys';
import { topicsApi } from '@/lib/api/topics';
import { visibilityApi } from '@/lib/api/visibility';
import type { VisibilityExecutionEvidence } from '@/lib/api/types';
import { useActiveProject } from '@/lib/project/project-context';
import { usePromptSet } from '@/lib/prompts/use-prompt-set';
import { cn } from '@/lib/utils';

import { groupByTopic } from './topic-groups';

/**
 * Per-prompt measured visibility: the share of persisted executions for the
 * prompt where the brand was mentioned (design.md §9.4 Visibility Score
 * column). Derived read-only from the evidence projection — no provider call.
 * Prompts with no completed executions yet score `null` (rendered as an
 * explicit not-measured state), never 0.
 */
function promptScores(items: VisibilityExecutionEvidence[]): Map<string, number> {
  const totals = new Map<string, { runs: number; mentioned: number }>();
  for (const item of items) {
    if (!item.prompt_id) continue;
    const entry = totals.get(item.prompt_id) ?? { runs: 0, mentioned: 0 };
    entry.runs += 1;
    if (item.mentions.some((mention) => mention.kind === 'brand')) entry.mentioned += 1;
    totals.set(item.prompt_id, entry);
  }
  const scores = new Map<string, number>();
  for (const [promptId, { runs, mentioned }] of totals) {
    if (runs > 0) scores.set(promptId, Math.round((mentioned / runs) * 100));
  }
  return scores;
}

function ScoreCell({ score }: Readonly<{ score: number | null }>) {
  if (score === null) return <UnavailableValue state="not_measured" />;
  return (
    <span
      className={cn('font-mono text-sm font-medium tabular-nums', scoreBandText[scoreBand(score)])}
    >
      {score}%
    </span>
  );
}

/**
 * Your Prompts (design.md §9.4, sidebar "Prompts"): the read-only,
 * score-annotated view of the ACTIVE prompt configuration, grouped by topic
 * with expandable rows. Editing, archive/restore, and AI generation
 * live in the page's in-page manage mode (`/prompts?mode=manage`) — the
 * banner links there.
 */
export function YourPrompts() {
  const project = useActiveProject();
  const { projectId, prompts, isLoading, isError } = usePromptSet();
  const [search, setSearch] = useState('');
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const topicsQuery = useQuery({
    queryKey: projectId ? queryKeys.topics.list(projectId) : ['topics', 'list', 'none'],
    queryFn: ({ signal }) => topicsApi.list(projectId as string, { signal }),
    enabled: Boolean(projectId),
  });

  // Latest-audit evidence window; a project with no completed audits returns
  // an empty list and every score renders as an em-dash.
  const evidenceQuery = useQuery({
    queryKey: projectId
      ? queryKeys.visibility.evidence(projectId, {})
      : ['visibility', 'evidence', 'none'],
    queryFn: ({ signal }) =>
      visibilityApi.getVisibilityEvidence(projectId as string, undefined, { signal }),
    enabled: Boolean(projectId),
    retry: false,
  });

  const activePrompts = useMemo(
    () => prompts.filter((prompt) => prompt.status === 'active'),
    [prompts],
  );
  const visiblePrompts = useMemo(() => {
    const query = search.trim().toLowerCase();
    if (!query) return activePrompts;
    return activePrompts.filter((prompt) => prompt.text.toLowerCase().includes(query));
  }, [activePrompts, search]);

  const scores = useMemo(() => promptScores(evidenceQuery.data?.items ?? []), [evidenceQuery.data]);
  const groups = useMemo(
    () => groupByTopic(visiblePrompts, topicsQuery.data ?? [], scores),
    [visiblePrompts, topicsQuery.data, scores],
  );
  // The banner pairs the ACTIVE prompt total with its topic count, so the
  // count must come from the unfiltered set — not the search-filtered groups.
  const topicCount = useMemo(
    () =>
      groupByTopic(activePrompts, topicsQuery.data ?? [], scores).filter(
        (group) => group.topic !== null,
      ).length,
    [activePrompts, topicsQuery.data, scores],
  );

  const toggleGroup = (key: string) =>
    setCollapsed((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  if (!projectId) {
    return (
      <Alert tone="info">
        Select or create a project first — prompts belong to a project&apos;s prompt set.
      </Alert>
    );
  }

  // Wait for topics too: rendering groups before topics arrive would flash
  // every prompt as "Ungrouped" for a moment.
  if (isLoading || topicsQuery.isLoading) {
    return (
      <div className="grid gap-3">
        <Skeleton className="h-12 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }

  return (
    <div className="grid gap-[var(--compact-gap)]">
      {isError ? (
        <Alert tone="danger">Could not load prompts. Check your connection and try again.</Alert>
      ) : null}

      <div className="bg-panel border-border flex flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] border px-[var(--card-padding)] py-[var(--card-padding-compact)]">
        <p className="text-secondary text-sm">
          The {project?.brand_name ?? 'brand'} configuration includes{' '}
          <span className="text-foreground font-medium">{activePrompts.length}</span> visibility{' '}
          {activePrompts.length === 1 ? 'prompt' : 'prompts'} across{' '}
          <span className="text-foreground font-medium">{topicCount}</span>{' '}
          {topicCount === 1 ? 'topic' : 'topics'}, which are run on each audit.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Link
            href="/prompts?mode=manage"
            className={buttonVariants({ variant: 'secondary', size: 'sm' })}
          >
            Manage prompts
          </Link>
          <LaunchAuditButton size="sm" disabled={activePrompts.length === 0} />
        </div>
      </div>

      <div className="relative max-w-sm">
        <Search
          className="text-muted pointer-events-none absolute start-2 top-1/2 size-4 -translate-y-1/2"
          aria-hidden
        />
        <Input
          type="search"
          role="searchbox"
          aria-label="Search prompts"
          placeholder="Search prompts…"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          className="pl-8"
        />
      </div>

      {activePrompts.length === 0 ? (
        <div className="bg-panel shadow-card border-border/70 grid place-items-center gap-3 rounded-sm border p-[var(--empty-state-padding)] text-center">
          <p className={eyebrowClasses}>Your prompts</p>
          <h2 className={displayHeadingLgClasses}>No active prompts yet</h2>
          <p className="text-secondary max-w-md text-sm leading-relaxed">
            Switch to manage mode to add prompts manually, import a CSV, or generate prompts and
            topics with AI.
          </p>
          <Link
            href="/prompts?mode=manage"
            className={buttonVariants({ variant: 'secondary', size: 'md' })}
          >
            Manage prompts
          </Link>
        </div>
      ) : visiblePrompts.length === 0 ? (
        <div className="bg-panel shadow-card text-secondary border-border/70 rounded-sm border p-[var(--empty-state-padding)] text-center text-sm">
          No prompts match your search.
        </div>
      ) : (
        <div className="bg-panel border-border overflow-hidden rounded-[var(--radius-card)] border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="w-8" aria-label="Expand" />
                <TableHead>Prompt</TableHead>
                <TableHead numeric>Visibility Score</TableHead>
                <TableHead numeric>Avg Position</TableHead>
                <TableHead numeric>Sentiment</TableHead>
                <TableHead>Topic</TableHead>
                <TableHead>Branded</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {groups.map((group) => {
                const isCollapsed = collapsed.has(group.key);
                const label = group.topic?.name ?? 'Ungrouped';
                return (
                  <Fragment key={group.key}>
                    <TableRow className="bg-background-alt/50">
                      <TableCell>
                        <button
                          type="button"
                          aria-expanded={!isCollapsed}
                          aria-label={`${isCollapsed ? 'Expand' : 'Collapse'} topic ${label}`}
                          onClick={() => toggleGroup(group.key)}
                          className="focus-ring text-muted hover:text-foreground hover:bg-well grid size-7 place-items-center rounded-lg transition-colors"
                        >
                          {isCollapsed ? (
                            <ChevronRight className="size-4" aria-hidden />
                          ) : (
                            <ChevronDown className="size-4" aria-hidden />
                          )}
                        </button>
                      </TableCell>
                      <TableCell>
                        <span className="inline-flex items-center gap-2">
                          <Badge variant="neutral">{label}</Badge>
                          <span className="text-muted text-xs">
                            {group.prompts.length}{' '}
                            {group.prompts.length === 1 ? 'prompt' : 'prompts'}
                          </span>
                        </span>
                      </TableCell>
                      <TableCell numeric>
                        <ScoreCell score={group.score} />
                      </TableCell>
                      <TableCell numeric>
                        <UnavailableValue state="not_measured" />
                      </TableCell>
                      <TableCell numeric>
                        <UnavailableValue state="not_measured" />
                      </TableCell>
                      <TableCell />
                      <TableCell />
                    </TableRow>
                    {!isCollapsed
                      ? group.prompts.map((prompt) => (
                          <TableRow key={prompt.id}>
                            <TableCell />
                            <TableCell className="max-w-120">
                              <span className="text-foreground block truncate" title={prompt.text}>
                                {prompt.text}
                              </span>
                            </TableCell>
                            <TableCell numeric>
                              <ScoreCell score={scores.get(prompt.id) ?? null} />
                            </TableCell>
                            <TableCell numeric>
                              <UnavailableValue state="not_measured" />
                            </TableCell>
                            <TableCell numeric>
                              <UnavailableValue state="not_measured" />
                            </TableCell>
                            <TableCell>
                              {group.topic ? (
                                <Badge variant="neutral">{group.topic.name}</Badge>
                              ) : (
                                <UnavailableValue state="not_set" />
                              )}
                            </TableCell>
                            <TableCell>
                              {prompt.branded ? (
                                <Badge variant="status" value="info">
                                  Branded
                                </Badge>
                              ) : (
                                <span className="text-subtle text-xs font-medium">Not branded</span>
                              )}
                            </TableCell>
                          </TableRow>
                        ))
                      : null}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
}
