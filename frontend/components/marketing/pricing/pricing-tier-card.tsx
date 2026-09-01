'use client';

import { Check } from 'lucide-react';

import type { BillingCatalog, CatalogPlan, CredentialMode } from '@/lib/api/billing';
import { formatMoney, headlinePrice, majorUnits } from '@/lib/billing/catalog';
import { planMonthlyPriceUsdMinor } from '@/lib/config/billing';
import {
  CONTACT_LABEL,
  FUNDED_UNAVAILABLE_LABEL,
  PLAN_PRESENTATION,
  type PlanKey,
  capabilityLabel,
} from '@/lib/marketing-content/pricing';
import { cn } from '@/lib/utils';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { AnimatedPrice } from './animated-price';

/**
 * One plan card. Every enforceable value — name, price, capabilities — comes
 * from the catalog entry; only the blurb and the emphasis come from the
 * presentation module.
 *
 * `data-tier` / `data-price` / `data-highlighted` are structural test hooks:
 * with utility CSS there is no meaningful class to query, and a plan name is
 * ambiguous once it also heads a comparison column.
 */
export function PricingTierCard({
  plan,
  catalog,
  mode,
  onCheckout,
  pending,
}: Readonly<{
  plan: CatalogPlan;
  catalog: BillingCatalog;
  mode: CredentialMode;
  /** Runs the checkout (or captures an intent when anonymous). */
  onCheckout: (plan: CatalogPlan) => void;
  pending: boolean;
}>) {
  const presentation = PLAN_PRESENTATION[plan.key as PlanKey];
  const catalogPrice = headlinePrice(plan, mode);
  const marketingAmount = planMonthlyPriceUsdMinor(plan.key, mode);
  const price =
    marketingAmount === null
      ? catalogPrice
      : {
          kind: 'price' as const,
          money: { currency: 'USD' as const, amount_minor: marketingAmount },
        };
  const highlighted = presentation?.highlighted ?? false;

  const numeric =
    price.kind === 'price' ? majorUnits(price.money, catalog.currency_minor_units) : null;
  const settled =
    price.kind === 'price'
      ? formatMoney(price.money, catalog.currency_minor_units)
      : price.kind === 'contact'
        ? CONTACT_LABEL
        : FUNDED_UNAVAILABLE_LABEL;

  return (
    <div
      data-tier={plan.key}
      data-highlighted={highlighted ? 'true' : undefined}
      className={cn(
        'border-border-subtle flex h-full flex-col rounded-[var(--radius-card)] border p-6 md:p-7 xl:p-6',
        highlighted ? 'bg-background-alt ring-accent ring-1' : 'bg-panel',
      )}
    >
      <div className="flex min-h-7 items-center justify-between gap-3">
        <h3 className="website-feature-heading text-foreground">{plan.name}</h3>
        {highlighted && (
          <Badge variant="status" value="info">
            Recommended
          </Badge>
        )}
      </div>
      <p className="website-body text-muted mt-3 min-h-[3rem] max-w-[32ch]">
        {presentation?.blurb ?? plan.description}
      </p>

      {/* The price rides the website's own display rung, not the app's
          `text-hero`: an app token on this surface drifts with the dashboard
          ladder rather than the site's. */}
      <p className="website-data-display text-foreground mt-6 flex min-h-[2.875rem] items-baseline gap-2">
        <AnimatedPrice
          value={numeric}
          format={(value) =>
            formatMoney(
              {
                currency: catalog.currency,
                amount_minor: value * 10 ** catalog.currency_minor_units,
              },
              catalog.currency_minor_units,
            )
          }
          announce={settled}
        />
        {price.kind === 'price' && (
          <span className="text-muted text-sm font-normal">per month</span>
        )}
      </p>

      {/* Labels and values occupy separate edges so every limit scans as a
          compact row instead of wrapping around punctuation. Absent
          capabilities are dropped before the five-row cap because the check
          glyph communicates inclusion. */}
      <ul className="border-border-subtle mt-6 grid flex-1 content-start gap-1 border-t pt-4">
        {plan.capabilities
          .filter((capability) => isIncluded(capability.value))
          .slice(0, 5)
          .map((capability) => {
            const value = renderValue(capability.value);
            return (
              <li
                key={capability.key}
                className="text-secondary flex min-h-9 items-center justify-between gap-3 text-sm"
              >
                <span className="flex min-w-0 items-center gap-2.5">
                  <Check aria-hidden className="text-accent size-4 shrink-0" />
                  <span>{capabilityLabel(capability.key)}</span>
                </span>
                {value !== 'Included' && (
                  <span className="text-foreground shrink-0 font-medium tabular-nums">{value}</span>
                )}
              </li>
            );
          })}
      </ul>

      <div className="mt-6">
        <PlanCta
          plan={plan}
          priceKind={catalogPrice.kind}
          onCheckout={onCheckout}
          pending={pending}
        />
      </div>
    </div>
  );
}

function PlanCta({
  plan,
  priceKind,
  onCheckout,
  pending,
}: Readonly<{
  plan: CatalogPlan;
  priceKind: 'price' | 'contact' | 'unavailable';
  onCheckout: (plan: CatalogPlan) => void;
  pending: boolean;
}>) {
  if (plan.contact_only) {
    return (
      <Button asChild variant="secondary" className="w-full">
        <a href={plan.contact_url ?? '/demo'}>{CONTACT_LABEL}</a>
      </Button>
    );
  }
  // Funded mode is unpurchasable while `credit_price` is null: the button is
  // present but disabled, so the state is visible rather than the CTA
  // vanishing and the card silently losing its call to action.
  const disabled = priceKind !== 'price' || pending;
  return (
    <Button disabled={disabled} onClick={() => onCheckout(plan)} className="w-full">
      {pending ? 'Starting checkout…' : `Choose ${plan.name}`}
    </Button>
  );
}

/**
 * Whether the tier carries this capability at all. `null` (not applicable) and
 * `false` (explicitly absent) both mean it does not.
 */
function isIncluded(value: boolean | number | string | null): boolean {
  return value !== null && value !== false;
}

function renderValue(value: boolean | number | string | null): string {
  if (value === null) return '—';
  if (typeof value === 'boolean') return value ? 'Included' : '—';
  return String(value);
}
