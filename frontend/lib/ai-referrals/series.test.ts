import { describe, expect, it } from 'vitest';

import { countDomainMax, formatPercent, isAiReferralsEmpty, toCountChartPoints } from './series';

describe('AI referral display helpers', () => {
  it('preserves unavailable points and formats persisted fractions', () => {
    expect(toCountChartPoints([{ date: '2026-08-01', value: null }])[0]?.value).toBeNull();
    expect(formatPercent(0.125, 1)).toBe('12.5%');
    expect(formatPercent(null)).toBe('Not measured');
  });

  it('uses a readable count scale and honest empty state', () => {
    expect(countDomainMax([101, 199])).toBe(200);
    expect(isAiReferralsEmpty({ referral_volume: [], referral_share: [] } as never)).toBe(true);
  });
});
