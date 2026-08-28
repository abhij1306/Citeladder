'use client';

import Link from 'next/link';
import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Drawer } from '@/components/ui/drawer';
import { Label } from '@/components/ui/typography';
import { siteHealthQueries } from '@/lib/api/site-health';
import type { AeoReadiness, ReadinessCheck, ReadinessDimension } from '@/lib/api/types';
import { cn } from '@/lib/utils';

/**
 * AEO Readiness — seven dimensions of how ready the site is to be quoted.
 *
 * The previous version of this screen was a table of raw counts whose evidence
 * drawer listed one row per rule evaluation. That produced the same URL five
 * times under five ids like `aeo.answer_first`, each labelled `fail`, capped at
 * 25 so every dimension coincidentally claimed "25 evidence links". It was
 * accurate and unreadable.
 *
 * What replaced it, and why:
 *
 *  - **Pages, not evaluations.** A dimension reports how many pages it checked
 *    and how many failed at least one check. Evidence lists each failing page
 *    ONCE with the checks it failed, so nothing looks duplicated.
 *  - **Catalog titles, never rule ids.** Every check names itself the way the
 *    issue catalog does, and carries its remediation.
 *  - **Honest counts.** The bounded evidence list always renders against the
 *    true failing-page total, so a capped list never reads as the whole set.
 *  - **No composite score.** Readiness is still persisted outcomes; the client
 *    computes nothing, ranks nothing, and invents no grade.
 */

function pageLabel(url: string) {
  try {
    const parsed = new URL(url);
    return `${parsed.hostname}${parsed.pathname}`;
  } catch {
    return url;
  }
}

/** Share of applicable checks that passed. Presentation only — never persisted. */
function passShare(dimension: ReadinessDimension): number | null {
  const applicable = dimension.pass_count + dimension.fail_count;
  return applicable === 0 ? null : dimension.pass_count / applicable;
}

function meterSentence(dimension: ReadinessDimension): string {
  const pages = `${dimension.checked_page_count} checked page${dimension.checked_page_count === 1 ? '' : 's'}`;
  return dimension.fail_count === 0
    ? `All ${pages} pass`
    : `${dimension.failing_page_count} of ${pages} need work`;
}

function DimensionMeter({ dimension }: Readonly<{ dimension: ReadinessDimension }>) {
  const share = passShare(dimension);
  if (share === null) {
    return (
      <span className="text-muted text-xs">
        Not measured on any analyzed page — these checks did not apply.
      </span>
    );
  }
  return (
    <div className="grid gap-1.5">
      <div className="bg-background-alt h-1.5 w-full overflow-hidden rounded-full">
        <div
          className={cn(
            'h-full rounded-full',
            share === 1 ? 'bg-success' : share >= 0.5 ? 'bg-warning' : 'bg-danger',
          )}
          style={{ width: `${Math.round(share * 100)}%` }}
        />
      </div>
      {/* One text node, not a span sandwich: the sentence has to read as a
          sentence to a screen reader as much as to an eye. */}
      <span
        className={cn('text-xs', dimension.fail_count === 0 ? 'text-secondary' : 'text-foreground')}
      >
        {meterSentence(dimension)}
      </span>
    </div>
  );
}

function CheckRow({ check }: Readonly<{ check: ReadinessCheck }>) {
  const [open, setOpen] = useState(false);
  const failing = check.fail_count > 0;
  const applicable = check.pass_count + check.fail_count;
  const Chevron = open ? ChevronDown : ChevronRight;
  return (
    <li className="border-border-subtle border-b last:border-b-0">
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((value) => !value)}
        className="hover:bg-background-alt flex w-full items-center gap-2.5 rounded-sm py-2 pr-2 text-left transition-colors"
      >
        <Chevron className="text-muted size-3.5 shrink-0" aria-hidden />
        <span className={cn('min-w-0 flex-1 truncate text-sm', failing && 'font-medium')}>
          {check.title}
        </span>
        {applicable === 0 ? (
          <span className="text-muted shrink-0 text-xs">Did not apply</span>
        ) : failing ? (
          <span className="text-danger-text shrink-0 text-xs font-medium">
            {check.failing_page_count} page{check.failing_page_count === 1 ? '' : 's'}
          </span>
        ) : (
          <span className="text-success-text shrink-0 text-xs">Passing</span>
        )}
      </button>
      {open ? (
        <div className="text-secondary pb-3 pl-6 text-sm">
          {check.remediation || 'No remediation guidance is recorded for this check.'}
          <span className="text-subtle mt-1 block text-xs">
            {check.pass_count} passed · {check.fail_count} failed · {check.not_applicable_count} did
            not apply
          </span>
        </div>
      ) : null}
    </li>
  );
}

/**
 * Evidence sheet: one row per failing PAGE, listing that page's failed checks.
 * A right-side sheet rather than an in-card disclosure, because a dimension can
 * carry dozens of pages and expanding them inline pushed a card past the
 * viewport.
 */
