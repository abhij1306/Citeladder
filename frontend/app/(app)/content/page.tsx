'use client';

import { Suspense } from 'react';
import { useSearchParams } from 'next/navigation';

import { ContentScreen } from '@/components/content/content-screen';
import { TooltipProvider } from '@/components/ui/tooltip';
import { DEMAND_SIGNAL_PARAM } from '@/lib/demand/content-brief';
import type { SiteHealthReferenceInput } from '@/lib/api/content';

function siteHealthReference(
  searchParams: ReturnType<typeof useSearchParams>,
): SiteHealthReferenceInput | undefined {
  const projectId = searchParams.get('project_id');
  const crawlId = searchParams.get('site_health_crawl_id');
  const siteUrlId = searchParams.get('site_url_id');
  const sourceAnalysisId = searchParams.get('source_analysis_id');
  const dimension = searchParams.get('dimension');
  const checkpointIds = searchParams.getAll('checkpoint_ids');
  if (
    !projectId ||
    !crawlId ||
    !siteUrlId ||
    !sourceAnalysisId ||
    !dimension ||
    checkpointIds.length === 0
  ) {
    return undefined;
  }
  return {
    project_id: projectId,
    crawl_id: crawlId,
    site_url_id: siteUrlId,
    source_analysis_id: sourceAnalysisId,
    dimension,
    checkpoint_ids: checkpointIds,
  };
}

function ContentSurface() {
  const searchParams = useSearchParams();
  return (
    <ContentScreen
      opportunityId={searchParams.get('opportunity_id')}
      demandSignalId={searchParams.get(DEMAND_SIGNAL_PARAM)}
      siteHealthReference={siteHealthReference(searchParams)}
    />
  );
}

export default function ContentPage() {
  return (
    // The skill picker explains each format through tooltips.
    <TooltipProvider>
      <Suspense fallback={null}>
        <ContentSurface />
      </Suspense>
    </TooltipProvider>
  );
}
