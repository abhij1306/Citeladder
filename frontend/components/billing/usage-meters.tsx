'use client';

import { useQuery } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Skeleton } from '@/components/ui/skeleton';
import { UsageMeter } from '@/components/billing/usage-meter';
import { billingApi, type UsageItem } from '@/lib/api/billing';
import { queryKeys } from '@/lib/api/query-keys';

/**
 * Preferred display order. Rows the backend sends that are not listed here
 * still render, after these — the list is an ordering hint, not a filter, so a
 * new backend counter appears without a frontend change.
 */
const PREFERRED_ORDER = [
  'prompt_slots',
  'project_slots',
  'manual_runs_per_day',
  'benchmark_credits',
  'pulse_credits',
];

function ordered(items: readonly UsageItem[]): UsageItem[] {
  return [...items].sort((a, b) => {
    const ai = PREFERRED_ORDER.indexOf(a.key);
    const bi = PREFERRED_ORDER.indexOf(b.key);
    if (ai === -1 && bi === -1) return a.key.localeCompare(b.key);
    if (ai === -1) return 1;
    if (bi === -1) return -1;
    return ai - bi;
  });
}

/**
 * Account usage, extracted from `BillingSettings` so plan orchestration and
 * meter rendering have separate owners.
 *
 * Fails closed on an unresolved entitlement: an account whose fold did not
 * resolve has no verified allowance, and showing meters against unverified
 * numbers would be worse than showing none.
 */
export function UsageMeters({ enabled = true }: Readonly<{ enabled?: boolean }>) {
  const usageQuery = useQuery({
    queryKey: queryKeys.billing.usage(),
    queryFn: ({ signal }) => billingApi.usage({ signal }),
    enabled,
  });

  return (
    <div className="bg-panel shadow-card border-border-subtle grid gap-3.5 rounded-md border p-5">
      <div>
        <h2 className="text-foreground text-sm font-semibold tracking-tight">Usage</h2>
        <p className="text-muted mt-0.5 text-xs">
          Measured against the allowances your active grants provide.
        </p>
      </div>
      <div className="grid gap-3">
        <UsageBody enabled={enabled} query={usageQuery} />
      </div>
    </div>
  );
}

function UsageBody({
  enabled,
  query,
}: Readonly<{
  enabled: boolean;
  query: ReturnType<typeof useQuery<Awaited<ReturnType<typeof billingApi.usage>>>>;
}>) {
  if (!enabled || query.isLoading) {
    return (
      <>
        <Skeleton className="h-10 w-full" />
        <Skeleton className="h-10 w-full" />
      </>
    );
  }
  if (query.isError || !query.data) {
    return <Alert tone="danger">Could not load usage. Check your connection and retry.</Alert>;
  }
  if (query.data.status !== 'resolved') {
    return (
      <Alert tone="warning">
        Your entitlement could not be resolved, so usage is unavailable. Contact support if this
        persists.
      </Alert>
    );
  }
  if (query.data.items.length === 0) {
    return <p className="text-muted text-sm">No measurable allowances on this account yet.</p>;
  }
  return (
    <>
      {ordered(query.data.items).map((item) => (
        <UsageMeter key={item.key} item={item} />
      ))}
    </>
  );
}
