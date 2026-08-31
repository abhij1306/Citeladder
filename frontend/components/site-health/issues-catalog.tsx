'use client';

import { useMemo, useState } from 'react';
import Link from 'next/link';
import { useQuery } from '@tanstack/react-query';

import { IssueEvidence } from '@/components/site-health/issue-evidence';
import {
  IssueSearch,
  useIssuesCatalogUrlState,
} from '@/components/site-health/issues-catalog-url-state';
import { PageKindSelect } from '@/components/site-health/page-kind-select';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { CopyButton } from '@/components/ui/copy-button';
import { Pressable } from '@/components/ui/pressable';
import { SegmentedControl } from '@/components/ui/segmented-control';
import { Skeleton } from '@/components/ui/skeleton';
import { siteHealthQueries, type IssuesParams } from '@/lib/api/site-health';
import type { IssuesSummary, SiteIssue, SiteIssueDetail } from '@/lib/api/types';
import { changeIssueFilters, toIssueParams, type IssueFilters } from '@/lib/site-health/filters';
import { dimensionLabel, issueTitle, severityLabel } from '@/lib/site-health/issues';
import { pageKindLabel } from '@/lib/site-health/page-kinds';
import { pageDisplayTitle } from '@/lib/site-health/status';
import { cn } from '@/lib/utils';

const ISSUE_LIMIT = 25;
const OCCURRENCE_LIMIT = 25;
type FilterKey = 'all' | 'high' | 'medium' | 'low' | 'technical' | 'aeo';
type FindingView = 'defect' | 'advisory';

const FILTERS: ReadonlyArray<{ key: FilterKey; label: string }> = [
  { key: 'all', label: 'All' },
  { key: 'high', label: 'High' },
  { key: 'medium', label: 'Medium' },
  { key: 'low', label: 'Low' },
  { key: 'technical', label: 'Web Fundamentals' },
  { key: 'aeo', label: 'AEO' },
];

function filterParams(filter: FilterKey): Pick<IssuesParams, 'severity' | 'dimension'> {
  if (filter === 'high' || filter === 'medium' || filter === 'low') return { severity: filter };
  if (filter === 'technical' || filter === 'aeo') return { dimension: filter };
  return {};
}

function selectedFilter(filters: IssueFilters): FilterKey {
  if (filters.severity === 'high' || filters.severity === 'medium' || filters.severity === 'low')
    return filters.severity;
  if (filters.dimension === 'technical' || filters.dimension === 'aeo') return filters.dimension;
  return 'all';
}

function filterChange(filter: FilterKey): Partial<IssueFilters> {
  const params = filterParams(filter);
  return { severity: params.severity ?? '', dimension: params.dimension ?? '' };
}

function filterCount(filter: FilterKey, summary: IssuesSummary, view: FindingView): number {
  if (filter === 'high')
    return (summary.severity_counts.high ?? 0) + (summary.severity_counts.critical ?? 0);
  if (filter === 'medium' || filter === 'low') return summary.severity_counts[filter] ?? 0;
  if (filter === 'technical' || filter === 'aeo') return summary.dimension_counts[filter] ?? 0;
  return view === 'defect' ? summary.defect_issue_type_count : summary.advisory_issue_type_count;
}

