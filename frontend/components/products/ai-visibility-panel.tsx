'use client';

import Link from 'next/link';
import { ExternalLink, PackageSearch, Play } from 'lucide-react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { EmptyState } from '@/components/ui/empty-state';
import { httpErrorStatus } from '@/lib/api/errors';
import { productsApi } from '@/lib/api/products';
import type { ProductVisibility } from '@/lib/api/types';
import { formatAvgRank, formatPercent } from '@/lib/products/catalog';
import type { useProductVisibilityQueries } from '@/lib/products/use-products-screen';

import { EngineFilterDropdown } from './engine-filter-dropdown';
import { RunSelectorDropdown } from './run-selector-dropdown';

type VisibilityQueries = ReturnType<typeof useProductVisibilityQueries>;
type CitedSource =
  ProductVisibility['citation_comparison']['categories'][number]['cited_sources'][number];

function VisibilityResults({
  projectId,
  queries,
  visibility,
}: Readonly<{
  projectId: string;
  queries: VisibilityQueries;
  visibility: ProductVisibility;
}>) {
  const categories = [...new Set(visibility.products.map((product) => product.category))].sort(
    (left, right) => left.localeCompare(right),
  );

  return (
    <div className="grid gap-4" data-testid="commerce-visibility-panel">
      <div className="flex flex-wrap items-center gap-2">
        <RunSelectorDropdown
          runOptions={queries.runOptions}
          activeRunId={queries.activeRunId}
          selectRun={queries.selectRun}
        />
        <EngineFilterDropdown engine={queries.engine} onChange={queries.setEngine} />
        <Button asChild variant="ghost" size="sm" className="ml-auto">
          <a
            href={productsApi.exportCsvUrl(projectId, {
              audit_id: queries.activeRunId ?? undefined,
              engine: queries.engineParam,
            })}
            download
          >
            Export CSV
          </a>
        </Button>
      </div>
      <ProductVisibilityTable visibility={visibility} categories={categories} />
      <CompetitorAnalysis visibility={visibility} />
      <CitationComparison visibility={visibility} />
    </div>
  );
}

function ProductVisibilityTable({
  visibility,
  categories,
}: Readonly<{ visibility: ProductVisibility; categories: string[] }>) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>SKU visibility</CardTitle>
        <CardDescription>Observed performance in the selected persisted audit.</CardDescription>
      </CardHeader>
      <CardContent className="overflow-x-auto p-0">
        <table className="w-full min-w-[560px] text-left text-sm">
          <thead className="border-border-subtle bg-well/30 text-muted border-b text-xs uppercase">
            <tr>
              <th className="px-4 py-3 font-medium">Product</th>
              <th className="px-3 py-3 font-medium">Visibility</th>
              <th className="px-3 py-3 font-medium">Mentions</th>
              <th className="px-3 py-3 font-medium">Avg position</th>
            </tr>
          </thead>
          <tbody className="divide-border-subtle divide-y">
            {categories.flatMap((category) => [
              <tr key={`category-${category}`} className="bg-well/40 text-foreground font-semibold">
                <td
                  className="text-secondary px-4 py-2.5 text-xs font-semibold tracking-wider uppercase"
                  colSpan={4}
                >
                  {category || 'Uncategorized'}
                </td>
              </tr>,
              ...visibility.products
                .filter((product) => product.category === category)
                .map((product) => <ProductVisibilityRow key={product.sku} product={product} />),
            ])}
          </tbody>
        </table>
      </CardContent>
    </Card>
  );
}

function ProductVisibilityRow({
  product,
}: Readonly<{ product: ProductVisibility['products'][number] }>) {
  const productName = (
    <>
      <span className="text-foreground font-medium">{product.name}</span>
      <span className="text-muted text-2xs block font-mono">{product.sku}</span>
    </>
  );
  return (
    <tr className="hover:bg-panel-tonal/50 transition-colors">
      <td className="px-4 py-3">
        {product.product_id ? (
          <Link
            className="text-foreground hover:text-accent-text transition-colors hover:underline"
            href={`/products/${product.product_id}`}
          >
            {productName}
          </Link>
        ) : (
          <span>{productName}</span>
        )}
      </td>
      <td className="text-foreground px-3 py-3 font-medium">
        {formatPercent(product.visibility_rate)}
      </td>
      <td className="text-secondary px-3 py-3">{product.mention_count}</td>
      <td className="text-secondary px-3 py-3">{formatAvgRank(product.avg_rank)}</td>
    </tr>
  );
}

