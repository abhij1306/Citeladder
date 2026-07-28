import { ArrowRight, Check, Minus } from 'lucide-react';

import { DEMO_CTA, DEMO_HREF } from '@/lib/marketing-content/nav';
import { PRICING_NOTE, PRICING_TABLE_ROWS, PRICING_TIERS } from '@/lib/marketing-content/pricing';
import type { PricingTier } from '@/lib/marketing-content/pricing';
import { cn } from '@/lib/utils';

import { Badge } from '../primitives/badge';
import { ButtonLink } from '../primitives/button';
import { Meta } from '../primitives/label';
import { Section, SectionHeader } from '../primitives/section';
import { Reveal, StaggerGroup, StaggerItem } from '../primitives/reveal';

/**
 * Pricing (`/pricing`). Every published price, quota and comparison row
 * renders verbatim from `@/lib/marketing-content/pricing` — that module is
 * the single source for commercial terms. Change a term there, never here.
 */
const TIER_KEYS = PRICING_TIERS.map((tier) => tier.key);
const TIERS_BY_KEY = new Map(PRICING_TIERS.map((tier) => [tier.key, tier]));

export function PricingTiers() {
  return (
    <Section tone="surface" rhythm="tight" aria-label="Plans">
      <StaggerGroup className="grid gap-4 md:grid-cols-3">
        {PRICING_TIERS.map((tier) => (
          <StaggerItem key={tier.key} className="h-full">
            <TierCard tier={tier} />
          </StaggerItem>
        ))}
      </StaggerGroup>
      <p className="text-mkt-sm text-mkt-ink-muted mt-8 max-w-[80ch]">{PRICING_NOTE}</p>
    </Section>
  );
}

