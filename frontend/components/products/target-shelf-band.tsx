'use client';

import { Alert } from '@/components/ui/alert';
import { Card, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { UnavailableValue } from '@/components/ui/unavailable-value';

import type { CommerceQueries } from './commerce-queries';

const percentage = (value: number | null | undefined) =>
  value == null ? null : `${(value * 100).toFixed(1)}%`;

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
  // A failed read is not an unmeasured target. Rendering "Not measured" for a
  // request that never landed reports a missing metric as an observed absence,
  // which is exactly the unknown/zero collapse the repo forbids.
  if (query.isError) return <Alert tone="danger">AI Shelf metrics could not be loaded.</Alert>;
  const latest = query.data?.snapshots[0];
  const metrics: Array<[string, string | null]> = [
    ['Product visibility', percentage(latest?.product_visibility)],
    ['Share of shelf', percentage(latest?.share_of_shelf)],
    ['Average position', latest?.average_shelf_position?.toFixed(2) ?? null],
    ['First-position rate', percentage(latest?.first_position_win_rate)],
  ];
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      {metrics.map(([label, value]) => (
        <Card key={label}>
          <CardHeader>
            <CardDescription>{label}</CardDescription>
            {value === null ? (
              <UnavailableValue state="not_measured" className="mt-1 inline-flex" />
            ) : (
              <CardTitle className="tabular-nums">{value}</CardTitle>
            )}
          </CardHeader>
        </Card>
      ))}
    </div>
  );
}

/** Whether the "not measured yet" prompt applies to this read.

 * Only a SUCCESSFUL read with no snapshots means the target was never
 * measured; a pending or failed read knows nothing either way and must not
 * claim it.
 */
export function hasShelfMeasurement(query: CommerceQueries['shelf']): boolean {
  return Boolean(query.data?.snapshots.length) || query.isPending || query.isError;
}
