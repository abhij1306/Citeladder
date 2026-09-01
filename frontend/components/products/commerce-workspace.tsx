'use client';

import { useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import type { CommerceTarget } from '@/lib/api/schemas/commerce-suite';
import { useCompetitorDiscovery } from '@/lib/products/competitor-discovery';
import {
  MAX_PANE_WIDTH,
  MIN_PANE_WIDTH,
  type ResizablePane,
  useResizablePane,
} from '@/lib/products/use-resizable-pane';
import { targetKey, useCommerceTarget } from '@/lib/products/use-commerce-target';
import { useCommerceQueries } from '@/lib/products/use-products-screen';

import { CatalogHeader } from './catalog-header';
import { CatalogList, catalogEntries } from './catalog-list';
import { TargetDetail } from './target-detail';

/** Stable bulk-selection status and actions; selecting the first row never shifts the workspace. */
export function BulkActions({
  count,
  hasCheckedKeys,
  pending,
  onDiscover,
  onClear,
}: Readonly<{
  count: number;
  hasCheckedKeys: boolean;
  pending: boolean;
  onDiscover: () => void;
  onClear: () => void;
}>) {
  return (
    <div className="bg-panel flex min-h-16 flex-wrap items-center justify-between gap-3 rounded-[var(--radius-card)] px-3 py-2">
      <div className="grid gap-0.5">
        <span aria-live="polite" className="text-foreground text-sm font-medium">
          {count
            ? `${count} ${count === 1 ? 'target' : 'targets'} selected`
            : 'No targets selected'}
        </span>
        <span className="text-muted text-xs">
          {count
            ? 'Find competitors for every checked target.'
            : 'Check categories or products to use bulk actions.'}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-1">
        <Button
          size="sm"
          disabled={!count}
          pending={pending}
          pendingLabel="Finding…"
          onClick={onDiscover}
        >
          Find competitors
        </Button>
        <Button size="sm" variant="ghost" disabled={!hasCheckedKeys || pending} onClick={onClear}>
          Clear selection
        </Button>
      </div>
    </div>
  );
}

/**
 * The drag handle between the catalog list and the target detail.
 *
 * A `separator` with `aria-valuenow` is the role a pane splitter has, so the
 * width is operable by keyboard (arrows nudge, Home restores the default) and
 * not only by pointer — a control that exists only under a mouse is not a
 * control. Hidden below `lg`, where the two panes stack and there is no
 * boundary to move.
 */
function PaneResizer({ pane }: Readonly<{ pane: ResizablePane }>) {
  return (
    <div
      // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- Native hr cannot expose value or support pointer and keyboard pane resizing.
      role="separator"
      tabIndex={0}
      aria-orientation="vertical"
      aria-label="Resize the catalog pane"
      aria-valuemin={MIN_PANE_WIDTH}
      aria-valuemax={MAX_PANE_WIDTH}
      aria-valuenow={pane.width}
      className="group focus-visible:ring-accent hidden min-h-24 cursor-col-resize touch-none items-stretch justify-center self-stretch rounded-full px-1 focus-visible:ring-2 focus-visible:outline-none lg:flex"
      onPointerDown={(event) => {
        event.currentTarget.setPointerCapture(event.pointerId);
        pane.beginDrag(event.clientX);
      }}
      onPointerMove={(event) => {
        if (pane.dragging) pane.dragTo(event.clientX);
      }}
      onPointerUp={(event) => {
        event.currentTarget.releasePointerCapture(event.pointerId);
        pane.endDrag();
      }}
      onPointerCancel={() => pane.endDrag()}
      onDoubleClick={() => pane.reset()}
      onKeyDown={(event) => {
        if (event.key === 'ArrowLeft') pane.nudge(-pane.keyboardStep);
        else if (event.key === 'ArrowRight') pane.nudge(pane.keyboardStep);
        else if (event.key === 'Home') pane.reset();
        else return;
        event.preventDefault();
      }}
    >
      <span
        aria-hidden
        className={`w-0.5 rounded-full transition-colors ${
          pane.dragging ? 'bg-accent' : 'bg-border group-hover:bg-border-bold'
        }`}
      />
    </div>
  );
}

export function CommerceWorkspace({ projectId }: Readonly<{ projectId: string }>) {
  const { target, selectTarget } = useCommerceTarget();
  const queries = useCommerceQueries(projectId, target);
  const discovery = useCompetitorDiscovery(projectId);
  const [checked, setChecked] = useState<string[]>([]);
  const pane = useResizablePane();
  const { categories, products } = catalogEntries(queries.catalog);
  const entries = [...categories, ...products];
  const selectedKey = target ? targetKey(target) : undefined;
  const label = entries.find((entry) => entry.key === selectedKey)?.label ?? '';
  const checkedSet = new Set(checked);
  const checkedTargets = entries
    .filter((entry) => checkedSet.has(entry.key))
    .map((entry) => entry.target);
  const toggle = (keys: string[]) =>
    setChecked((current) => {
      const next = new Set(current);
      const remove = keys.every((key) => next.has(key));
      keys.forEach((key) => (remove ? next.delete(key) : next.add(key)));
      return [...next];
    });
  return (
    <div className="grid gap-4">
      <CatalogHeader projectId={projectId} query={queries.catalog} />
      <BulkActions
        count={checkedTargets.length}
        hasCheckedKeys={checked.length > 0}
        pending={discovery.discover.isPending}
        onDiscover={() => discovery.discover.mutate(checkedTargets)}
        onClear={() => setChecked([])}
      />
      {/* `min-w-0` on BOTH columns is load-bearing: a grid item defaults to
          `min-width: auto`, so a long product name ("TempPro TP920 Bluetooth
          Meat Thermometer + TP620 Instant-Read + TP358 Hygrometer — Bundle")
          forces the track wider than its track sizing and the list overflows
          its own card, on top of the detail pane.

          The first track is the reader's to size (see `useResizablePane`); the
          gap is halved because the separator now carries the space between the
          panes itself. `select-none` while dragging stops the pointer from
          painting a text selection across both panes. */}
      <div
        style={{ '--catalog-pane': `${pane.width}px` } as React.CSSProperties}
        className={`grid items-start gap-2 lg:grid-cols-[var(--catalog-pane)_auto_minmax(0,1fr)] ${
          pane.dragging ? 'cursor-col-resize select-none' : ''
        }`}
      >
        <Card className="min-w-0 lg:sticky lg:top-4">
          <CardContent className="max-h-[calc(100vh-8rem)] overflow-y-auto p-0">
            <CatalogList
              query={queries.catalog}
              selectedKey={selectedKey}
              checkedKeys={checkedSet}
              onSelect={(next: CommerceTarget) => selectTarget(next)}
              onToggle={toggle}
            />
          </CardContent>
        </Card>
        <PaneResizer pane={pane} />
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