function TierCard({ tier }: Readonly<{ tier: PricingTier }>) {
  // A "Custom" price has no per-period label — its cadence drops to the note
  // line so the price row keeps the same optical weight across all three cards.
  const isCustom = tier.price === 'Custom';
  return (
    <div
      // Structural test hooks. With utility CSS there is no meaningful class
      // to query, and the tier name alone is ambiguous once it also appears
      // as a comparison-table column header.
      data-tier={tier.key}
      data-highlighted={tier.highlighted ? 'true' : undefined}
      className={cn(
        'rounded-mkt-lg shadow-card flex h-full flex-col p-7',
        tier.highlighted ? 'bg-mkt-wash ring-mkt-proof-line ring-1' : 'bg-mkt-surface',
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <h3 className="font-mkt-display text-mkt-ink text-heading-sm font-semibold">{tier.name}</h3>
        {tier.highlighted && <Badge tone="proof">Recommended</Badge>}
      </div>
      <p className="text-mkt-sm text-mkt-ink-soft mt-2 min-h-[3rem]">{tier.blurb}</p>

      <p
        data-price
        className="text-mkt-ink text-hero mt-4 flex items-baseline gap-1.5 font-mono leading-none font-medium tabular-nums"
      >
        {tier.price}
        {!isCustom && (
          <span className="text-mkt-ink-muted text-mkt-sm font-normal">{tier.cadence}</span>
        )}
      </p>
      {isCustom && (
        <Meta as="p" className="mt-2.5">
          {tier.cadence}
        </Meta>
      )}

      <ul className="border-mkt-line-soft mt-6 grid gap-3 border-t pt-6">
        {tier.features.map((feature) =>
          feature.startsWith('Everything in') ? (
            <li key={feature} className="text-mkt-sm text-mkt-ink font-semibold">
              {feature}
            </li>
          ) : (
            <li key={feature} className="text-mkt-sm text-mkt-ink-soft flex gap-2.5">
              <Check
                aria-hidden
                strokeWidth={2.5}
                className="text-mkt-evidence-text mt-0.5 size-3.5 shrink-0"
              />
              {feature}
            </li>
          ),
        )}
      </ul>

      <div className="mt-8 pt-2">
        <ButtonLink
          href={tier.cta.href}
          intent={tier.primaryCta ? 'primary' : 'secondary'}
          className="w-full"
        >
          {tier.cta.label}
          {tier.primaryCta && <ArrowRight className="size-3.5" aria-hidden />}
        </ButtonLink>
      </div>
    </div>
  );
}

export function PricingTable() {
  return (
    <Section tone="paper" aria-labelledby="pricing-compare-title">
      <SectionHeader
        kicker="Compare plans"
        title="Same evidence engine. Different dials."
        intro="Every plan runs the same deterministic engine. Tiers differ on monitoring scope, web-search grounding, exports and support."
        headingId="pricing-compare-title"
      />
      <Reveal className="rounded-mkt-lg bg-mkt-surface shadow-card overflow-hidden">
        {/* The table is wider than a phone: it scrolls inside its own box so
            the page body never scrolls sideways. */}
        <div className="overflow-x-auto">
          <table className="w-full min-w-[46rem] border-collapse text-left">
            <thead>
              <tr className="border-mkt-line-soft bg-mkt-paper-raised border-b">
                <th scope="col" className="text-mkt-meta text-mkt-ink-muted p-4 uppercase">
                  Capability
                </th>
                {PRICING_TIERS.map((tier) => (
                  <th
                    key={tier.key}
                    scope="col"
                    data-highlighted={tier.highlighted ? 'true' : undefined}
                    className={cn(
                      'text-mkt-sm text-mkt-ink p-4 text-center font-semibold',
                      tier.highlighted && 'bg-mkt-wash text-mkt-proof',
                    )}
                  >
                    {tier.name}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {PRICING_TABLE_ROWS.map((row) => (
                <tr key={row.dimension} className="border-mkt-line-soft border-b last:border-b-0">
                  <th scope="row" className="text-mkt-sm text-mkt-ink-soft p-4 font-normal">
                    {row.dimension}
                  </th>
                  {TIER_KEYS.map((key) => (
                    <TableCell
                      key={key}
                      value={row[key]}
                      highlighted={Boolean(TIERS_BY_KEY.get(key)?.highlighted)}
                    />
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Reveal>
    </Section>
  );
}

/**
 * One comparison cell. The content module encodes booleans as '✓' / '—'; both
 * render as icons WITH screen-reader text, so the cell never conveys its
 * value by glyph alone.
 */
function TableCell({ value, highlighted }: Readonly<{ value: string; highlighted: boolean }>) {
  const base = cn('p-4 text-center text-mkt-sm', highlighted && 'bg-mkt-wash');

  if (value === '✓' || value === '—') {
    const included = value === '✓';
    const Icon = included ? Check : Minus;
    return (
      <td className={base}>
        <Icon
          aria-hidden
          strokeWidth={2.4}
          className={cn(
            'mx-auto size-4',
            included ? 'text-mkt-evidence-text' : 'text-mkt-line-strong',
          )}
        />
        <span className="sr-only">{included ? 'Included' : 'Not included'}</span>
      </td>
    );
  }
  return <td className={cn(base, 'text-mkt-ink-soft')}>{value}</td>;
}

/** Closing band — evaluation first, then the workspace. */
export function PricingCta() {
  return (
    <Section tone="sunken" rhythm="loose" aria-label="Get started">
      <Reveal className="mx-auto max-w-3xl text-center">
        <h2 className="font-mkt-display text-mkt-d2 text-mkt-ink mx-auto mb-5 max-w-[18ch] font-medium">
          Start from the evidence, not the invoice.
        </h2>
        <p className="text-mkt-lead text-mkt-ink-soft mx-auto max-w-[54ch]">
          Walk through your own category with us, then pick the plan that matches the volume you
          actually need.
        </p>
        <div className="mt-9 flex flex-col items-center justify-center gap-2.5 sm:flex-row">
          <ButtonLink href={DEMO_HREF} className="w-full sm:w-auto">
            {DEMO_CTA}
            <ArrowRight className="size-3.5" aria-hidden />
          </ButtonLink>
          <ButtonLink href="/faq" intent="secondary" className="w-full sm:w-auto">
            Read the FAQ
          </ButtonLink>
        </div>
      </Reveal>
    </Section>
  );
}
