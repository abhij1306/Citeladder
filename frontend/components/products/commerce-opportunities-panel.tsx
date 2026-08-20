'use client';

import { useMemo, useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog } from '@/components/ui/dialog';
import type { Opportunity } from '@/lib/api/types';
import type { useCommerceOpportunities } from '@/lib/products/use-products-screen';

type OpportunityQueries = ReturnType<typeof useCommerceOpportunities>;

export function CommerceOpportunitiesPanel({ queries }: Readonly<{ queries: OpportunityQueries }>) {
  const [selected, setSelected] = useState<Opportunity | null>(null);
  const [confirmedIds, setConfirmedIds] = useState<Set<string>>(() => new Set());
  const groups = useMemo(() => {
    const result = new Map<string, Opportunity[]>();
    for (const item of queries.opportunitiesQuery.data?.items ?? []) {
      const key = item.target_label ?? 'Catalog-wide';
      result.set(key, [...(result.get(key) ?? []), item]);
    }
    return [...result.entries()];
  }, [queries.opportunitiesQuery.data]);

  if (queries.opportunitiesQuery.isLoading)
    return <p className="text-secondary text-sm">Loading opportunities…</p>;
  if (queries.opportunitiesQuery.isError)
    return <Alert tone="danger">Could not load Commerce opportunities.</Alert>;

  return (
    <div className="grid gap-4" data-testid="commerce-opportunities-panel">
      {groups.map(([product, items]) => (
        <Card key={product}>
          <CardHeader>
            <CardTitle>{product}</CardTitle>
            <CardDescription>
              {items.length} evidence-backed action{items.length === 1 ? '' : 's'}
            </CardDescription>
          </CardHeader>
          <CardContent className="grid gap-2">
            {items.map((item) => (
              <button
                key={item.id}
                type="button"
                className="hover:bg-surface-hover flex items-center justify-between rounded-sm p-2 text-left text-sm"
                onClick={() => setSelected(item)}
              >
                <span>{item.title}</span>
                {confirmedIds.has(item.id) ? (
                  <Badge>Confirmed</Badge>
                ) : (
                  <Badge>{item.severity}</Badge>
                )}
              </button>
            ))}
          </CardContent>
        </Card>
      ))}
      {!groups.length ? <Alert tone="info">No Commerce opportunities are open.</Alert> : null}
      <Dialog
        open={Boolean(selected)}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
        title={selected?.title ?? 'Review action'}
        description="Review this observed gap before making a catalog change."
        footer={
          <>
            <Button variant="ghost" onClick={() => setSelected(null)}>
              Cancel
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                if (selected) setConfirmedIds((current) => new Set(current).add(selected.id));
                setSelected(null);
              }}
            >
              Confirm
            </Button>
          </>
        }
      >
        <div className="grid gap-3 py-4 text-sm">
          <p>{selected?.target_label ?? 'Catalog-wide recommendation'}</p>
          <p className="text-secondary">
            This confirmation exists only in this browser session. It does not update an external
            system or persisted workflow state.
          </p>
        </div>
      </Dialog>
    </div>
  );
}
