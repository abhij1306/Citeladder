'use client';

import Link from 'next/link';

import { Alert } from '@/components/ui/alert';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { formatAvgRank, formatPercent } from '@/lib/products/catalog';
import type { ProductsTab } from '@/lib/products/catalog';
import type { useCommerceOverview } from '@/lib/products/use-products-screen';

type OverviewQueries = ReturnType<typeof useCommerceOverview>;

export function CommerceOverviewPanel({
  queries,
  onSelectTab,
}: Readonly<{
  queries: OverviewQueries;
  onSelectTab: (tab: ProductsTab) => void;
}>) {
  if (queries.visibilityQuery.isLoading) {
    return <p className="text-secondary text-sm">Loading Commerce overview…</p>;
  }
  if (queries.visibilityQuery.isError) {
    return <Alert tone="danger">Could not load the Commerce overview.</Alert>;
  }
  if (!queries.visibilityQuery.data) {
    return (
      <Alert tone="info">Run a product-enabled audit to populate the Commerce overview.</Alert>
    );
  }

  const visibility = queries.visibilityQuery.data;
  const summary = visibility.summary;
  const gaps = [...visibility.products]
    .filter((product) => product.visibility_delta !== null)
    .sort((a, b) => a.visibility_delta! - b.visibility_delta!)
    .slice(0, 3);
  const opportunities = queries.opportunitiesQuery.data?.items ?? [];

  return (
    <div className="grid gap-4" data-testid="commerce-overview-panel">
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Kpi
          label="Products visible"
          value={`${summary.products_visible}/${summary.products_tracked}`}
        />
        <Kpi label="Visibility rate" value={formatPercent(summary.visibility_rate)} />
        <Kpi label="Top-three rate" value={formatPercent(summary.top_three_rate)} />
        <Kpi label="Average rank" value={formatAvgRank(summary.average_rank)} />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Engine visibility</CardTitle>
            <CardDescription>Latest completed audit across configured AI engines.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm">
            <p>{visibility.total_analyses} responses analyzed</p>
            <p>{summary.competitor_wins} observed competitor wins</p>
            <button
              className="text-link w-fit"
              type="button"
              onClick={() => onSelectTab('visibility')}
            >
              View AI Visibility
            </button>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Largest product gaps</CardTitle>
            <CardDescription>Products with the weakest recent visibility movement.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2 text-sm">
            {gaps.map((product) => (
              <Link
                key={product.product_id ?? product.sku}
                className="hover:bg-surface-hover flex justify-between rounded-sm p-2"
                href={
                  product.product_id ? `/products/${product.product_id}` : '/products?tab=catalog'
                }
              >
                <span>{product.name}</span>
                <span>{formatPercent(product.visibility_delta)}</span>
              </Link>
            ))}
            {!gaps.length ? <p className="text-muted">No product gaps yet.</p> : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Recommended actions</CardTitle>
          <CardDescription>Deterministic opportunities tied to product evidence.</CardDescription>
        </CardHeader>
        <CardContent className="grid gap-2 text-sm">
          {opportunities.slice(0, 3).map((opportunity) => (
            <button
              key={opportunity.id}
              className="hover:bg-surface-hover flex justify-between rounded-sm p-2 text-left"
              type="button"
              onClick={() => onSelectTab('opportunities')}
            >
              <span>{opportunity.title}</span>
              <span className="text-muted">{opportunity.target_label ?? 'Catalog'}</span>
            </button>
          ))}
          {!opportunities.length ? <p className="text-muted">No open Commerce actions.</p> : null}
        </CardContent>
      </Card>
    </div>
  );
}

function Kpi({ label, value }: Readonly<{ label: string; value: string }>) {
  return (
    <Card>
      <CardContent className="grid gap-1">
        <span className="text-muted text-xs">{label}</span>
        <strong className="text-2xl">{value}</strong>
      </CardContent>
    </Card>
  );
}
