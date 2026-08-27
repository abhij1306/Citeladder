'use client';

import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import type { CommerceTarget } from '@/lib/api/schemas/commerce-suite';
import { useCompetitorDiscovery } from '@/lib/products/competitor-discovery';
import { targetKey, useCommerceTarget } from '@/lib/products/use-commerce-target';
import { useCommerceQueries } from '@/lib/products/use-products-screen';

import { CatalogHeader } from './catalog-header';
import { CatalogList, catalogEntries } from './catalog-list';
import { TargetDetail } from './target-detail';

/** The bulk bar exists only while rows are checked; that is its whole rule. */
function BulkActions({
  count,
  pending,
  onDiscover,
  onClear,
}: Readonly<{
  count: number;
  pending: boolean;
  onDiscover: () => void;
  onClear: () => void;
}>) {
  if (!count) return null;
  return (
    <div className="border-border bg-elevated flex flex-wrap items-center gap-2 rounded-lg border p-2">
      <span className="text-secondary text-sm">
        {count} {count === 1 ? 'target' : 'targets'} selected
      </span>
      <Button size="sm" disabled={pending} onClick={onDiscover}>
        Find competitors
      </Button>
      <Button size="sm" variant="ghost" onClick={onClear}>
        Clear
      </Button>
    </div>
  );
}

export function CommerceWorkspace({ projectId }: Readonly<{ projectId: string }>) {
  const { target, selectTarget } = useCommerceTarget();
  const queries = useCommerceQueries(projectId, target);
  const discovery = useCompetitorDiscovery(projectId);
  const [checked, setChecked] = useState<string[]>([]);
  const { categories, products } = catalogEntries(queries.catalog);
  const entries = [...categories, ...products];
  const selectedKey = target ? targetKey(target) : undefined;
  const label = entries.find((entry) => entry.key === selectedKey)?.label ?? '';
  const checkedSet = new Set(checked);
  const checkedTargets = entries
    .filter((entry) => checkedSet.has(entry.key))
    .map((entry) => entry.target);
  const toggle = (key: string) =>
    setChecked((current) =>
      current.includes(key) ? current.filter((value) => value !== key) : [...current, key],
    );
  return (
    <div className="grid gap-4">
      <CatalogHeader projectId={projectId} query={queries.catalog} />
      <BulkActions
        count={checkedTargets.length}
        pending={discovery.discover.isPending}
        onDiscover={() => discovery.discover.mutate(checkedTargets)}
        onClear={() => setChecked([])}
      />
      {/* `min-w-0` on BOTH columns is load-bearing: a grid item defaults to
          `min-width: auto`, so a long product name ("TempPro TP920 Bluetooth
          Meat Thermometer + TP620 Instant-Read + TP358 Hygrometer — Bundle")
          forces the track wider than its track sizing and the list overflows
          its own card, on top of the detail pane. */}
      <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,18rem)_minmax(0,1fr)]">
        <Card className="min-w-0 lg:sticky lg:top-4">
          <CardContent className="max-h-[calc(100vh-8rem)] overflow-y-auto pt-4">
            <CatalogList
              query={queries.catalog}
              selectedKey={selectedKey}
              checkedKeys={checkedSet}
              onSelect={(next: CommerceTarget) => selectTarget(next)}
              onToggle={toggle}
            />
          </CardContent>
        </Card>
        <div className="min-w-0">
          {target ? (
            // Rendered as soon as a target exists, not once the catalog has
            // loaded a label for it: a reload with `?target=` in the URL used
            // to show "select a category" until the catalog landed.
            <TargetDetail
              projectId={projectId}
              target={target}
              label={label || `Selected ${target.kind}`}
              queries={queries}
              discovery={discovery}
            />
          ) : (
            <Alert tone="info">
              Select a category or product to see its shelf position, its competitors, and the
              prompts that measure it.
            </Alert>
          )}
        </div>
      </div>
    </div>
  );
}
