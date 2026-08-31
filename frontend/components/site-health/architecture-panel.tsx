'use client';

import Link from 'next/link';
import { Fragment, useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, Link2, ListTree } from 'lucide-react';

import { PageKindBadge } from '@/components/site-health/page-kind-badge';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Pressable } from '@/components/ui/pressable';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRecordMetricCell,
  TableRow,
} from '@/components/ui/table';
import { siteHealthQueries } from '@/lib/api/site-health';
import type {
  ArchitectureNode,
  ArchitecturePageKind,
  CoverageState,
  SiteArchitecture,
} from '@/lib/api/types';
import { PLACEHOLDER } from '@/lib/site-health/status';

const COVERAGE_LABELS: Record<CoverageState, string> = {
  complete: 'Complete coverage',
  partial: 'Partial coverage',
  unknown: 'Coverage unknown',
};

const DEPTH_LABELS = {
  depth_0: 'Depth 0',
  depth_1: 'Depth 1',
  depth_2: 'Depth 2',
  depth_3_plus: 'Depth 3+',
} as const;

const PARENT_SOURCE_LABELS: Record<ArchitectureNode['parent_source'], string> = {
  breadcrumb: 'Breadcrumb',
  explicit_structure: 'Explicit structure',
  url_parent: 'URL parent',
  unknown: 'Root or unresolved',
};

function formatPercentage(value: number | null): string {
  return value === null ? PLACEHOLDER : `${Math.round(value * 100)}%`;
}

function median(values: number[]): number | null {
  if (values.length === 0) return null;
  const ordered = [...values].sort((left, right) => left - right);
  const middle = Math.floor(ordered.length / 2);
  return ordered.length % 2 === 0
    ? (ordered[middle - 1]! + ordered[middle]!) / 2
    : ordered[middle]!;
}

export function ArchitecturePanel({
  projectId,
  crawlId,
}: Readonly<{ projectId: string; crawlId?: string }>) {
  const architecture = useQuery(siteHealthQueries.architecture(projectId, crawlId));

  if (architecture.isLoading) {
    return (
      <output className="grid gap-4" aria-label="Loading the observed architecture">
        <Skeleton className="h-28 w-full" />
        <Skeleton className="h-72 w-full" />
      </output>
    );
  }
  if (architecture.isError) return <Alert tone="danger">Could not load Architecture.</Alert>;
  if (!architecture.data || architecture.data.state === 'unavailable') {
    return (
      <Alert tone="info">
        {architecture.data?.limitations[0] ??
          'Page kinds appear once a crawl has finished and its structure has been derived.'}
      </Alert>
    );
  }
  return <ArchitectureLedger data={architecture.data} />;
}

function pagesByKind(nodes: ArchitectureNode[]): Map<string, ArchitectureNode[]> {
  const grouped = new Map<string, ArchitectureNode[]>();
  for (const node of nodes) {
    const pages = grouped.get(node.page_kind);
    if (pages) pages.push(node);
    else grouped.set(node.page_kind, [node]);
  }
  for (const pages of grouped.values()) {
    pages.sort((left, right) => left.url.localeCompare(right.url));
  }
  return grouped;
}

function ArchitectureLedger({ data }: Readonly<{ data: SiteArchitecture }>) {
  const grouped = useMemo(() => pagesByKind(data.nodes), [data.nodes]);
  const pageKinds = useMemo(
    () => [...data.page_kinds].sort((left, right) => right.page_count - left.page_count),
    [data.page_kinds],
  );
  const depths = data.nodes.flatMap((node) =>
    node.depth_from_home === null ? [] : [node.depth_from_home],
  );
  const duplicatePages = pageKinds.reduce(
    (total, pageKind) => total + pageKind.duplicate_metadata_count,
    0,
  );

  return (
    <div className="grid min-w-0 gap-[var(--workspace-gap)]" data-testid="site-architecture">
      <ArchitectureEvidence data={data} />
      <Card>
        <CardHeader className="gap-2">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="grid gap-1">
              <CardTitle className="text-lg">Page kinds</CardTitle>
              <CardDescription>
                URLs grouped by their persisted structural purpose for this crawl.
              </CardDescription>
            </div>
            <Badge
              variant="status"
              value={data.coverage_state === 'complete' ? 'success' : 'warning'}
            >
              {COVERAGE_LABELS[data.coverage_state]}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="grid gap-3 pt-1">
          <ArchitectureMetrics
            pageKinds={pageKinds.length}
            pages={data.page_count}
            medianDepth={median(depths)}
            duplicatePages={duplicatePages}
            orphanCount={data.internal_linking.orphan_page_count}
            coverageState={data.coverage_state}
          />
          {data.limitations.map((limitation) => (
            <Alert key={limitation} tone="info">
              {limitation}
            </Alert>
          ))}
          {pageKinds.length === 0 ? (
            <p className="text-secondary text-sm">No page kinds were measured.</p>
          ) : (
            <PageKindTable pageKinds={pageKinds} grouped={grouped} crawlId={data.crawl_id} />
          )}
        </CardContent>
      </Card>
      <HierarchyCard nodes={data.nodes} crawlId={data.crawl_id} />
    </div>
  );
}

