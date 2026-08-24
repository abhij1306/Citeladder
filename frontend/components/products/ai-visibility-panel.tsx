'use client';

import Link from 'next/link';
import { PackageSearch, Play } from 'lucide-react';

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
      <CardContent className="overflow-x-auto">
        <table className="w-full min-w-[720px] text-left text-sm">
          <thead className="text-muted border-b">
            <tr>
              <th className="p-2">Product</th>
              <th className="p-2">Visibility</th>
              <th className="p-2">Top three</th>
              <th className="p-2">Avg position</th>
              <th className="p-2">Engine coverage</th>
              <th className="p-2">Change</th>
            </tr>
          </thead>
          <tbody>
            {categories.flatMap((category) => [
              <tr key={`category-${category}`} className="bg-well border-b">
                <td className="p-2 font-semibold" colSpan={6}>
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
      {product.name}
      <span className="text-muted block text-xs">{product.sku}</span>
    </>
  );
  return (
    <tr className="border-b last:border-0">
      <td className="p-2">
        {product.product_id ? (
          <Link className="text-link" href={`/products/${product.product_id}`}>
            {productName}
          </Link>
        ) : (
          <span>{productName}</span>
        )}
      </td>
      <td className="p-2">{formatPercent(product.visibility_rate)}</td>
      <td className="p-2">{formatPercent(product.top_three_rate)}</td>
      <td className="p-2">{formatAvgRank(product.avg_rank)}</td>
      <td className="p-2">{product.engine_coverage} engines</td>
      <td className="p-2">{formatPercent(product.visibility_delta)}</td>
    </tr>
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
      <CardContent className="grid gap-5">
        {!comparison.categories.length ? (
          <p className="text-muted text-sm">
            This audit returned no citations for the tracked categories.
          </p>
        ) : null}
        {comparison.categories.map((category) => (
          <div key={category.category} className="grid gap-2">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <strong>{category.category}</strong>
              <span className="text-muted text-xs">
                {category.response_count} responses · {category.uploaded_commerce_citation_count}{' '}
                uploaded destination citations · {category.third_party_citation_count} third-party
                citations
              </span>
            </div>
            {category.cited_sources.length ? (
              category.cited_sources.map((source) => (
                <CitedSourceRow key={`${source.domain}-${source.title}`} source={source} />
              ))
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
  const className = 'border-border-subtle flex justify-between gap-3 rounded-sm border p-3 text-sm';
  const content = (
    <>
      <span>
        <span className="font-medium">{source.title || source.domain}</span>
        <span className="text-muted block text-xs">{source.domain}</span>
      </span>
      <span className="text-muted text-xs">
        {source.citation_count} citations · {source.distinct_prompts} prompts ·{' '}
        {source.distinct_engines} engines
      </span>
    </>
  );
  const href = safeCitationUrl(source.representative_url);
  if (!href) return <div className={className}>{content}</div>;
  return (
    <a
      className={`${className} hover:bg-surface-hover`}
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
        description="Launch an audit to measure product mentions, rankings, and engine coverage."
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