function EvidenceDrawer({
  dimension,
  crawlId,
  onClose,
}: Readonly<{ dimension: ReadinessDimension | null; crawlId: string; onClose: () => void }>) {
  const shown = dimension?.evidence_pages.length ?? 0;
  const total = dimension?.failing_page_count ?? 0;
  return (
    <Drawer
      open={Boolean(dimension)}
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={dimension ? `Pages to fix — ${dimension.label}` : ''}
      description={
        dimension
          ? shown < total
            ? `Showing the ${shown} most affected of ${total} pages, worst first.`
            : `${total} page${total === 1 ? '' : 's'} failed at least one check, worst first.`
          : ''
      }
      closeLabel="Close evidence"
    >
      <ul className="divide-border-subtle divide-y">
        {(dimension?.evidence_pages ?? []).map((page) => (
          <li key={page.site_url_id} className="grid gap-1.5 py-3 first:pt-0">
            <Link
              className="text-accent-text truncate text-sm font-medium hover:underline"
              href={`/site/crawls/${crawlId}/pages/${page.site_url_id}`}
            >
              {pageLabel(page.normalized_url)}
            </Link>
            <ul className="grid gap-1">
              {page.failed_checks.map((check) => (
                <li key={check.rule_id} className="text-secondary flex items-start gap-2 text-xs">
                  <span className="bg-danger mt-1.5 size-1.5 shrink-0 rounded-full" aria-hidden />
                  {check.title}
                </li>
              ))}
            </ul>
          </li>
        ))}
      </ul>
    </Drawer>
  );
}

function DimensionCard({
  dimension,
  onOpenEvidence,
}: Readonly<{ dimension: ReadinessDimension; onOpenEvidence: () => void }>) {
  return (
    <Card>
      <CardContent className="grid content-start gap-3">
        <div className="grid gap-1">
          <h3 className="text-foreground text-heading-sm">{dimension.label}</h3>
          <p className="text-muted text-xs leading-relaxed">{dimension.description}</p>
        </div>
        <DimensionMeter dimension={dimension} />
        {dimension.checks.length > 0 ? (
          <div className="grid gap-1">
            <Label>Checks</Label>
            <ul className="grid">
              {dimension.checks.map((check) => (
                <CheckRow key={check.rule_id} check={check} />
              ))}
            </ul>
          </div>
        ) : null}
        {dimension.failing_page_count > 0 ? (
          <Button
            variant="secondary"
            size="sm"
            className="justify-self-start"
            onClick={onOpenEvidence}
          >
            View {dimension.failing_page_count} page
            {dimension.failing_page_count === 1 ? '' : 's'} to fix
          </Button>
        ) : null}
      </CardContent>
    </Card>
  );
}

function ReadinessHeader({ data }: Readonly<{ data: AeoReadiness }>) {
  const failing = data.dimensions.filter((dimension) => dimension.fail_count > 0);
  return (
    <Card>
      <CardHeader>
        <CardTitle>AEO Readiness</CardTitle>
        <CardDescription className="max-w-3xl">
          Seven things an answer engine needs from a page, checked across {data.analysis_count}{' '}
          analyzed page{data.analysis_count === 1 ? '' : 's'}.{' '}
          {failing.length === 0
            ? 'Every dimension is passing on the pages where its checks applied.'
            : `${failing.length} of ${data.dimensions.length} need work: ${failing
                .map((dimension) => dimension.label)
                .join(', ')}.`}{' '}
          These are recorded check results, not a score.
        </CardDescription>
      </CardHeader>
    </Card>
  );
}

export function AeoReadinessPanel({
  projectId,
  crawlId,
}: Readonly<{ projectId: string; crawlId: string }>) {
  const readiness = useQuery(siteHealthQueries.aeoReadiness(projectId, crawlId));
  const [evidenceKey, setEvidenceKey] = useState<string | null>(null);

  if (readiness.isLoading) {
    return (
      <p role="status" className="text-secondary text-sm">
        Loading persisted AEO evaluations…
      </p>
    );
  }
  if (readiness.isError) {
    return <Alert tone="danger">Could not load AEO Readiness.</Alert>;
  }
  if (!readiness.data || readiness.data.state === 'unavailable') {
    return (
      <Alert tone="info">
        {readiness.data?.limitations[0] ??
          'AEO Readiness appears once a crawl has finished analyzing pages.'}
      </Alert>
    );
  }

  const data = readiness.data;
  return (
    <div className="grid min-w-0 gap-4" data-testid="aeo-readiness">
      <ReadinessHeader data={data} />
      {data.limitations.length ? <Alert tone="info">{data.limitations.join(' ')}</Alert> : null}
      <div className="grid gap-4 lg:grid-cols-2">
        {data.dimensions.map((dimension) => (
          <DimensionCard
            key={dimension.key}
            dimension={dimension}
            onOpenEvidence={() => setEvidenceKey(dimension.key)}
          />
        ))}
      </div>
      <EvidenceDrawer
        dimension={data.dimensions.find((dimension) => dimension.key === evidenceKey) ?? null}
        crawlId={crawlId}
        onClose={() => setEvidenceKey(null)}
      />
      <p className="text-subtle text-xs">
        Taxonomy {data.taxonomy_version} · Analyzer {data.analyzer_version}
      </p>
    </div>
  );
}