function ArchitectureMetrics({
  pageKinds,
  pages,
  medianDepth,
  duplicatePages,
  orphanCount,
  coverageState,
}: Readonly<{
  pageKinds: number;
  pages: number;
  medianDepth: number | null;
  duplicatePages: number;
  orphanCount: number | null;
  coverageState: CoverageState;
}>) {
  const items = [
    ['Page kinds', String(pageKinds)],
    ['Pages', String(pages)],
    ['Median depth', medianDepth === null ? PLACEHOLDER : String(medianDepth)],
    ['Duplicate metadata', String(duplicatePages)],
    [
      'Orphaned pages',
      orphanCount === null ? orphanCoverageExplanation(coverageState) : String(orphanCount),
    ],
  ];
  return (
    <dl className="border-border-subtle grid grid-cols-2 border-y sm:grid-cols-3 lg:grid-cols-5">
      {items.map(([label, value]) => (
        <div
          key={label}
          className="border-border-subtle grid gap-0.5 border-b px-3 py-2 last:border-b-0 sm:border-r sm:border-b-0 sm:last:border-r-0"
        >
          <dt className="text-muted text-xs font-medium tracking-[0.06em] uppercase">{label}</dt>
          <dd
            className={
              value.startsWith('Count withheld')
                ? 'text-muted text-xs font-normal'
                : 'text-foreground text-2xl font-medium tabular-nums'
            }
          >
            {value === PLACEHOLDER ? <UnavailableValue state="not_measured" /> : value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

function PageKindTable({
  pageKinds,
  grouped,
  crawlId,
}: Readonly<{
  pageKinds: ArchitecturePageKind[];
  grouped: Map<string, ArchitectureNode[]>;
  crawlId: string | null;
}>) {
  const [openKind, setOpenKind] = useState<string | null>(null);
  return (
    <Table className="block md:table" wrapperClassName="overflow-hidden md:overflow-auto">
      <TableHeader className="hidden md:table-header-group">
        <TableRow>
          <TableHead>Page kind</TableHead>
          <TableHead numeric>Pages</TableHead>
          <TableHead numeric>Median depth</TableHead>
          <TableHead numeric>Indexable</TableHead>
          <TableHead numeric>Duplicate metadata</TableHead>
          <TableHead numeric>Orphaned</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody className="block md:table-row-group">
        {pageKinds.map((pageKind) => {
          const open = openKind === pageKind.page_kind;
          const pages = grouped.get(pageKind.page_kind) ?? [];
          const Chevron = open ? ChevronDown : ChevronRight;
          return (
            <Fragment key={pageKind.page_kind}>
              <TableRow className="grid h-auto grid-cols-1 py-2 md:table-row md:h-[var(--table-row-height)] md:py-0">
                <TableCell className="block border-b-0 px-4 py-1 md:table-cell md:border-b md:px-[var(--table-cell-padding-x)] md:py-[var(--table-cell-padding-y)]">
                  <Pressable
                    type="button"
                    aria-expanded={open}
                    onClick={() => setOpenKind(open ? null : pageKind.page_kind)}
                    className="inline-flex min-h-11 w-auto items-center gap-2 text-left md:min-h-9"
                  >
                    <Chevron className="text-muted size-4 shrink-0" aria-hidden />
                    <PageKindBadge pageKind={pageKind.page_kind} className="text-xs" />
                  </Pressable>
                </TableCell>
                <TableRecordMetricCell label="Pages">{pageKind.page_count}</TableRecordMetricCell>
                <TableRecordMetricCell label="Median depth">
                  {pageKind.median_depth ?? <UnavailableValue state="not_measured" />}
                </TableRecordMetricCell>
                <TableRecordMetricCell label="Indexable">
                  {pageKind.indexable_count} / {pageKind.page_count}
                </TableRecordMetricCell>
                <TableRecordMetricCell label="Duplicate metadata">
                  {pageKind.duplicate_metadata_count}
                </TableRecordMetricCell>
                <TableRecordMetricCell label="Orphaned">
                  {pageKind.orphan_count ?? <UnavailableValue state="not_measured" />}
                </TableRecordMetricCell>
              </TableRow>
              {open ? <PageKindPages pages={pages} crawlId={crawlId} /> : null}
            </Fragment>
          );
        })}
      </TableBody>
    </Table>
  );
}

function PageKindPages({
  pages,
  crawlId,
}: Readonly<{ pages: ArchitectureNode[]; crawlId: string | null }>) {
  return (
    <TableRow className="bg-background-alt hover:bg-background-alt block h-auto md:table-row md:h-[var(--table-row-height)]">
      <TableCell colSpan={6} className="block py-3 md:table-cell">
        {pages.length === 0 ? (
          <p className="text-secondary text-sm">No projected URLs are available for this kind.</p>
        ) : (
          <ul className="content-scroll grid max-h-64 gap-1.5 overflow-y-auto overscroll-contain pr-2 pl-6">
            {pages.map((page) => (
              <li key={page.site_url_id} className="min-w-0">
                {crawlId ? (
                  <Link
                    href={`/site/crawls/${crawlId}/pages/${page.site_url_id}`}
                    className="text-accent-text min-w-0 truncate text-sm hover:underline"
                    title={page.url}
                  >
                    {page.url}
                  </Link>
                ) : (
                  <span className="text-foreground min-w-0 truncate text-sm">{page.url}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </TableCell>
    </TableRow>
  );
}

function nodesByParent(nodes: ArchitectureNode[]): Map<string | null, ArchitectureNode[]> {
  const nodeIds = new Set(nodes.map((node) => node.site_url_id));
  const grouped = new Map<string | null, ArchitectureNode[]>();
  for (const node of nodes) {
    const parentId =
      node.parent_site_url_id &&
      node.parent_site_url_id !== node.site_url_id &&
      nodeIds.has(node.parent_site_url_id)
        ? node.parent_site_url_id
        : null;
    const siblings = grouped.get(parentId);
    if (siblings) siblings.push(node);
    else grouped.set(parentId, [node]);
  }
  for (const siblings of grouped.values()) {
    siblings.sort((left, right) => left.url.localeCompare(right.url));
  }
  return grouped;
}

function HierarchyCard({
  nodes,
  crawlId,
}: Readonly<{ nodes: ArchitectureNode[]; crawlId: string | null }>) {
  const grouped = useMemo(() => nodesByParent(nodes), [nodes]);
  const roots = grouped.get(null) ?? [];
  return (
    <Card>
      <CardHeader className="gap-1">
        <CardTitle>Observed hierarchy</CardTitle>
        <CardDescription>
          Persisted parent relationships from breadcrumbs, explicit structure, or a safe URL parent.
          Unresolved pages remain at the root.
        </CardDescription>
      </CardHeader>
      <CardContent className="pt-0">
        {roots.length === 0 ? (
          <p className="text-secondary text-sm">No hierarchy nodes were measured.</p>
        ) : (
          <section
            className="content-scroll max-h-96 overflow-y-auto overscroll-contain pr-2"
            aria-label="Observed hierarchy pages"
          >
            <HierarchyList nodes={roots} grouped={grouped} crawlId={crawlId} />
          </section>
        )}
      </CardContent>
    </Card>
  );
}

function HierarchyList({
  nodes,
  grouped,
  crawlId,
}: Readonly<{
  nodes: ArchitectureNode[];
  grouped: Map<string | null, ArchitectureNode[]>;
  crawlId: string | null;
}>) {
  return (
    <ul className="border-border-subtle grid gap-2 border-l pl-4">
      {nodes.map((node) => {
        const children = grouped.get(node.site_url_id) ?? [];
        return (
          <li key={node.site_url_id} className="grid min-w-0 gap-2">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              {crawlId ? (
                <Link
                  href={`/site/crawls/${crawlId}/pages/${node.site_url_id}`}
                  className="text-accent-text min-w-0 text-sm [overflow-wrap:anywhere] hover:underline"
                >
                  {node.url}
                </Link>
              ) : (
                <span className="text-foreground min-w-0 text-sm [overflow-wrap:anywhere]">
                  {node.url}
                </span>
              )}
              <PageKindBadge pageKind={node.page_kind} />
              <span className="text-muted text-xs">{PARENT_SOURCE_LABELS[node.parent_source]}</span>
            </div>
            {children.length > 0 ? (
              <HierarchyList nodes={children} grouped={grouped} crawlId={crawlId} />
            ) : null}
          </li>
        );
      })}
    </ul>
  );
}

function ArchitectureEvidence({ data }: Readonly<{ data: SiteArchitecture }>) {
  const linking = data.internal_linking;
  return (
    <div className="grid gap-[var(--workspace-gap)] md:grid-cols-2">
      <Card>
        <CardHeader className="flex-row items-center gap-2 pb-2">
          <Link2 className="text-accent-text size-4" aria-hidden />
          <CardTitle>Internal linking</CardTitle>
        </CardHeader>
        <CardContent className="grid grid-cols-3 gap-4 pt-2">
          <EvidenceMetric label="Internal links" value={String(linking.internal_link_count)} />
          <EvidenceMetric
            label="Have incoming links"
            value={formatPercentage(linking.pages_with_incoming_percentage)}
            supporting={`${linking.pages_with_incoming_count} pages`}
          />
          <EvidenceMetric
            label="Orphaned pages"
            value={
              linking.orphan_page_count === null
                ? orphanCoverageExplanation(data.coverage_state)
                : String(linking.orphan_page_count)
            }
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="flex-row items-center gap-2 pb-2">
          <ListTree className="text-accent-text size-4" aria-hidden />
          <CardTitle>Structure depth</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3 pt-2">
          {data.structure_depth.buckets.map((bucket) => (
            <div key={bucket.key} className="grid grid-cols-[4.5rem_1fr_auto] items-center gap-3">
              <span className="text-secondary text-xs">{DEPTH_LABELS[bucket.key]}</span>
              <div className="bg-background-alt h-1.5 overflow-hidden rounded-full">
                <div
                  className="bg-accent h-full rounded-full"
                  style={{ width: `${Math.round((bucket.percentage ?? 0) * 100)}%` }}
                />
              </div>
              <span className="text-foreground min-w-16 text-right text-xs font-medium tabular-nums">
                {bucket.page_count} ({formatPercentage(bucket.percentage)})
              </span>
            </div>
          ))}
          {data.structure_depth.unmeasured_page_count > 0 ? (
            <p className="text-muted text-xs">
              {data.structure_depth.unmeasured_page_count} pages have no measured depth.
            </p>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}

function orphanCoverageExplanation(coverageState: CoverageState): string {
  return coverageState === 'partial'
    ? 'Count withheld · partial coverage'
    : 'Count withheld · coverage unknown';
}

function EvidenceMetric({
  label,
  value,
  supporting,
}: Readonly<{ label: string; value: string; supporting?: string }>) {
  return (
    <div className="grid content-start gap-1">
      <span className="text-muted text-xs font-medium tracking-[0.06em] uppercase">{label}</span>
      {value === PLACEHOLDER ? (
        <UnavailableValue state="not_measured" />
      ) : value.startsWith('Count withheld') ? (
        <span className="text-muted text-xs leading-4">{value}</span>
      ) : (
        <span className="mono text-foreground text-2xl font-medium tracking-[-0.02em] tabular-nums">
          {value}
        </span>
      )}
      {supporting ? <span className="text-muted text-xs">{supporting}</span> : null}
    </div>
  );
}
