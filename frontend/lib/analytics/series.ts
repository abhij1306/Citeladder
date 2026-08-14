/** Display-only helpers for the persisted AI-referral projection. */
import type { TrendPoint } from '@/components/ui/trend-chart';
import type { AiReferrals, AiSource } from '@/lib/api/analytics';
import { formatShortDate } from '@/lib/format';

export { formatCount as formatInt } from '@/lib/format';

type SeriesPoint = { date: string; value: number | null };

export function toCountChartPoints(points: readonly SeriesPoint[]): TrendPoint[] {
  return points.map((point) => ({
    label: formatShortDate(point.date),
    value: point.value === null ? null : Math.round(point.value),
  }));
}

export function toPercentChartPoints(points: readonly SeriesPoint[]): TrendPoint[] {
  return points.map((point) => ({
    label: formatShortDate(point.date),
    value: point.value === null ? null : Math.round(point.value * 1000) / 10,
  }));
}

export function countDomainMax(values: readonly number[]): number {
  const max = values.length ? Math.max(...values) : 0;
  if (max <= 100) return 100;
  const magnitude = 10 ** Math.floor(Math.log10(max));
  return Math.ceil(max / magnitude) * magnitude;
}

export function countYLabels(domainMax: number): string[] {
  return [1, 0.75, 0.5, 0.25, 0].map((fraction) => `${Math.round(domainMax * fraction)}`);
}

export function formatPercent(fraction: number | null, decimals = 0): string {
  if (fraction === null) return '—';
  return `${(fraction * 100).toFixed(decimals)}%`;
}

export const AI_SOURCE_LABELS: Record<AiSource, string> = {
  chatgpt: 'ChatGPT',
  gemini: 'Gemini',
  claude: 'Claude',
  perplexity: 'Perplexity',
  copilot: 'Copilot',
  google_ai_overview: 'Google AI Overview',
  other: 'Other',
};

export function aiSourceLabel(source: AiSource): string {
  return AI_SOURCE_LABELS[source] ?? source;
}

export function totalSourceSessions(sources: AiReferrals['sources']): number {
  return sources.reduce((sum, row) => sum + row.sessions, 0);
}

export function isAnalyticsEmpty(data: AiReferrals): boolean {
  return data.referral_volume.length === 0 && data.referral_share.length === 0;
}
