'use client';

import Link from 'next/link';
import { useMemo, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { PageKindBadge } from '@/components/site-health/page-kind-badge';
import { siteHealthQueries } from '@/lib/api/site-health';
import type {
  ArchitectureFamily,
  ArchitectureNode,
  CoverageState,
  SiteArchitecture,
} from '@/lib/api/types';
import { downloadCrawlExport } from '@/lib/site-health/download';
import { PLACEHOLDER } from '@/lib/site-health/status';
import { cn } from '@/lib/utils';

/**
 * Architecture tab — the crawl's page families, each expanding to its URLs.
 *
 * This deliberately shows one thing. An earlier version also rendered an
 * observed hierarchy tree and a "site profile" block (archetype, expected
 * structures, coverage prose); both described the analysis rather than the
 * site, and neither answered the question someone opens this tab with — *what
 * kinds of pages does my site have, and which URLs are they?* Families answer
 * exactly that, so the tree and profile are gone.
 *
 * One honesty rule survives from that removal and is load-bearing: a crawl that
 * did not prove it saw the whole site says so, once, at the top, and its orphan
 * counts stay unmeasured. A partial crawl cannot prove absence.
 */

const COVERAGE_LABELS: Record<CoverageState, string> = {
  complete: 'Complete coverage',
  partial: 'Partial coverage',
  unknown: 'Coverage unknown',
};

export function ArchitecturePanel({
  projectId,
  crawlId,
}: Readonly<{ projectId: string; crawlId?: string }>) {
  const architecture = useQuery(siteHealthQueries.architecture(projectId, crawlId));

  if (architecture.isLoading) {
    return (
      <div
        className="grid gap-4"
        // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- output only permits phrasing content; this live region contains block skeletons.
        role="status"
        aria-label="Loading the observed architecture"
      >
        <Skeleton className="h-24 w-full" />
        <Skeleton className="h-64 w-full" />
      </div>
    );
  }
  if (architecture.isError) return <Alert tone="danger">Could not load Architecture.</Alert>;
  if (!architecture.data || architecture.data.state === 'unavailable') {
    return (
      <Alert tone="info">
        {architecture.data?.limitations[0] ??
          'Page families appear once a crawl has finished and its structure has been derived.'}
      </Alert>
    );
  }

  return <FamiliesCard data={architecture.data} />;
}

/** Group the projected pages under the family the backend assigned each one. */
function pagesByFamily(nodes: ArchitectureNode[]): Map<string, ArchitectureNode[]> {
  const grouped = new Map<string, ArchitectureNode[]>();
  for (const node of nodes) {
    const pages = grouped.get(node.family);
    if (pages) pages.push(node);
    else grouped.set(node.family, [node]);
  }
  for (const pages of grouped.values()) {
    pages.sort((left, right) => left.url.localeCompare(right.url));
  }
  return grouped;
}

function FamiliesCard({ data }: Readonly<{ data: SiteArchitecture }>) {
  const grouped = useMemo(() => pagesByFamily(data.nodes), [data.nodes]);
  const families = useMemo(
    () => [...data.families].sort((left, right) => right.url_count - left.url_count),
    [data.families],
  );
  return (
    <div className="grid min-w-0 gap-4" data-testid="site-architecture">
      <Card>
        <CardHeader>
          <CardTitle>Page families</CardTitle>
          <CardDescription className="max-w-3xl">
            The {data.page_count} page{data.page_count === 1 ? '' : 's'} this crawl analyzed,
            grouped by URL pattern. Open a family to see its pages.
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-3 pt-0">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <Badge
              variant="status"
              value={data.coverage_state === 'complete' ? 'success' : 'warning'}
            >
              {COVERAGE_LABELS[data.coverage_state]}
            </Badge>
            {data.crawl_id ? <TreeExportButton crawlId={data.crawl_id} /> : null}
          </div>
          {data.limitations.map((limitation) => (
            <Alert key={limitation} tone="info">
              {limitation}
            </Alert>
          ))}
          {families.length === 0 ? (
            <p className="text-secondary text-sm">No page families were observed.</p>
          ) : (
            <ul className="border-border-subtle grid rounded-md border">
              {families.map((family) => (
                <FamilyRow
                  key={family.family}
                  family={family}
                  pages={grouped.get(family.family) ?? []}
                  crawlId={data.crawl_id}
                />
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

function FamilyRow({
  family,
  pages,
  crawlId,
}: Readonly<{ family: ArchitectureFamily; pages: ArchitectureNode[]; crawlId: string | null }>) {
  const [open, setOpen] = useState(false);
  const Chevron = open ? ChevronDown : ChevronRight;
  const kinds = Object.entries(family.page_kind_distribution).sort(
    ([, left], [, right]) => right - left,
  );
  return (
    <li className="border-border-subtle border-b last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="hover:bg-background-alt flex w-full items-center gap-3 px-3 py-2.5 text-left transition-colors"
      >
        <Chevron className="text-muted size-4 shrink-0" aria-hidden />
        <span
          className="mono text-foreground min-w-0 flex-1 truncate text-sm"
          title={family.family}
        >
          {family.family}
        </span>
        <span className="hidden shrink-0 items-center gap-1 sm:flex">
          {kinds.map(([kind, count]) => (
            <span key={kind} className="flex items-center gap-1">
              <PageKindBadge pageKind={kind} />
              <span className="mono text-2xs text-muted">{count}</span>
            </span>
          ))}
        </span>
        <span className="mono text-secondary shrink-0 text-xs tabular-nums">
          {family.url_count} URL{family.url_count === 1 ? '' : 's'}
        </span>
      </button>
      {open ? (
        <div className="border-border-subtle bg-background-alt border-t px-3 py-2.5">
          <FamilyFacts family={family} />
          {pages.length === 0 ? (
            <p className="text-secondary text-sm">
              This family&apos;s pages are outside the projected set.
            </p>
          ) : (
            <ul className="grid gap-0.5">
              {pages.map((page) => (
                <li key={page.site_url_id} className="flex min-w-0 items-center gap-2">
                  {crawlId ? (
                    <Link
                      href={`/site/crawls/${crawlId}/pages/${page.site_url_id}`}
                      className="mono text-accent-text min-w-0 truncate text-xs hover:underline"
                      title={page.url}
                    >
                      {page.url}
                    </Link>
                  ) : (
                    <span className="mono text-foreground min-w-0 truncate text-xs">
                      {page.url}
                    </span>
                  )}
                  <PageKindBadge pageKind={page.page_kind || null} />
                </li>
              ))}
            </ul>
          )}
        </div>
      ) : null}
    </li>
  );
}

function FamilyFacts({ family }: Readonly<{ family: ArchitectureFamily }>) {
  const facts = [
    { label: 'Indexable', value: `${family.indexable_count} / ${family.url_count}` },
    {
      label: 'Median depth',
      value: family.median_depth === null ? PLACEHOLDER : String(family.median_depth),
    },
    {
      label: 'Duplicate metadata',
      value: `${Math.round(family.metadata_duplication_rate * 100)}%`,
      warn: family.metadata_duplication_rate > 0,
    },
    {
      // Null unless the crawl proved it reached every page — an orphan count is
      // an absence claim, and a partial crawl cannot make one.
      label: 'Orphans',
      value: family.orphan_count === null ? PLACEHOLDER : String(family.orphan_count),
    },
  ];
  return (
    <dl className="mb-2.5 flex flex-wrap gap-x-6 gap-y-1">
      {facts.map((fact) => (
        <div key={fact.label} className="flex items-baseline gap-1.5">
          <dt className="text-muted text-2xs">{fact.label}</dt>
          <dd
            className={cn(
              'mono text-xs font-medium',
              fact.warn ? 'text-warning-text' : 'text-foreground',
            )}
          >
            {fact.value}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/**
 * Markdown is where an ASCII tree genuinely belongs, so the structural export
 * stays available here even though the screen itself no longer draws a tree.
 */
function TreeExportButton({ crawlId }: Readonly<{ crawlId: string }>) {
  const [exporting, setExporting] = useState(false);
  const [failed, setFailed] = useState(false);
  const run = async () => {
    setExporting(true);
    setFailed(false);
    try {
      await downloadCrawlExport(crawlId, 'md', 'architecture');
    } catch {
      setFailed(true);
    } finally {
      setExporting(false);
    }
  };
  return (
    <div className="flex items-center gap-3">
      {failed ? <span className="text-danger-text text-xs">Export failed. Try again.</span> : null}
      <Button variant="secondary" size="sm" onClick={run} disabled={exporting}>
        {exporting ? 'Exporting…' : 'Export structure (Markdown)'}
      </Button>
    </div>
  );
}