export function IssuesCatalog({ crawlId }: Readonly<{ crawlId: string }>) {
  const { cursor, filters, selectedGroupId, navigate, selectIssue } = useIssuesCatalogUrlState();
  const [occurrenceCursors, setOccurrenceCursors] = useState<string[]>([]);
  const findingView: FindingView = filters.finding_class;
  const params = useMemo(() => toIssueParams(filters, cursor, ISSUE_LIMIT), [filters, cursor]);
  const issuesQuery = useQuery(siteHealthQueries.issues(crawlId, params));
  const summary = issuesQuery.data?.summary ?? null;
  const rows = issuesQuery.data?.items ?? [];
  const selected = rows.find((issue) => issue.group_id === selectedGroupId) ?? rows[0] ?? null;
  const detailQuery = useQuery({
    ...siteHealthQueries.issue(crawlId, selected?.group_id ?? '', {
      cursor: occurrenceCursors.at(-1),
      limit: OCCURRENCE_LIMIT,
    }),
    enabled: selected !== null,
  });

  const updateFilters = (change: Partial<IssueFilters>) => {
    const changed = changeIssueFilters(filters, change);
    setOccurrenceCursors([]);
    navigate(changed.filters, changed.cursor);
  };
  const chooseGroup = (groupId: string) => {
    selectIssue(groupId);
    setOccurrenceCursors([]);
  };

  return (
    <div className="grid gap-[var(--workspace-gap)]">
      {summary ? <IssueSummary summary={summary} findingView={findingView} /> : null}
      <div className="flex flex-wrap items-center gap-2">
        <IssueSearch
          key={filters.query}
          query={filters.query}
          onApply={(query) => updateFilters({ query })}
        />
        <PageKindSelect
          value={filters.page_kind}
          onChange={(page_kind) => updateFilters({ page_kind })}
        />
        <FindingClassFilter
          value={findingView}
          summary={summary}
          onChange={(finding_class) =>
            updateFilters({ finding_class, severity: '', dimension: '' })
          }
        />
        <SegmentedControl
          value={selectedFilter(filters)}
          onChange={(value) => updateFilters(filterChange(value))}
          ariaLabel="Issue filters"
          options={FILTERS.filter(
            (item) => findingView === 'defect' || !['high', 'medium', 'low'].includes(item.key),
          ).map((item) => ({
            value: item.key,
            label: `${item.label}${summary ? ` (${filterCount(item.key, summary, findingView)})` : ''}`,
          }))}
        />
      </div>

      {issuesQuery.isError ? (
        <Alert tone="danger">Could not load issues for this crawl. Please refresh.</Alert>
      ) : issuesQuery.isLoading ? (
        <div className="grid gap-4 lg:grid-cols-2">
          <Skeleton className="h-80 w-full" />
          <Skeleton className="h-80 w-full" />
        </div>
      ) : rows.length === 0 ? (
        <p className="text-secondary py-[var(--empty-state-padding)] text-center text-sm">
          No issues match this view.
        </p>
      ) : (
        <div
          className="grid items-start gap-4 lg:grid-cols-[minmax(18rem,0.85fr)_minmax(0,1.65fr)]"
          aria-busy={issuesQuery.isFetching}
        >
          <IssueGroupList rows={rows} selectedGroupId={selected?.group_id} onSelect={chooseGroup} />
          {selected ? (
            <IssueDetailRail
              issue={selected}
              crawlId={crawlId}
              detailQuery={detailQuery}
              canPrevious={occurrenceCursors.length > 0}
              onPrevious={() => setOccurrenceCursors((values) => values.slice(0, -1))}
              onNext={() => {
                const next = detailQuery.data?.next_cursor;
                if (next) setOccurrenceCursors((values) => [...values, next]);
              }}
            />
          ) : null}
        </div>
      )}

      {rows.length > 0 ? (
        <div className="flex items-center justify-end gap-2">
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              setOccurrenceCursors([]);
              navigate(filters, null);
            }}
            disabled={!cursor}
          >
            First page
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => {
              const next = issuesQuery.data?.next_cursor;
              if (next) {
                setOccurrenceCursors([]);
                navigate(filters, next);
              }
            }}
            disabled={!issuesQuery.data?.next_cursor}
          >
            Next
          </Button>
        </div>
      ) : null}
    </div>
  );
}

function IssueSummary({
  summary,
  findingView,
}: Readonly<{ summary: IssuesSummary; findingView: FindingView }>) {
  const typeCount =
    findingView === 'defect' ? summary.defect_issue_type_count : summary.advisory_issue_type_count;
  return (
    <div className="border-border-subtle flex flex-wrap gap-x-8 gap-y-3 border-b pb-3">
      <SummaryMeasure value={typeCount} label={`${findingView} issue types`} />
      <SummaryMeasure value={summary.occurrence_count} label={`${findingView} occurrences`} />
      <SummaryMeasure value={summary.affected_url_count} label="affected URLs" />
    </div>
  );
}

function SummaryMeasure({ value, label }: Readonly<{ value: number; label: string }>) {
  return (
    <span className="flex items-baseline gap-1.5">
      <span className="text-foreground text-lg font-semibold tabular-nums">{value}</span>{' '}
      <span className="text-muted text-xs">{label}</span>
    </span>
  );
}

