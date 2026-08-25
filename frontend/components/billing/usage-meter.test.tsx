import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import type { UsageItem } from '@/lib/api/billing';
import { USAGE_METER_CRITICAL_RATIO, USAGE_METER_WARNING_RATIO } from '@/lib/config/billing';

import { UsageMeter } from './usage-meter';

/**
 * `components/billing` had no colocated tests.
 *
 * The rule this meter exists to enforce is that `limit_state` is the ONLY
 * authority for what the numbers mean. An `unknown` allowance drawn as an empty
 * bar reads as "none left" when it means "we could not resolve this" — the user
 * then believes they are out of quota they may well have. `unlimited` drawn as
 * a bar is the mirror mistake. Both are asserted here as the ABSENCE of a
 * progressbar, which is the thing that would mislead.
 */
function item(overrides: Partial<UsageItem> = {}): UsageItem {
  return {
    key: 'prompt_slots',
    capability_type: 'counter',
    unit: 'slots',
    limit_state: 'finite',
    allowance: 100,
    consumed: 10,
    reserved: 0,
    remaining: 90,
    window_started_at: null,
    resets_at: null,
    earliest_expiry: null,
    grants: [],
    ...overrides,
  } as UsageItem;
}

describe('UsageMeter', () => {
  it('humanises the backend key into a label', () => {
    render(<UsageMeter item={item({ key: 'prompt_slots' })} />);

    expect(screen.getByText('Prompt slots')).toBeVisible();
  });

  it('says an unresolved allowance is unavailable and draws no bar', () => {
    render(<UsageMeter item={item({ limit_state: 'unknown', allowance: null })} />);

    expect(screen.getByText('Not available')).toBeVisible();
    expect(screen.getByText(/could not be resolved/)).toBeVisible();
    // Drawing a meter here would read as "none left".
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('shows consumption with no ceiling for an unlimited allowance', () => {
    render(<UsageMeter item={item({ limit_state: 'unlimited', allowance: null, consumed: 42 })} />);

    expect(screen.getByText('Unlimited')).toBeVisible();
    expect(screen.getByText('42 slots')).toBeVisible();
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument();
  });

  it('treats a null consumption on an unlimited row as zero, not blank', () => {
    render(<UsageMeter item={item({ limit_state: 'unlimited', consumed: null })} />);

    expect(screen.getByText('0 slots')).toBeVisible();
  });

  it('renders a finite row as an accessible progressbar', () => {
    render(<UsageMeter item={item({ allowance: 100, consumed: 25, remaining: 75 })} />);

    const bar = screen.getByRole('progressbar', { name: 'Prompt slots usage' });
    expect(bar).toHaveAttribute('aria-valuemin', '0');
    expect(bar).toHaveAttribute('aria-valuemax', '100');
    expect(bar).toHaveAttribute('aria-valuenow', '25');
    expect(screen.getByText('25 / 100 slots')).toBeVisible();
    expect(screen.getByText(/75 remaining/)).toBeVisible();
  });

  it('does not divide by a zero allowance', () => {
    render(<UsageMeter item={item({ allowance: 0, consumed: 0, remaining: 0 })} />);

    const bar = screen.getByRole('progressbar');
    expect(bar).toHaveAttribute('aria-valuemax', '0');
    expect(bar.firstElementChild).toHaveStyle({ width: '0%' });
  });

  it.each([
    ['normal', 10, 'bg-brand-solid'],
    ['warning', Math.ceil(USAGE_METER_WARNING_RATIO * 100), 'bg-warning-solid'],
    ['critical', Math.ceil(USAGE_METER_CRITICAL_RATIO * 100), 'bg-danger-solid'],
  ])('uses the %s tone at that consumption band', (_name, consumed, tone) => {
    render(<UsageMeter item={item({ allowance: 100, consumed: consumed as number })} />);

    expect(screen.getByRole('progressbar').firstElementChild).toHaveClass(tone as string);
  });

  it('never overfills the bar past full', () => {
    // Over-consumption is possible (a reservation settling high); the bar must
    // clamp rather than overflow its track.
    render(<UsageMeter item={item({ allowance: 100, consumed: 150, remaining: 0 })} />);

    expect(screen.getByRole('progressbar').firstElementChild).toHaveStyle({ width: '100%' });
  });

  it('mentions reserved usage only when some is reserved', () => {
    const { unmount } = render(<UsageMeter item={item({ reserved: 5 })} />);
    expect(screen.getByText(/5 reserved/)).toBeVisible();
    unmount();

    render(<UsageMeter item={item({ reserved: 0 })} />);
    expect(screen.queryByText(/reserved/)).not.toBeInTheDocument();
  });

  it('shows a reset date when the window resets', () => {
    render(<UsageMeter item={item({ resets_at: '2026-09-01T00:00:00Z' })} />);

    expect(screen.getByText(/Resets Sep 1, 2026/)).toBeVisible();
  });

  it('warns that unused credits are forfeited at the earliest expiry', () => {
    render(<UsageMeter item={item({ earliest_expiry: '2026-09-15T00:00:00Z' })} />);

    // A consumable balance that silently disappears is the surprise this line
    // exists to prevent.
    expect(screen.getByText(/Earliest expiry Sep 15, 2026/)).toBeVisible();
    expect(screen.getByText(/forfeited/)).toBeVisible();
  });

  it('prefers the reset date over the expiry when both are present', () => {
    render(
      <UsageMeter
        item={item({ resets_at: '2026-09-01T00:00:00Z', earliest_expiry: '2026-09-15T00:00:00Z' })}
      />,
    );

    expect(screen.getByText(/Resets Sep 1, 2026/)).toBeVisible();
    expect(screen.queryByText(/Earliest expiry/)).not.toBeInTheDocument();
  });

  it('renders no timing line when the row carries neither date', () => {
    render(<UsageMeter item={item()} />);

    expect(screen.queryByText(/Resets|Earliest expiry/)).not.toBeInTheDocument();
  });
});
