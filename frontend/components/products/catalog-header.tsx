'use client';

import { useRef, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { commerceApi } from '@/lib/api/commerce';
import { queryKeys } from '@/lib/api/query-keys';
import { siteHealthApi, siteHealthQueries } from '@/lib/api/site-health';
import { crawlPollInterval } from '@/lib/site-health/status';

import type { CommerceQueries } from './commerce-queries';

function projectionSummary(tasks: Record<string, number> | undefined) {
  const entries = Object.entries(tasks ?? {}).filter(([, count]) => count > 0);
  return entries.length
    ? entries.map(([status, count]) => `${count} ${status}`).join(' · ')
    : 'no projection tasks yet';
}

/**
 * Catalog-WIDE state and catalog-wide actions, and nothing target-scoped.
 *
 * The old header stacked crawl progress, projection counts and the import
 * result as three separate full-width paragraphs under a button row, and each
 * tab restated its own version of the same context. One line, one toolbar,
 * one place.
 */
export function CatalogHeader({
  projectId,
  query,
}: Readonly<{ projectId: string; query: CommerceQueries['catalog'] }>) {
  const client = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement>(null);
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
  const crawl = dashboard.data?.crawl;
  const counts = query.data;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Commerce</CardTitle>
        <CardDescription>
          Site Health observations project automatically. CSV and explicit edits retain field-level
          authority.
        </CardDescription>
        <p className="text-secondary text-sm">
          {counts
            ? `${counts.products.length} products · ${counts.categories.length} categories · `
            : ''}
          {crawl
            ? `crawl ${crawl.analyzed_count}/${crawl.total_url_count ?? crawl.visible_url_count} analyzed, ${crawl.status}`
            : 'no Site Health crawl yet'}
          {' · '}
          {projectionSummary(counts?.projection_tasks)}
          {result ? ` · ${result}` : ''}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <Button
            disabled={discover.isPending || dashboard.isPending}
            onClick={() =>
              crawl ? void Promise.all([dashboard.refetch(), query.refetch()]) : discover.mutate()
            }
          >
            {crawl ? 'Refresh from Site Health' : 'Discover from Site Health'}
          </Button>
          <Button
            variant="secondary"
            disabled={importCatalog.isPending}
            onClick={() => fileInputRef.current?.click()}
          >
            {importCatalog.isPending ? 'Importing…' : 'Import CSV'}
          </Button>
          <a className="text-link text-sm" href="/site" target="_blank" rel="noreferrer">
            Open Site Health
          </a>
        </div>
        <input
          ref={fileInputRef}
          aria-label="Import catalog CSV"
          type="file"
          accept=".csv,text/csv"
          className="sr-only"
          disabled={importCatalog.isPending}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.currentTarget.value = '';
            if (file) importCatalog.mutate(file);
          }}
        />
        {importCatalog.isError ? <Alert tone="danger">The catalog import failed.</Alert> : null}
        {discover.isError || dashboard.isError ? (
          <Alert tone="danger">Site Health progress could not be refreshed.</Alert>
        ) : null}
      </CardHeader>
    </Card>
  );
}
