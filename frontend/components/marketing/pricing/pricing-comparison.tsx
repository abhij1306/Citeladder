'use client';

import { Check } from 'lucide-react';

import type { BillingCatalog } from '@/lib/api/billing';
import { comparisonRows } from '@/lib/billing/catalog';
import { capabilityLabel } from '@/lib/marketing-content/pricing';
import { cn } from '@/lib/utils';

/**
 * Compact plan comparison grid.
 *
 * Rows come from the union of capability keys the plans publish, so a new
 * backend capability appears here without a frontend change. Dense padding,
 * sticky capability column, and semantic check/dash cells keep the table
 * scannable without a wall of whitespace.
 */
export function PricingComparison({ catalog }: Readonly<{ catalog: BillingCatalog }>) {
  const rows = comparisonRows(catalog);
  if (rows.length === 0) return null;

  return (
    <div className="border-border-subtle bg-panel overflow-hidden rounded-[var(--radius-card)] border">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] border-collapse text-left">
          <thead>
            <tr className="border-border-subtle bg-background-alt border-b">
              <th
                scope="col"
                className="text-muted bg-background-alt sticky left-0 z-1 px-4 py-3 text-xs font-medium tracking-wide uppercase"
              >
                Capability
              </th>
              {catalog.plans.map((plan) => (
                <th
                  key={plan.key}
                  scope="col"
                  className="text-foreground px-4 py-3 text-sm font-medium whitespace-nowrap"
                >
                  {plan.name}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row, index) => (
              <tr
                key={row.key}
                className={cn(
                  'border-border-subtle border-b last:border-b-0',
                  index % 2 === 1 && 'bg-background-alt/60',
                )}
              >
                <th
                  scope="row"
                  className={cn(
                    'text-foreground sticky left-0 z-1 px-4 py-2.5 text-sm font-medium',
                    index % 2 === 1 ? 'bg-background-alt' : 'bg-panel',
                  )}
                >
                  {capabilityLabel(row.key)}
                </th>
                {catalog.plans.map((plan) => (
                  <td key={plan.key} className="text-muted px-4 py-2.5 text-sm whitespace-nowrap">
                    {renderCell(row.values[plan.key]?.value)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/**
 * A capability a plan does not publish renders as an em dash — the honest
 * "not included", distinct from a published zero. Booleans use a success check
 * so the table stays compact and colour is never the only signal.
 */
function renderCell(value: boolean | number | string | null | undefined) {
  if (value === undefined || value === null) {
    return <span className="text-subtle">—</span>;
  }
  if (typeof value === 'boolean') {
    return value ? (
      <span className="text-success-text inline-flex items-center gap-1.5 font-medium">
        <Check aria-hidden strokeWidth={2.5} className="size-3.5" />
        <span className="sr-only">Included</span>
      </span>
    ) : (
      <span className="text-subtle">—</span>
    );
  }
  return <span className="text-foreground tabular-nums">{String(value)}</span>;
}
