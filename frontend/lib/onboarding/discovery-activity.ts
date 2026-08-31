import type { ActivityStep } from '@/components/ui/activity-progress';
import type { BrandDiscovery } from '@/lib/api/brand-discoveries';

type DiscoveryPhase = BrandDiscovery['progress']['phase'];

const PHASE_INDEX: Record<DiscoveryPhase, number> = {
  opening_website: 0,
  understanding_business: 1,
  finding_competitors: 2,
  preparing_review: 3,
  complete: 4,
};

const COMPLETE_STATUSES = new Set<BrandDiscovery['status']>(['ready', 'project_created']);

function currentStep(discovery: BrandDiscovery | undefined): number {
  if (!discovery) return 0;
  if (COMPLETE_STATUSES.has(discovery.status)) return 4;
  return PHASE_INDEX[discovery.progress.phase];
}

function countDetail(
  count: number | undefined,
  adjective: string,
  singular: string,
  plural: string,
  action: string,
): string | undefined {
  if (!count) return undefined;
  const noun = count === 1 ? singular : plural;
  return `${count} ${adjective} ${noun} ${action}`;
}

function stepState(index: number, current: number): ActivityStep['state'] {
  if (index < current) return 'complete';
  if (index > current) return 'pending';
  return 'active';
}

/**
 * Convert persisted discovery facts into customer language. Unknown backend
 * details never become a copy fallback; adding a phase must be handled here.
 */
export function discoveryActivity(discovery: BrandDiscovery | undefined): ActivityStep[] {
  const current = currentStep(discovery);
  const progress = discovery?.progress;
  const labels = [
    'Opening your website',
    'Understanding what you offer',
    'Finding comparable brands',
    'Preparing your review',
  ] as const;
  const details = [
    countDetail(progress?.pages_read, 'useful', 'page', 'pages', 'read') ??
      'Checking that your website can be read.',
    'Learning what you offer and who it is most useful for.',
    countDetail(progress?.competitors_found, 'comparable', 'brand', 'brands', 'found') ??
      'Looking for genuinely comparable brands.',
    'Organizing the strongest findings for your review.',
  ] as const;
  return labels.map((label, index) => ({
    id: label,
    label,
    detail: details[index],
    state: stepState(index, current),
  }));
}
