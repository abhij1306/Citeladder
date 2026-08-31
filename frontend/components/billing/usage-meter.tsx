'use client';

import { USAGE_METER_CRITICAL_RATIO, USAGE_METER_WARNING_RATIO } from '@/lib/config/billing';
import type { UsageItem } from '@/lib/api/billing';

/**
 * One usage counter.
 *
 * `limit_state` is the ONLY authority for what the numbers mean. The backend
 * never uses null to mean both "unlimited" and "unresolved", so neither does
 * this component: an `unlimited` row shows what has been consumed with no bar
 * and no ceiling, and an `unknown` row says so rather than rendering zero. A
 * missing allowance is never drawn as an empty meter — that reads as "none
 * left" when it means "we don't know".
 */
export function UsageMeter({ item }: Readonly<{ item: UsageItem }>) {
  const label = humanizeKey(item.key);

  if (item.limit_state === 'unknown') {
    return (
      <div className="border-border-subtle grid gap-1 border-b pb-3 last:border-b-0 last:pb-0">
        <div className="flex items-center justify-between gap-3">
          <span className="text-secondary text-xs font-medium">{label}</span>
          <span className="text-muted text-xs font-medium">Not available</span>
        </div>
        <p className="text-muted text-xs">
          This allowance could not be resolved, so no usage is shown.
        </p>
      </div>
    );
  }

  if (item.limit_state === 'unlimited') {
    return (
      <div className="border-border-subtle grid gap-1 border-b pb-3 last:border-b-0 last:pb-0">
        <div className="flex items-center justify-between gap-3">
          <span className="text-secondary text-xs font-medium">{label}</span>
          <span className="text-foreground font-mono text-xs font-medium tabular-nums">
            {item.consumed ?? 0} {item.unit}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted text-xs">Unlimited</span>
          <ExpiryLine item={item} />
        </div>
      </div>
    );
  }

  // `finite`: the backend guarantees every numeric aggregate is present.
  const allowance = item.allowance ?? 0;
  const consumed = item.consumed ?? 0;
  const remaining = item.remaining ?? 0;
  const ratio = allowance > 0 ? consumed / allowance : 0;
  const tone =
    ratio >= USAGE_METER_CRITICAL_RATIO
      ? 'bg-danger-solid'
      : ratio >= USAGE_METER_WARNING_RATIO
        ? 'bg-warning-solid'
        : 'bg-brand-solid';

  return (
    <div className="border-border-subtle grid gap-1.5 border-b pb-3.5 last:border-b-0 last:pb-0">
      <div className="flex items-center justify-between gap-3">
        <span className="text-secondary text-xs font-medium">{label}</span>
        <span className="text-foreground font-mono text-xs font-medium tabular-nums">
          {consumed} / {allowance} {item.unit}
        </span>
      </div>
      <div
        // oxlint-disable-next-line jsx-a11y/prefer-tag-over-role -- Native progress cannot preserve the token-driven inner fill and reserved-credit presentation.
        role="progressbar"
        aria-label={`${label} usage`}
        aria-valuemin={0}
        aria-valuemax={allowance}
        aria-valuenow={consumed}
        className="bg-surface-sunken h-1.5 overflow-hidden rounded-full"
      >
        <div
          className={`h-full rounded-full transition-all ${tone}`}
          style={{ width: `${Math.min(100, Math.round(ratio * 100))}%` }}
        />
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-muted text-xs">
          {remaining} remaining
          {item.reserved ? ` · ${item.reserved} reserved` : ''}
        </span>
        <ExpiryLine item={item} />
      </div>
    </div>
  );
}

/**
 * Reset and expiry copy. Consumable balances forfeit at expiry, so that has to
 * be visible next to the balance rather than only at purchase.
 */
function ExpiryLine({ item }: Readonly<{ item: UsageItem }>) {
  if (item.resets_at) {
    return <p className="text-muted text-xs">Resets {formatDate(item.resets_at)}.</p>;
  }
  if (item.earliest_expiry) {
    return (
      <p className="text-muted text-xs">
        Earliest expiry {formatDate(item.earliest_expiry)} — unused credits are forfeited then.
      </p>
    );
  }
  return null;
}

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('en-US', { dateStyle: 'medium', timeZone: 'UTC' });
}

/** `prompt_slots` → `Prompt slots`. The key is the backend's, the label is ours. */
function humanizeKey(key: string) {
  const words = key.replaceAll('_', ' ');
  return words.charAt(0).toUpperCase() + words.slice(1);
}