function CompetitorAnalysis({ visibility }: Readonly<{ visibility: ProductVisibility }>) {
  const categories = visibility.citation_comparison.categories;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Competitor analysis</CardTitle>
        <CardDescription>
          Persisted brand and configured-competitor mentions from the selected audit.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {categories.map((category) => (
          <div
            key={category.category}
            className="border-border-subtle bg-well/20 grid gap-3 rounded-lg border p-4"
          >
            <div className="flex flex-wrap items-center justify-between gap-2">
              <strong className="text-foreground text-sm font-semibold">{category.category}</strong>
              <span className="text-muted text-xs">
                Brand in {category.brand_response_count}/{category.response_count} responses
              </span>
            </div>
            {category.competitor_mentions.length ? (
              <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
                {category.competitor_mentions.map((competitor) => (
                  <div
                    key={competitor.competitor_name}
                    className="border-border-subtle bg-panel rounded-md border p-3"
                  >
                    <span className="text-foreground block text-sm font-medium">
                      {competitor.competitor_name}
                    </span>
                    <span className="text-muted text-xs">
                      {competitor.response_count} responses · {competitor.distinct_prompts} prompts
                      {' · '}
                      {competitor.distinct_engines} engines
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-muted text-sm">No configured competitors were mentioned.</p>
            )}
          </div>
        ))}
        {!categories.length ? (
          <p className="text-muted text-sm">No category-level mention evidence is available.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function CitationComparison({ visibility }: Readonly<{ visibility: ProductVisibility }>) {
  const comparison = visibility.citation_comparison;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Cited alternatives and sources</CardTitle>
        <CardDescription>
          {comparison.limitation || 'Observed citations returned by the selected audit.'}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        {!comparison.categories.length ? (
          <p className="text-muted text-sm">
            This audit returned no citations for the tracked categories.
          </p>
        ) : null}
        {comparison.categories.map((category) => (
          <div
            key={category.category}
            className="border-border-subtle bg-well/20 grid gap-3 rounded-lg border p-4"
          >
            <div className="border-border-subtle flex flex-wrap items-baseline justify-between gap-2 border-b pb-2.5">
              <strong className="text-foreground text-sm font-semibold">{category.category}</strong>
              <span className="text-muted text-2xs">
                {category.response_count} responses · {category.uploaded_commerce_citation_count}{' '}
                brand citations · {category.competitor_citation_count} competitor citations ·{' '}
                {category.third_party_citation_count} other citations
              </span>
            </div>
            {category.cited_sources.length ? (
              <div className="grid gap-2">
                {category.cited_sources.map((source) => (
                  <CitedSourceRow key={`${source.domain}-${source.title}`} source={source} />
                ))}
              </div>
            ) : (
              <p className="text-muted text-sm">No citations returned for this category.</p>
            )}
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function safeCitationUrl(value: string): string | null {
  try {
    const parsed = new URL(value);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.toString() : null;
  } catch {
    return null;
  }
}

function CitedSourceRow({ source }: Readonly<{ source: CitedSource }>) {
  const sourceLabel =
    source.classification === 'owned'
      ? 'Brand source'
      : source.matched_competitor
        ? `${source.matched_competitor} source`
        : source.classification === 'competitor'
          ? 'Competitor source'
          : 'Other source';
  const content = (
    <div className="flex w-full flex-wrap items-center justify-between gap-2">
      <div className="min-w-0">
        <div className="flex items-center gap-1.5">
          <span className="text-foreground truncate text-sm font-medium">
            {source.title || source.domain}
          </span>
          {source.representative_url ? (
            <ExternalLink className="text-muted size-3 shrink-0" aria-hidden />
          ) : null}
        </div>
        <span className="text-muted block truncate text-xs">
          {source.domain} · {sourceLabel}
        </span>
      </div>
      <span className="bg-well text-secondary shrink-0 rounded px-2 py-0.5 text-xs">
        {source.citation_count} citations · {source.distinct_prompts} prompts ·{' '}
        {source.distinct_engines} engines
      </span>
    </div>
  );
  const href = safeCitationUrl(source.representative_url);
  if (!href) {
    return (
      <div className="border-border-subtle bg-panel flex justify-between gap-3 rounded-md border p-3 text-sm">
        {content}
      </div>
    );
  }
  return (
    <a
      className="border-border-subtle bg-panel hover:bg-panel-tonal flex justify-between gap-3 rounded-md border p-3 text-sm transition-colors"
      href={href}
      target="_blank"
      rel="noreferrer"
    >
      {content}
    </a>
  );
}

export function AiVisibilityPanel({
  projectId,
  queries,
  onAddProducts,
  onLaunchAudit,
}: Readonly<{
  projectId: string;
  queries: VisibilityQueries;
  onAddProducts: () => void;
  onLaunchAudit: () => void;
}>) {
  if (queries.visibilityQuery.isLoading || queries.productsQuery.isLoading)
    return <p className="text-secondary text-sm">Loading visibility…</p>;
  if (queries.productsQuery.isError) {
    return <Alert tone="danger">Could not load the product catalog.</Alert>;
  }
  if (!queries.productsQuery.data?.length) {
    return (
      <EmptyState
        icon={PackageSearch}
        heading="Add products before measuring them"
        description="Commerce visibility is calculated for the products present when an audit starts."
        action={<Button onClick={onAddProducts}>Add products</Button>}
      />
    );
  }
  if (queries.visibilityQuery.isError && httpErrorStatus(queries.visibilityQuery.error) !== 404) {
    return <Alert tone="danger">Could not load Commerce visibility.</Alert>;
  }
  if (
    (queries.visibilityQuery.isError && httpErrorStatus(queries.visibilityQuery.error) === 404) ||
    !queries.visibilityQuery.data
  ) {
    return (
      <EmptyState
        icon={Play}
        heading="No Commerce visibility audit yet"
        description="Launch an audit to measure product, brand, competitor, and citation presence."
        action={<Button onClick={onLaunchAudit}>Launch audit</Button>}
      />
    );
  }
  return (
    <VisibilityResults
      projectId={projectId}
      queries={queries}
      visibility={queries.visibilityQuery.data}
    />
  );
}
