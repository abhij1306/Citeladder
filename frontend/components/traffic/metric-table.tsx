'use client';

import { useQuery } from '@tanstack/react-query';
import { ArrowDown, ArrowUp, ArrowUpDown } from 'lucide-react';
import { type ReactNode, useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { CursorPager } from '@/components/ui/cursor-pager';
import { Skeleton } from '@/components/ui/skeleton';
import { UnavailableValue } from '@/components/ui/unavailable-value';
import { Pressable } from '@/components/ui/pressable';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { retainPreviousDataForScope } from '@/lib/api/query-client';
import { useCursorStack } from '@/lib/site-health/use-cursor-stack';
import {
  describeSort,
  formatCount,
  formatCtr,
  formatPosition,
  sortDirection,
  sortKey,
  toggleSort,
} from '@/lib/traffic/traffic';
import { cn } from '@/lib/utils';

const SORTABLE_COLUMNS = [
  { key: 'impressions', label: 'Impressions' },
  { key: 'clicks', label: 'Clicks' },
  { key: 'ctr', label: 'CTR' },
  { key: 'position', label: 'Position' },
] as const;
type SortableColumnKey = (typeof SORTABLE_COLUMNS)[number]['key'];

const DEFAULT_SORT = '-clicks';

export type MetricRow = {
  impressions: number;
  clicks: number;
  ctr: number | null;
  position: number | null;
};

type MetricPage<Row extends MetricRow> = { items: Row[]; next_cursor: string | null };

type MetricTableProps<Row extends MetricRow> = Readonly<{
  testId: string;
  title: string;
  description: string;
  leadLabel: string;
  emptyMessage: string;
  errorMessage: string;
  leadSkeletonClassName: string;
  scopeId: string;
  queryKey: (sort: string, cursor: string | undefined) => readonly unknown[];
  fetchPage: (
    sort: string,
    cursor: string | undefined,
    signal: AbortSignal,
  ) => Promise<MetricPage<Row>>;
  rowKey: (row: Row) => string;
  renderLead: (row: Row) => ReactNode;
}>;

function SortableColumnHead({
  columnKey,
  label,
  sort,
  onSort,
}: Readonly<{
  columnKey: SortableColumnKey;
  label: string;
  sort: string;
  onSort: (key: SortableColumnKey) => void;
}>) {
  const active = sortKey(sort) === columnKey;
  const descending = sortDirection(sort) === 'descending';
  return (
    <TableHead numeric aria-sort={active ? (descending ? 'descending' : 'ascending') : undefined}>
      <Pressable
        type="button"
        onClick={() => onSort(columnKey)}
        className={cn(
          'inline-flex w-auto items-center gap-1',
          active ? 'text-accent-text' : 'hover:text-foreground',
        )}
      >
        {label}
        {active ? (
          descending ? (
            <ArrowDown className="size-3" aria-hidden />
          ) : (
            <ArrowUp className="size-3" aria-hidden />
          )
        ) : (
          <ArrowUpDown className="text-muted size-3" aria-hidden />
        )}
      </Pressable>
    </TableHead>
  );
}

function NumericCell({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <TableCell numeric>
      <span className="font-mono">{children}</span>
    </TableCell>
  );
}

function NullableMetricCell({
  value,
  format,
}: Readonly<{ value: number | null; format: (value: number) => string }>) {
  return value === null ? (
    <TableCell numeric>
      <UnavailableValue state="not_measured" />
    </TableCell>
  ) : (
    <NumericCell>{format(value)}</NumericCell>
  );
}

export function MetricTable<Row extends MetricRow>({
  testId,
  title,
  description,
  leadLabel,
  emptyMessage,
  errorMessage,
  leadSkeletonClassName,
  scopeId,
  queryKey,
  fetchPage,
  rowKey,
  renderLead,
}: MetricTableProps<Row>) {
  const pager = useCursorStack();
  const [sort, setSort] = useState(DEFAULT_SORT);
  const query = useQuery({
    queryKey: queryKey(sort, pager.cursor),
    queryFn: ({ signal }) => fetchPage(sort, pager.cursor, signal),
    placeholderData: (previousData, previousQuery) =>
      retainPreviousDataForScope(scopeId, previousData, previousQuery),
  });
  const rows = query.data?.items ?? [];
  const nextCursor = query.data?.next_cursor ?? null;

  const onSort = (key: SortableColumnKey) => {
    setSort((current) => toggleSort(current, key));
    pager.reset();
  };

  return (
    <Card data-testid={testId}>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      {query.isError ? (
        <div className="p-[var(--card-padding)]">
          <Alert tone="danger">{errorMessage}</Alert>
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{leadLabel}</TableHead>
              {SORTABLE_COLUMNS.map((column) => (
                <SortableColumnHead
                  key={column.key}
                  columnKey={column.key}
                  label={column.label}
                  sort={sort}
                  onSort={onSort}
                />
              ))}
            </TableRow>
          </TableHeader>
          <TableBody>
            {query.isLoading
              ? Array.from({ length: 5 }, (_, index) => (
                  <TableRow key={`skeleton-${index}`}>
                    <TableCell>
                      <Skeleton className={leadSkeletonClassName} />
                    </TableCell>
                    {SORTABLE_COLUMNS.map((column) => (
                      <TableCell key={column.key} numeric>
                        <Skeleton className="mx-auto h-4 w-12" />
                      </TableCell>
                    ))}
                  </TableRow>
                ))
              : null}
            {!query.isLoading && rows.length === 0 ? (
              <TableRow>
                <TableCell colSpan={1 + SORTABLE_COLUMNS.length}>
                  <span className="text-muted">{emptyMessage}</span>
                </TableCell>
              </TableRow>
            ) : null}
            {rows.map((row) => (
              <TableRow key={rowKey(row)}>
                <TableCell>{renderLead(row)}</TableCell>
                <NumericCell>{formatCount(row.impressions)}</NumericCell>
                <NumericCell>{formatCount(row.clicks)}</NumericCell>
                <NullableMetricCell value={row.ctr} format={formatCtr} />
                <NullableMetricCell value={row.position} format={formatPosition} />
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
      {!query.isError ? (
        <div className="border-border-subtle flex items-center justify-between gap-3 border-t px-3 py-2">
          <span className="text-muted text-xs">{describeSort(sort)}</span>
          <CursorPager
            canPrev={pager.canPrev}
            canNext={Boolean(nextCursor)}
            onPrev={pager.pop}
            onNext={() => {
              if (nextCursor) pager.push(nextCursor);
            }}
          />
        </div>
      ) : null}
    </Card>
  );
}
