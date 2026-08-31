'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { CsvImportTrigger } from '@/components/ui/csv-import';
import { Label, Metric } from '@/components/ui/typography';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import { commerceApi } from '@/lib/api/commerce';
import { queryKeys } from '@/lib/api/query-keys';
import { siteHealthApi, siteHealthQueries } from '@/lib/api/site-health';
import {
  PLACEHOLDER,
  crawlBadgeValue,
  crawlPollInterval,
  statusLabel,
} from '@/lib/site-health/status';

import type { SiteCrawl } from '@/lib/api/types';

import type { CommerceQueries } from './commerce-queries';

/** One metric: micro-label above a tabular value. The row's only unit. */
function Stat({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <div className="flex flex-col gap-0.5">
      <Label>{label}</Label>
      {value === PLACEHOLDER ? <UnavailableValue state="not_measured" /> : <Metric>{value}</Metric>}
    </div>
  );
}

/**
 * Pages analyzed over the crawl's own inventory.
 *
 * The denominator is the site inventory the crawl holds, which is never below
 * what it analyzed — reading it off the discovery FETCH counter is what
 * rendered "49/1". The client still floors it, because a crawl whose counters
 * are mid-flight must not print a fraction that reads backwards.
 */
/** The dashboard's crawl, exactly as the query returns it (nullable). */
type SiteHealthCrawl = SiteCrawl | null;

function analyzedLabel(crawl: SiteHealthCrawl): string {
  if (!crawl) return PLACEHOLDER;
  const known = crawl.total_url_count ?? crawl.visible_url_count;
  return `${crawl.analyzed_count}/${Math.max(known, crawl.analyzed_count)}`;
}

/** In-flight projection work, or '' when the queue is idle. */
function projectionLabel(tasks: Record<string, number> | undefined): string {
  const pending = Object.entries(tasks ?? {})
    .filter(([status, count]) => count > 0 && status !== 'succeeded')
    .reduce((total, [, count]) => total + count, 0);
  return pending ? `${pending} projecting` : '';
}

/** The catalog-wide metrics half of the toolbar: counts, crawl, queue. */
function CatalogStats({
  counts,
  crawl,
  projecting,
}: Readonly<{
  counts: CommerceQueries['catalog']['data'];
  crawl: SiteHealthCrawl;
  projecting: string;
}>) {
  return (
    <div className="flex flex-wrap items-center gap-x-8 gap-y-4">
      <Stat label="Products" value={counts ? `${counts.products.length}` : PLACEHOLDER} />
      <Stat label="Categories" value={counts ? `${counts.categories.length}` : PLACEHOLDER} />
      <Stat label="Pages analyzed" value={analyzedLabel(crawl)} />
      <div className="flex flex-col items-start gap-0.5">
        <Label>Site Health</Label>
        {crawl ? (
          <Badge variant="run-status" value={crawlBadgeValue(crawl.status)}>
            {statusLabel(crawl.status)}
          </Badge>
        ) : (
          <Badge>No crawl yet</Badge>
        )}
      </div>
      {projecting ? (
        <div className="flex flex-col items-start gap-0.5">
          <Label>Projection</Label>
          <Badge variant="status" value="info">
            {projecting}
          </Badge>
        </div>
      ) : null}
    </div>
  );
}

/**
 * Catalog-WIDE state and catalog-wide actions, and nothing target-scoped.
 *
 * ONE row: metrics left, actions right — the same toolbar shape every other
 * screen uses. It carries no title and no description. The screen already
 * names itself in the nav, and the two sentences that used to sit here
 * ("Site Health observations project automatically…") explained a mechanism
 * the numbers show directly, while pushing the actions down a line and
 * leaving the entire right half of the card empty.
 */
export function CatalogHeader({
  projectId,
  query,
}: Readonly<{ projectId: string; query: CommerceQueries['catalog'] }>) {
  const client = useQueryClient();
  const [result, setResult] = useState('');
  const dashboard = useQuery({
    ...siteHealthQueries.dashboard(projectId),
    refetchInterval: (state) => {
      const crawl = state.state.data?.crawl;
      return crawl ? crawlPollInterval(crawl) : false;
    },
  });
  const invalidateCatalog = () =>
    client.invalidateQueries({ queryKey: queryKeys.commerce.catalog(projectId) });
  const importCatalog = useMutation({
    mutationFn: async (file: File) =>
      commerceApi.importCatalog(projectId, await file.text(), file.name),
    onSuccess: async (data) => {
      setResult(
        `${data.created} created, ${data.updated} updated, ${data.unchanged} unchanged, ${data.rejected} rejected`,
      );
      await invalidateCatalog();
    },
  });
  const discover = useMutation({
    mutationFn: () => siteHealthApi.createCrawl({ project_id: projectId }),
    onSuccess: async () => {
      await Promise.all([dashboard.refetch(), query.refetch()]);
    },
  });
  const crawl = dashboard.data?.crawl ?? null;
  const counts = query.data;
  const projecting = projectionLabel(counts?.projection_tasks);
  return (
    <Card>
      <CardContent className="flex flex-wrap items-center justify-between gap-x-8 gap-y-4">
        <CatalogStats counts={counts} crawl={crawl} projecting={projecting} />
        <div className="flex flex-wrap items-center gap-2">
          <CsvImportTrigger
            accessibleLabel="Import catalog CSV"
            pending={importCatalog.isPending}
            onSelect={(file) => importCatalog.mutate(file)}
          />
          <Button asChild variant="ghost">
            <a href="/site" target="_blank" rel="noreferrer">
              Open Site Health
            </a>
          </Button>
          <Button
            disabled={discover.isPending || dashboard.isPending}
            onClick={() =>
              crawl ? void Promise.all([dashboard.refetch(), query.refetch()]) : discover.mutate()
            }
          >
            {crawl ? 'Refresh from Site Health' : 'Run Site Health crawl'}
          </Button>
        </div>
        {result ? <p className="text-secondary w-full text-sm">{result}</p> : null}
        {importCatalog.isError ? (
          <Alert className="w-full" tone="danger">
            The catalog import failed.
          </Alert>
        ) : null}
        {discover.isError || dashboard.isError ? (
          <Alert className="w-full" tone="danger">
            Site Health progress could not be refreshed.
          </Alert>
        ) : null}
      </CardContent>
    </Card>
  );
}