function FindingClassFilter({
  value,
  summary,
  onChange,
}: Readonly<{
  value: FindingView;
  summary: IssuesSummary | null;
  onChange: (value: FindingView) => void;
}>) {
  return (
    <SegmentedControl
      value={value}
      onChange={onChange}
      ariaLabel="Finding class"
      options={(['defect', 'advisory'] as const).map((view) => ({
        value: view,
        label: `${view === 'defect' ? 'Defects' : 'Advisories'}${
          summary
            ? ` (${view === 'defect' ? summary.defect_issue_type_count : summary.advisory_issue_type_count})`
            : ''
        }`,
      }))}
    />
  );
}

function IssueGroupList({
  rows,
  selectedGroupId,
  onSelect,
}: Readonly<{
  rows: SiteIssue[];
  selectedGroupId: string | undefined;
  onSelect: (groupId: string) => void;
}>) {
  return (
    <div className="border-border-subtle bg-panel divide-border-subtle divide-y overflow-hidden rounded-lg border">
      {rows.map((issue) => {
        const selected = issue.group_id === selectedGroupId;
        return (
          <Pressable
            key={issue.group_id}
            type="button"
            onClick={() => onSelect(issue.group_id)}
            aria-pressed={selected}
            className={cn(
              'focus-ring grid w-full gap-2 px-4 py-3 text-left transition-colors',
              selected ? 'bg-accent-subtle' : 'hover:bg-panel-subtle',
            )}
          >
            <span className="flex items-center justify-between gap-3">
              <IssueMetadata issue={issue} />
              <span className="text-2xs text-muted whitespace-nowrap">
                {issue.affected_url_count} {issue.affected_url_count === 1 ? 'page' : 'pages'}
              </span>
            </span>
            <span className="text-foreground text-sm font-semibold">{issueTitle(issue)}</span>
            <span className="text-secondary line-clamp-2 text-xs">{issue.description}</span>
          </Pressable>
        );
      })}
    </div>
  );
}

function IssueDetailRail({
  issue,
  crawlId,
  detailQuery,
  canPrevious,
  onPrevious,
  onNext,
}: Readonly<{
  issue: SiteIssue;
  crawlId: string;
  detailQuery: {
    data: SiteIssueDetail | undefined;
    isError: boolean;
    isLoading: boolean;
    isFetching: boolean;
  };
  canPrevious: boolean;
  onPrevious: () => void;
  onNext: () => void;
}>) {
  const detail = detailQuery.data;
  return (
    <Card
      className="lg:sticky lg:top-[var(--workspace-gap)] lg:max-h-[calc(100dvh-var(--topbar-height)-2*var(--workspace-gap))] lg:overflow-hidden"
      aria-busy={detailQuery.isFetching}
    >
      <CardContent className="flex flex-col p-0 lg:max-h-[calc(100dvh-var(--topbar-height)-2*var(--workspace-gap))]">
        {detailQuery.isFetching && !detailQuery.isLoading ? (
          <progress
            className="bg-neutral-bg [&::-webkit-progress-bar]:bg-neutral-bg [&::-webkit-progress-value]:bg-accent [&::-moz-progress-bar]:bg-accent h-0.5 w-full shrink-0 appearance-none border-0"
            aria-label="Updating issue evidence"
          />
        ) : null}
        <header className="border-border-subtle grid shrink-0 gap-3 border-b p-[var(--card-padding)]">
          <div className="flex items-start justify-between gap-[var(--workspace-gap)]">
            <div className="grid min-w-0 gap-2">
              <h2 className="text-foreground text-lg font-semibold tracking-[-0.02em]">
                {issueTitle(issue)}
              </h2>
              <IssueMetadata issue={issue} />
            </div>
            <div className="border-border-subtle grid shrink-0 gap-1 border-l pl-4 text-sm font-normal">
              <span className="text-secondary whitespace-nowrap tabular-nums">
                {issue.affected_url_count} {issue.affected_url_count === 1 ? 'page' : 'pages'}{' '}
                affected
              </span>
              {issue.page_kinds.length > 0 ? (
                <span className="text-muted flex max-w-56 flex-wrap items-center gap-1 text-xs">
                  <span>Affects</span>
                  {issue.page_kinds.map((kind, index) => (
                    <span key={kind} className="contents">
                      {index > 0 ? <span aria-hidden>·</span> : null}
                      <span>{pageKindLabel(kind)}</span>
                    </span>
                  ))}
                </span>
              ) : null}
            </div>
          </div>
          <CopyButton value={buildFixPrompt(issue)} size="sm" className="w-fit">
            Copy fix prompt
          </CopyButton>
        </header>
        <div className="content-scroll grid min-h-0 gap-[var(--workspace-gap)] p-[var(--card-padding)] lg:flex-1 lg:overflow-y-auto">
          {issue.description ? (
            <p className="text-secondary text-sm whitespace-pre-line">{issue.description}</p>
          ) : null}
          {issue.remediation ? (
            <div className="border-border-subtle bg-panel-subtle grid gap-1 rounded-lg border p-3">
              <span className="text-2xs text-muted font-medium">How to fix</span>
              <p className="text-secondary text-sm whitespace-pre-line">{issue.remediation}</p>
            </div>
          ) : null}
          <OccurrenceList
            detail={detail}
            crawlId={crawlId}
            isError={detailQuery.isError}
            isLoading={detailQuery.isLoading}
          />
        </div>
        {detail && (detail.occurrences.length > 0 || canPrevious) ? (
          <footer className="border-border-subtle bg-panel flex shrink-0 items-center justify-end gap-2 border-t p-3">
            <Button variant="secondary" size="sm" onClick={onPrevious} disabled={!canPrevious}>
              Previous
            </Button>
            <Button variant="secondary" size="sm" onClick={onNext} disabled={!detail.next_cursor}>
              Next
            </Button>
          </footer>
        ) : null}
      </CardContent>
    </Card>
  );
}

