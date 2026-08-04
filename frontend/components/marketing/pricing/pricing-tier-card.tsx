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
        'shadow-card flex h-full flex-col rounded-lg p-8',
        highlighted ? 'bg-background-alt ring-accent ring-1' : 'bg-panel',
      )}
    >
      <div className="flex items-center justify-between gap-4">
        <h3 className="font-display text-foreground text-xl">{plan.name}</h3>
        {highlighted && (
          <Badge variant="status" value="info">
            Recommended
          </Badge>
        )}
      </div>
      <p className="text-muted mt-3 min-h-[3rem] text-sm">
        {presentation?.blurb ?? plan.description}
      </p>

      {/* The price rides the website's own display rung, not the app's
          `text-hero`: an app token on this surface drifts with the dashboard
          ladder rather than the site's. */}
      <p className="text-foreground mt-5 flex items-baseline gap-2 font-mono text-4xl tabular-nums">
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

      {/* Each capability leads with a check glyph and reads as a sentence:
          "Prompts tracked — 250". The raw `snake_case` key used to render
          verbatim, so the list read as a database dump rather than a list of
          what you get. Tight 10px rhythm — a feature list is a scan target,
          not prose.

          Absent capabilities are dropped BEFORE the cap, not after: the glyph
          is a success tick, so an absent value rendered "Label — —" behind a
          tick, and dropping it late would also spend one of the five slots on
          something the tier does not include. */}
      <ul className="border-border-subtle mt-5 grid flex-1 gap-3 border-t pt-5">
        {plan.capabilities
          .filter((capability) => isIncluded(capability.value))
          .slice(0, 5)
          .map((capability) => (
            <li key={capability.key} className="text-muted flex items-start gap-3 text-sm">
              {/* The glyph sits in a box as tall as the text's first line, so
                  it stays optically aligned on wrapped items without a nudge
                  margin — a margin here would be an off-ladder one-off, which
                  is exactly what this system exists to prevent. */}
              <span aria-hidden className="flex h-[1lh] shrink-0 items-center text-sm">
                <Check className="text-success size-4" />
              </span>
              <span>
                {capabilityLabel(capability.key)}
                {renderValue(capability.value) !== 'Included' && (
                  <>
                    {' — '}
                    <span className="text-foreground font-medium">
                      {renderValue(capability.value)}
                    </span>
                  </>
                )}
              </span>
            </li>
          ))}
      </ul>

      <div className="mt-5">
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
      <a
        href={plan.contact_url ?? '/demo'}
        className="border-border-subtle text-foreground focus-ring inline-flex h-10 w-full items-center justify-center rounded-md border text-sm font-medium"
      >
        {CONTACT_LABEL}
      </a>
    );
  }
  // Funded mode is unpurchasable while `credit_price` is null: the button is
  // present but disabled, so the state is visible rather than the CTA
  // vanishing and the card silently losing its call to action.
  const disabled = priceKind !== 'price' || pending;
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onCheckout(plan)}
      className="bg-accent text-inverse focus-ring inline-flex h-10 w-full items-center justify-center rounded-md text-sm font-medium disabled:cursor-not-allowed disabled:opacity-60"
    >
      {pending ? 'Starting checkout…' : `Choose ${plan.name}`}
    </button>
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
