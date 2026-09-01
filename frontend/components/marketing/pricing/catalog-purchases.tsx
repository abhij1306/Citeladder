'use client';

import type { BillingCatalog, CatalogAddon, CatalogTopup } from '@/lib/api/billing';
import { formatMoney, isPurchasable } from '@/lib/billing/catalog';

/**
 * Add-ons and top-ups, rendered generically.
 *
 * There is no key-specific branch here: whatever the catalog publishes
 * renders, including entries added after this file was written. An entry with
 * no `unit_price` is UNPRICED, which is not the same as free — it renders as
 * unavailable and cannot start a mutation.
 */
/**
 * Turn an API reason code into a sentence. These are enum values from the
 * billing contract (`not_yet_priced`, `contact_sales`, …) and were rendering
 * verbatim, so a customer saw `not_yet_priced` under a disabled button. Unknown
 * codes fall back to a de-underscored form rather than being swallowed — a new
 * reason should still say something rather than nothing.
 */
function reasonLabel(reason: string): string {
  const KNOWN: Record<string, string> = {
    not_yet_priced: 'Pricing to be announced.',
    contact_sales: 'Available through sales.',
    funded_not_priced: 'Not available on funded credits yet.',
    trial_unavailable: 'No trial on this item.',
  };
  if (Object.hasOwn(KNOWN, reason)) return KNOWN[reason];
  const words = reason.replaceAll('_', ' ');
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}.`;
}

export function CatalogPurchases({
  catalog,
  onActivateAddon,
  onPurchaseTopup,
  pendingKey,
}: Readonly<{
  catalog: BillingCatalog;
  onActivateAddon: (addon: CatalogAddon) => void;
  onPurchaseTopup: (topup: CatalogTopup) => void;
  pendingKey: string | null;
}>) {
  if (catalog.addons.length === 0 && catalog.topups.length === 0) return null;

  return (
    <div className="grid gap-8">
      {catalog.addons.length > 0 && (
        <section aria-label="Add-ons" className="grid gap-4">
          <h3 className="website-feature-heading text-foreground">Add-ons</h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {catalog.addons.map((addon) => (
              <PurchaseRow
                key={addon.key}
                entry={addon}
                catalog={catalog}
                cadence="per month"
                pending={pendingKey === addon.key}
                onPurchase={() => onActivateAddon(addon)}
              />
            ))}
          </div>
        </section>
      )}

      {catalog.topups.length > 0 && (
        <section aria-label="Top-ups" className="grid gap-4">
          <h3 className="website-feature-heading text-foreground">Top-ups</h3>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {catalog.topups.map((topup) => (
              <PurchaseRow
                key={topup.key}
                entry={topup}
                catalog={catalog}
                cadence="one-off"
                pending={pendingKey === topup.key}
                onPurchase={() => onPurchaseTopup(topup)}
                // Forfeiture has to be visible AT PURCHASE, not only later on
                // the usage meter — it is a term of the sale.
                footnote={`Credits expire ${topup.expiry_days} days after purchase; unused credits are forfeited.`}
              />
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function PurchaseRow({
  entry,
  catalog,
  cadence,
  pending,
  onPurchase,
  footnote,
}: Readonly<{
  entry: CatalogAddon | CatalogTopup;
  catalog: BillingCatalog;
  cadence: string;
  pending: boolean;
  onPurchase: () => void;
  footnote?: string;
}>) {
  const purchasable = isPurchasable(entry);
  return (
    // A compact tile in a grid, not a full-width band: 20px padding and a 6px
    // internal rhythm. These are secondary purchases sitting under the plan
    // cards, so each one stacked at card scale made the section longer than
    // the plans it supplements.
    <div
      data-catalog-key={entry.key}
      className="border-border-subtle bg-panel flex flex-col gap-2 rounded-[var(--radius-card)] border p-5"
    >
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <span className="text-foreground text-sm font-medium">{entry.name}</span>
        <span className="text-foreground text-sm tabular-nums">
          {entry.unit_price
            ? `${formatMoney(entry.unit_price, catalog.currency_minor_units)} ${cadence}`
            : 'Not yet priced'}
        </span>
      </div>
      <p className="website-body text-muted flex-1">{entry.description}</p>
      {footnote && <p className="website-body text-muted">{footnote}</p>}
      <button
        type="button"
        disabled={!purchasable || pending}
        onClick={onPurchase}
        className="border-border-subtle text-foreground focus-ring mt-2 inline-flex h-8 w-fit items-center justify-center rounded-full border px-4 text-xs font-medium disabled:cursor-not-allowed disabled:opacity-60"
      >
        {pending ? 'Starting…' : `Add ${entry.name}`}
      </button>
      {!purchasable && entry.unavailable_reason && (
        <p className="website-body text-muted">{reasonLabel(entry.unavailable_reason)}</p>
      )}
    </div>
  );
}