function OccurrenceList({
  detail,
  crawlId,
  isError,
  isLoading,
}: Readonly<{
  detail: SiteIssueDetail | undefined;
  crawlId: string;
  isError: boolean;
  isLoading: boolean;
}>) {
  if (isError) return <Alert tone="danger">Could not load affected URLs.</Alert>;
  if (isLoading)
    return (
      <div className="grid gap-2">
        <Skeleton className="h-6 w-full" />
        <Skeleton className="h-24 w-full" />
      </div>
    );
  if (!detail || detail.occurrences.length === 0)
    return <p className="text-secondary text-sm">No affected URLs found.</p>;
  return (
    <ul className="border-border-subtle divide-border-subtle divide-y border-y">
      {detail.occurrences.map((occurrence) => (
        <li key={occurrence.occurrence_id} className="grid gap-3 p-3">
          <Link
            href={`/site/crawls/${crawlId}/pages/${occurrence.site_url_id}`}
            className="hover:text-accent flex min-w-0 flex-col gap-0.5"
          >
            <span className="flex min-w-0 items-center gap-2">
              <span className="text-foreground truncate text-sm font-medium">
                {pageDisplayTitle(occurrence.title, occurrence.display_url)}
              </span>
              {occurrence.page_kind ? (
                <span className="text-muted shrink-0 text-xs">
                  {pageKindLabel(occurrence.page_kind)}
                </span>
              ) : null}
            </span>
            <span className="mono text-2xs text-muted truncate" title={occurrence.display_url}>
              {occurrence.display_url}
            </span>
          </Link>
          <IssueEvidence occurrence={occurrence} />
        </li>
      ))}
    </ul>
  );
}

function IssueMetadata({ issue }: Readonly<{ issue: SiteIssue }>) {
  const severityTone =
    issue.severity === 'critical' || issue.severity === 'high'
      ? 'text-danger-text'
      : issue.severity === 'medium'
        ? 'text-warning-text'
        : 'text-info-text';
  return (
    <span className="flex flex-wrap items-center gap-1.5 text-xs font-medium uppercase">
      <span className={issue.finding_class === 'defect' ? severityTone : 'text-secondary'}>
        {issue.finding_class === 'defect' ? severityLabel(issue.severity) : 'Advisory'}
      </span>
      <span className="text-muted" aria-hidden>
        ·
      </span>
      <span className={issue.dimension === 'aeo' ? 'text-accent-text' : 'text-info-text'}>
        {dimensionLabel(issue.dimension)}
      </span>
    </span>
  );
}

function buildFixPrompt(issue: SiteIssue): string {
  const lines = [
    `Fix this Site Health issue on my website: "${issueTitle(issue)}" (${dimensionLabel(issue.dimension)}, ${severityLabel(issue.severity)} severity).`,
  ];
  if (issue.description) lines.push('', 'What is wrong:', issue.description);
  if (issue.remediation) lines.push('', 'Recommended remediation:', issue.remediation);
  return lines.join('\n');
}
