'use client';

import { useMemo, useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { useCommerceComparison } from '@/lib/products/use-products-screen';
import { formatAvgRank, formatPercent } from '@/lib/products/catalog';

type ComparisonQueries = ReturnType<typeof useCommerceComparison>;

export function CompetitorsPanel({ queries }: Readonly<{ queries: ComparisonQueries }>) {
  const [selectedProductId, setSelectedProductId] = useState('');
  const comparison = queries.comparisonQuery.data;
  const selected = useMemo(
    () =>
      comparison?.items.find((item) => item.own_product.id === selectedProductId) ??
      comparison?.items[0],
    [comparison, selectedProductId],
  );

  if (queries.comparisonQuery.isLoading)
    return <p className="text-secondary text-sm">Loading comparison…</p>;
  if (queries.comparisonQuery.isError || !comparison || !selected) {
    return (
      <Alert tone="info">
        A completed audit with matched competitor products will populate this view.
      </Alert>
    );
  }

  const competitorMayBeWinning =
    selected.competitor_product.visibility_rate > selected.own_product.visibility_rate ||
    (selected.competitor_product.average_rank ?? Infinity) <
      (selected.own_product.average_rank ?? Infinity);

  return (
    <div className="grid gap-4" data-testid="commerce-competitors-panel">
      <Card>
        <CardHeader>
          <CardTitle>Product comparison</CardTitle>
          <CardDescription>
            Automatic deterministic match from the latest completed audit.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <label className="grid max-w-sm gap-1 text-sm">
            Product
            <select
              className="border-border bg-surface rounded-sm border p-2"
              value={selected.own_product.id}
              onChange={(event) => setSelectedProductId(event.target.value)}
            >
              {comparison.items.map((item) => (
                <option key={item.own_product.id} value={item.own_product.id}>
                  {item.own_product.name}
                </option>
              ))}
            </select>
          </label>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>
            {selected.own_product.name} vs {selected.competitor_product.name}
          </CardTitle>
          <CardDescription>
            Matched by {selected.match_reasons.join(', ')} (
            {formatPercent(selected.match_confidence)} confidence).
          </CardDescription>
        </CardHeader>
        <CardContent className="grid gap-4">
          <div className="grid grid-cols-3 gap-2 text-sm">
            <strong>Metric</strong>
            <strong>Your product</strong>
            <strong>Competitor</strong>
            <span>Visibility</span>
            <span>{formatPercent(selected.own_product.visibility_rate)}</span>
            <span>{formatPercent(selected.competitor_product.visibility_rate)}</span>
            <span>Average rank</span>
            <span>{formatAvgRank(selected.own_product.average_rank)}</span>
            <span>{formatAvgRank(selected.competitor_product.average_rank)}</span>
            <span>Win rate</span>
            <span>{formatPercent(selected.own_product.win_rate)}</span>
            <span>{formatPercent(selected.competitor_product.win_rate)}</span>
          </div>
          <div className="grid gap-2">
            <strong className="text-sm">Attribute differences</strong>
            {selected.attribute_gaps.map((gap) => (
              <div
                key={gap.field}
                className="border-border grid grid-cols-3 gap-2 rounded-sm border p-2 text-sm"
              >
                <span>{gap.field}</span>
                <span>{String(gap.own_value ?? 'Missing')}</span>
                <span>{String(gap.competitor_value)}</span>
              </div>
            ))}
          </div>
          {competitorMayBeWinning ? (
            <Alert tone="info">
              This competitor may be winning because it is more visible, ranks higher, or exposes
              richer product attributes in the observed evidence.
            </Alert>
          ) : (
            <Badge>Your product leads in the latest observed comparison.</Badge>
          )}
          <p className="text-muted text-xs">
            Audit {comparison.audit_id} · {comparison.source_metric_ids.length} source metrics
          </p>
        </CardContent>
      </Card>
    </div>
  );
}
