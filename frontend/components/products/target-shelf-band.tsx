'use client';

import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';

import type { CommerceQueries } from './commerce-queries';

const percentage = (value: number | null | undefined) =>
  value == null ? 'Not measured' : `${(value * 100).toFixed(1)}%`;

/**
 * The measured outcome for the selected target, at the top of its detail.
 *
 * AI Shelf was a fourth tab with its own target selector, so the numbers a
 * category is judged on sat one navigation away from the competitors and
 * prompts that produced them. `design.md` asks for state before features:
 * this is the state, and everything below it is how the state was reached.
 */
export function TargetShelfBand({ query }: Readonly<{ query: CommerceQueries['shelf'] }>) {
  if (query.isPending) return <Skeleton className="h-24 w-full" />;
  const latest = query.data?.snapshots[0];
  const metrics: Array<[string, string]> = [
    ['Product visibility', percentage(latest?.product_visibility)],
    ['Share of shelf', percentage(latest?.share_of_shelf)],
    ['Average position', latest?.average_shelf_position?.toFixed(2) ?? 'Not measured'],
    ['First-position rate', percentage(latest?.first_position_win_rate)],
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {metrics.map(([label, value]) => (
        <Card key={label}>
          <CardHeader>
            <CardDescription>{label}</CardDescription>
            <CardTitle className="tabular-nums">{value}</CardTitle>
          </CardHeader>
        </Card>
      ))}
    </div>
  );
}

/** Whether this target has ever been measured, which decides the empty copy. */
export function hasShelfMeasurement(query: CommerceQueries['shelf']): boolean {
  return Boolean(query.data?.snapshots.length);
}
