import type { UseQueryResult } from '@tanstack/react-query';

import { AiReferralsEmptyState } from '@/components/ai-referrals/empty-state';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { type AiReferralsRange } from '@/lib/ai-referrals/options';
import { isAiReferralsEmpty } from '@/lib/ai-referrals/series';
import { formatWindowDate } from '@/lib/format';
import type { AiReferrals } from '@/lib/api/ai-referrals';

import { AiReferralsDashboard } from './ai-referrals-dashboard';
import { AiReferralsSkeleton } from './ai-referrals-skeleton';

export function AiReferralsContent({
  projectId,
  projectLoading,
  range,
  windowBounds,
  query,
  toolbar,
}: Readonly<{
  projectId: string | null;
  projectLoading: boolean;
  range: AiReferralsRange;
  windowBounds: { from?: string; to?: string };
  query: UseQueryResult<AiReferrals, Error>;
  toolbar: React.ReactNode;
}>) {
  if (projectLoading || (Boolean(projectId) && query.isLoading)) return <AiReferralsSkeleton />;
  if (!projectId) return <Alert tone="info">Select or create a project to see AI referrals.</Alert>;
  if (query.isError) return <AiReferralsError onRetry={() => query.refetch()} />;

  const data = query.data ?? null;
  if (!data || (isAiReferralsEmpty(data) && range === 'latest')) return <AiReferralsEmptyState />;
  if (isAiReferralsEmpty(data))
    return <AiReferralsNoSnapshot toolbar={toolbar} windowBounds={windowBounds} />;

  return <AiReferralsDashboard data={data} toolbar={toolbar} fetching={query.isFetching} />;
}

function AiReferralsError({ onRetry }: Readonly<{ onRetry: () => void }>) {
  return (
    <Alert tone="danger">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <span>AI referrals could not be loaded. Check your connection and try again.</span>
        <Button variant="secondary" size="sm" onClick={onRetry}>
          Retry
        </Button>
      </div>
    </Alert>
  );
}

function AiReferralsNoSnapshot({
  toolbar,
  windowBounds,
}: Readonly<{ toolbar: React.ReactNode; windowBounds: { from?: string; to?: string } }>) {
  return (
    <div className="grid gap-[var(--workspace-gap)]">
      {toolbar}
      <Alert tone="info">
        No synced AI-referral snapshot covers {formatWindowDate(windowBounds.from ?? '')} –{' '}
        {formatWindowDate(windowBounds.to ?? '')}. Switch to the latest synced window or run a sync
        from Traffic.
      </Alert>
    </div>
  );
}
