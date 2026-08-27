'use client';

import { useMemo, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Input } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { Alert } from '@/components/ui/alert';
import type { CommerceTarget } from '@/lib/api/schemas/commerce-suite';
import { targetKey } from '@/lib/products/use-commerce-target';
import { cn } from '@/lib/utils';

import type { CommerceQueries } from './commerce-queries';

export type CatalogEntry = {
  key: string;
  label: string;
  target: CommerceTarget;
  /** Products in a category; undefined for a product row. */
  count?: number;
};

export function catalogEntries(query: CommerceQueries['catalog']): {
  categories: CatalogEntry[];
  products: CatalogEntry[];
} {
  const data = query.data;
  if (!data) return { categories: [], products: [] };
  return {
    categories: data.categories.map((row) => ({
      key: targetKey({ kind: 'category', id: row.id }),
      label: row.name,
      target: { kind: 'category' as const, id: row.id },
      count: row.product_count,
    })),
    products: data.products.map((row) => ({
      key: targetKey({ kind: 'product', id: row.id }),
      label: row.name || row.canonical_url,
      target: { kind: 'product' as const, id: row.id },
    })),
  };
}

function matches(entry: CatalogEntry, needle: string): boolean {
  return !needle || entry.label.toLowerCase().includes(needle);
}

function CatalogRow({
  entry,
  selected,
  checked,
  onSelect,
  onToggle,
}: Readonly<{
  entry: CatalogEntry;
  selected: boolean;
  checked: boolean;
  onSelect: () => void;
  onToggle: () => void;
}>) {
  return (
    <li>
      {/* The row is the picker. A checkbox in the gutter is bulk selection and
          deliberately does NOT change which target is open, so checking three
          categories to run them together never moves you off the one you are
          reading. */}
      <div className={cn('group flex items-center gap-2 rounded-md px-2', selected && 'bg-active')}>
        <input
          type="checkbox"
          className="accent-accent size-4 shrink-0"
          aria-label={`Select ${entry.label} for bulk actions`}
          checked={checked}
          onChange={onToggle}
        />
        <button
          type="button"
          onClick={onSelect}
          aria-current={selected ? 'true' : undefined}
          className="flex min-w-0 flex-1 items-center justify-between gap-2 py-2 text-left text-sm"
        >
          <span
            className={cn('truncate', selected ? 'text-foreground font-medium' : 'text-secondary')}
          >
            {entry.label}
          </span>
          {entry.count === undefined ? null : (
            <span className="text-muted shrink-0 tabular-nums">{entry.count}</span>
          )}
        </button>
      </div>
    </li>
  );
}

function CatalogGroup({
  title,
  entries,
  selectedKey,
  checkedKeys,
  onSelect,
  onToggle,
}: Readonly<{
  title: string;
  entries: CatalogEntry[];
  selectedKey?: string;
  checkedKeys: Set<string>;
  onSelect: (target: CommerceTarget) => void;
  onToggle: (key: string) => void;
}>) {
  if (!entries.length) return null;
  return (
    <div className="grid gap-1">
      <div className="text-muted flex items-center justify-between px-2 text-xs font-medium">
        <span>{title}</span>
        <span className="tabular-nums">{entries.length}</span>
      </div>
      <ul className="grid">
        {entries.map((entry) => (
          <CatalogRow
            key={entry.key}
            entry={entry}
            selected={entry.key === selectedKey}
            checked={checkedKeys.has(entry.key)}
            onSelect={() => onSelect(entry.target)}
            onToggle={() => onToggle(entry.key)}
          />
        ))}
      </ul>
    </div>
  );
}

/**
 * The catalog as navigation.
 *
 * Selecting a category or product happens here, once, by clicking the list you
 * are already reading — replacing the target selector that each tab used to
 * carry its own copy of.
 */
export function CatalogList({
  query,
  selectedKey,
  checkedKeys,
  onSelect,
  onToggle,
}: Readonly<{
  query: CommerceQueries['catalog'];
  selectedKey?: string;
  checkedKeys: Set<string>;
  onSelect: (target: CommerceTarget) => void;
  onToggle: (key: string) => void;
}>) {
  const [search, setSearch] = useState('');
  const { categories, products } = useMemo(() => catalogEntries(query), [query]);
  const needle = search.trim().toLowerCase();
  const shownCategories = categories.filter((entry) => matches(entry, needle));
  const shownProducts = products.filter((entry) => matches(entry, needle));
  const empty = !shownCategories.length && !shownProducts.length;

  if (query.isPending) return <Skeleton className="h-96 w-full" />;
  if (query.isError) return <Alert tone="danger">The catalog could not be loaded.</Alert>;
  return (
    <div className="grid content-start gap-3">
      <Input
        aria-label="Search the catalog"
        placeholder="Search categories and products"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      {empty ? (
        <p className="text-muted px-2 py-8 text-center text-sm">
          {needle
            ? `Nothing matches “${search.trim()}”.`
            : 'Nothing projected yet. Run a Site Health crawl or import a CSV.'}
        </p>
      ) : (
        <div className="grid gap-4">
          <CatalogGroup
            title="Categories"
            entries={shownCategories}
            selectedKey={selectedKey}
            checkedKeys={checkedKeys}
            onSelect={onSelect}
            onToggle={onToggle}
          />
          <CatalogGroup
            title="Products"
            entries={shownProducts}
            selectedKey={selectedKey}
            checkedKeys={checkedKeys}
            onSelect={onSelect}
            onToggle={onToggle}
          />
        </div>
      )}
      {checkedKeys.size ? (
        <Badge variant="status" value="info">
          {checkedKeys.size} selected
        </Badge>
      ) : null}
    </div>
  );
}
