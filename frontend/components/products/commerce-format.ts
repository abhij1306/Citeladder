import type { StatusValue } from '@/components/ui/badge-variants';

/**
 * Discovery status as a sentence, not a status string dropped into one.
 * Interpolating the raw value produced "Discovery for this category is
 * succeeded", and `unavailable` read as success to anyone skimming.
 */
export function discoveryMessage(status: string, kind: string, errorCode: string): string {
  if (status === 'succeeded') return `Discovery finished for this ${kind}.`;
  if (status === 'cancelled') return `Discovery was cancelled for this ${kind}.`;
  if (status === 'failed') {
    if (errorCode === 'unusable_target') {
      return `This ${kind} needs a clearer name before competitors can be found.`;
    }
    if (errorCode === 'provider_unavailable') {
      return 'Competitor discovery is unavailable: no search provider is configured.';
    }
    return `Discovery failed for this ${kind}${errorCode ? ` (${errorCode})` : ''}.`;
  }
  return `Finding competitors for this ${kind}…`;
}

/** The candidate's domain — what a person recognises as "who is this?". */
export function competitorHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

const COMPETITOR_TONES: Record<string, StatusValue> = {
  approved: 'success',
  rejected: 'danger',
  excluded: 'danger',
  pending: 'info',
};

export function competitorTone(state: string): StatusValue {
  return COMPETITOR_TONES[state] ?? 'info';
}
