'use client';

import { useQuery } from '@tanstack/react-query';
import { useMemo, useState } from 'react';

import { AiReferralsContent } from '@/components/ai-referrals/ai-referrals-content';
import { AnalyticsToolbar } from '@/components/ui/analytics-toolbar';
import { aiReferralsApi } from '@/lib/api/ai-referrals';
import { queryKeys } from '@/lib/api/query-keys';
import { retainPreviousDataForScope } from '@/lib/api/query-client';
import {
  GRANULARITY_OPTIONS,
  RANGE_OPTIONS,
  rangeLabel,
  rangeToWindow,
  type AiReferralsGranularity,
  type AiReferralsRange,
} from '@/lib/ai-referrals/options';
import { useProjectContext } from '@/lib/project/project-context';

export function AiReferralsScreen() {
  const { activeProject, isLoading: isProjectLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;
  const [range, setRange] = useState<AiReferralsRange>('latest');
  const [granularity, setGranularity] = useState<AiReferralsGranularity>('week');
  const windowBounds = useMemo(() => rangeToWindow(range), [range]);
  const dashboardQuery = useQuery({
    queryKey: queryKeys.aiReferrals.dashboard(projectId ?? '', { ...windowBounds, granularity }),
    queryFn: ({ signal }) =>
      aiReferralsApi.getDashboard(projectId!, { ...windowBounds, granularity }, { signal }),
    enabled: Boolean(projectId),
    placeholderData: (previousData, previousQuery) =>
      retainPreviousDataForScope(projectId!, previousData, previousQuery),
  });

  return (
    <AiReferralsContent
      projectId={projectId}
      projectLoading={isProjectLoading}
      range={range}
      windowBounds={windowBounds}
      query={dashboardQuery}
      toolbar={
        <AiReferralsToolbar
          range={range}
          onChangeRange={setRange}
          granularity={granularity}
          onChangeGranularity={setGranularity}
          fetching={dashboardQuery.isFetching}
        />
      }
    />
  );
}

function AiReferralsToolbar({
  range,
  onChangeRange,
  granularity,
  onChangeGranularity,
  fetching,
}: Readonly<{
  range: AiReferralsRange;
  onChangeRange: (range: AiReferralsRange) => void;
  granularity: AiReferralsGranularity;
  onChangeGranularity: (granularity: AiReferralsGranularity) => void;
  fetching: boolean;
}>) {
  return (
    <AnalyticsToolbar
      range={range}
      defaultRange="latest"
      rangeLabel={rangeLabel(range)}
      rangeOptions={RANGE_OPTIONS}
      onChangeRange={onChangeRange}
      granularity={granularity}
      granularityOptions={GRANULARITY_OPTIONS}
      onChangeGranularity={onChangeGranularity}
      fetching={fetching}
      testId="ai-referrals-toolbar"
    />
  );
}

export { AiReferralsSkeleton } from './ai-referrals-skeleton';
