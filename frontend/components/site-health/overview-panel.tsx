'use client';

import { useQuery } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { OverviewDetails, OverviewDetailsSkeleton } from './overview-details';
import { OverviewMetricCards } from './overview-metrics';
import { Alert } from '@/components/ui/alert';
import { siteHealthQueries } from '@/lib/api/site-health';
import type { SiteCrawl, SiteHealthDashboard } from '@/lib/api/types';
import { shouldPollCrawl } from '@/lib/site-health/status';

/**
 * Overview shares the screen's single polling dashboard while a crawl runs.
 * Its immutable snapshot query is enabled only after the crawl terminalizes.
 */
export function OverviewPanel({
  projectId,
  crawlId,
  crawl,
  dashboard,
}: Readonly<{
  projectId: string;
  crawlId: string;
  crawl: SiteCrawl | null;
  dashboard: SiteHealthDashboard | undefined;
}>) {
  const terminal = crawl ? !shouldPollCrawl(crawl) : false;
  const overview = useQuery({
    ...siteHealthQueries.overview(projectId, crawlId),
    enabled: terminal,
  });
  const data = overview.data;
  let overviewBody: ReactNode = null;
  if (overview.isError) {
    overviewBody = <Alert tone="danger">Could not load the persisted Site Health Overview.</Alert>;
  } else if (data) {
    overviewBody = <OverviewDetails data={data} />;
  } else if (terminal && overview.isLoading) {
    overviewBody = <OverviewDetailsSkeleton />;
  }

  return (
    <div className="grid min-w-0 gap-4" data-testid="site-health-overview">
      {data ? (
        <Alert tone={searchEligibilityTone(data.search_eligibility)}>
          Search eligibility: {data.search_eligibility}. {data.audited_page_count} audited of{' '}
          {data.selected_page_count} selected pages.
        </Alert>
      ) : null}
      <OverviewMetricCards overview={data} dashboard={dashboard} crawl={crawl} />
      {overviewBody}
    </div>
  );
}

function searchEligibilityTone(state: 'eligible' | 'blocked' | 'unknown' | 'excluded') {
  if (state === 'eligible') return 'success' as const;
  if (state === 'blocked') return 'danger' as const;
  return 'warning' as const;
}
