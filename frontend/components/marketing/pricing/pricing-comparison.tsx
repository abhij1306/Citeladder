'use client';

import type { BillingCatalog } from '@/lib/api/billing';
import { comparisonRows } from '@/lib/billing/catalog';
import { capabilityLabel } from '@/lib/marketing-content/pricing';

/**
 * The plan comparison grid.
 *
 * Rows are derived from the union of capability keys the plans publish, so a
 * new backend capability appears here without a frontend change — and a value
 * this page shows is always a value the backend will actually enforce. No
 * limit is written into this component.
 */
export function PricingComparison({ catalog }: Readonly<{ catalog: BillingCatalog }>) {
  const rows = comparisonRows(catalog);
  if (rows.length === 0) return null;

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[40rem] border-collapse text-left">
        <thead>
          <tr className="border-border-subtle border-b">
            <th scope="col" className="text-foreground p-5 text-sm font-semibold">
              Capability
            </th>
            {catalog.plans.map((plan) => (
              <th key={plan.key} scope="col" className="text-foreground p-5 text-sm font-semibold">
                {plan.name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key} className="border-border-subtle border-b">
              <th scope="row" className="text-muted p-5 text-sm font-normal">
                {capabilityLabel(row.key)}
              </th>
              {catalog.plans.map((plan) => (
                <td key={plan.key} className="text-muted p-5 text-sm">
                  {renderCell(row.values[plan.key]?.value)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * A capability a plan does not publish renders as an em dash — the honest
 * "not included", distinct from a published zero.
 */
function renderCell(value: boolean | number | string | null | undefined): string {
  if (value === undefined || value === null) return '—';
  if (typeof value === 'boolean') return value ? '✓' : '—';
  return String(value);
}
