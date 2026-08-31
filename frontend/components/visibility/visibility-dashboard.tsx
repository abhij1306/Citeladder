'use client';

import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { ActiveRunBanner } from '@/components/visibility/active-run-banner';
import { DashboardSkeleton } from '@/components/visibility/dashboard-skeleton';
import { VisibilityEmptyState } from '@/components/visibility/empty-state';
import { FanoutEvidence } from '@/components/visibility/fanout-evidence';
import { MentionsCitations } from '@/components/visibility/mentions-citations';
import { VisibilityToolbar } from '@/components/visibility/visibility-toolbar';
import { VisibilityTrends } from '@/components/visibility/visibility-trends';
import { TabPanel, Tabs } from '@/components/ui/tabs';
import { queryKeys } from '@/lib/api/query-keys';
import { visibilityApi } from '@/lib/api/visibility';
import { useProjectContext } from '@/lib/project/project-context';
import { VISIBILITY_TABS, type VisibilityTab } from '@/lib/visibility/dashboard';
import {
  EVIDENCE_LIMIT,
  useVisibilityFilters,
  useVisibilityQueries,
} from '@/lib/visibility/use-visibility-dashboard';

export function VisibilityDashboard() {
  const { activeProject, isLoading: projectLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;
  const filters = useVisibilityFilters();
  const queries = useVisibilityQueries(projectId, filters);
  const promptQuery = usePromptQuery(projectId, queries.activeRunId, filters.activeTab);
  const state = dashboardState(
    projectId,
    projectLoading,
    queries.auditsQuery.isLoading,
    queries.auditsQuery.isError,
    queries.hasRuns,
  );
  if (state) return <DashboardState state={state} activeRun={queries.activeRun} />;
  return <VisibilityWorkspace filters={filters} queries={queries} promptQuery={promptQuery} />;
}

function usePromptQuery(projectId: string | null, activeRunId: string | null, activeTab: string) {
  return useQuery({
    queryKey: queryKeys.visibility.prompts(projectId ?? '', activeRunId ?? undefined),
    queryFn: ({ signal }) =>
      visibilityApi.getPromptMetrics(projectId ?? '', activeRunId ?? undefined, { signal }),
    enabled: activeTab === 'trends' && Boolean(projectId) && Boolean(activeRunId),
  });
}

function dashboardState(
  projectId: string | null,
  projectLoading: boolean,
  auditsLoading: boolean,
  auditsError: boolean,
  hasRuns: boolean,
) {
  if (projectLoading || (Boolean(projectId) && auditsLoading)) return 'loading';
  if (!projectId) return 'missing-project';
  if (auditsError) return 'error';
  if (!hasRuns) return 'empty';
  return null;
}

function DashboardState({
  state,
  activeRun,
}: Readonly<{ state: string; activeRun: ReturnType<typeof useVisibilityQueries>['activeRun'] }>) {
  if (state === 'loading') return <DashboardSkeleton />;
  if (state === 'missing-project')
    return <Alert tone="info">Select or create a project to see its AI-visibility results.</Alert>;
  if (state === 'error')
    return (
      <Alert tone="danger">
        Could not load this project&apos;s runs. Check your connection and try again.
      </Alert>
    );
  return (
    <div className="grid gap-[var(--workspace-gap)]">
      {activeRun ? <ActiveRunBanner run={activeRun} /> : null}
      <VisibilityEmptyState hasActiveRun={Boolean(activeRun)} />
    </div>
  );
}

function VisibilityWorkspace({
  filters,
  queries,
  promptQuery,
}: Readonly<{
  filters: ReturnType<typeof useVisibilityFilters>;
  queries: ReturnType<typeof useVisibilityQueries>;
  promptQuery: ReturnType<typeof usePromptQuery>;
}>) {
  return (
    <div className="grid gap-[var(--workspace-gap)]">
      {queries.activeRun ? <ActiveRunBanner run={queries.activeRun} /> : null}
      <VisibilityToolbar
        activeTab={filters.activeTab}
        runs={queries.runOptions}
        selectedRunId={filters.selectedRunId}
        onSelectRun={filters.setSelectedRunId}
        engine={filters.engine}
        onChangeEngine={filters.setEngine}
        promptOptions={queries.promptOptions}
        promptId={filters.promptId}
        onChangePrompt={filters.setPromptId}
        range={filters.range}
        onChangeRange={filters.setRange}
        granularity={filters.granularity}
        onChangeGranularity={filters.setGranularity}
        cohort={filters.cohort}
        onChangeCohort={filters.setCohort}
      />
      <Tabs
        value={filters.activeTab}
        onValueChange={filters.selectTab}
        items={VISIBILITY_TABS.map((tab) => ({ value: tab.id, label: tab.label }))}
        ariaLabel="Visibility views"
        rootClassName="grid gap-4"
      >
        <TabPanel value={filters.activeTab} className="focus-ring">
          <DashboardPanel filters={filters} queries={queries} promptQuery={promptQuery} />
        </TabPanel>
      </Tabs>
    </div>
  );
}

function DashboardPanel({
  filters,
  queries,
  promptQuery,
}: Readonly<{
  filters: ReturnType<typeof useVisibilityFilters>;
  queries: ReturnType<typeof useVisibilityQueries>;
  promptQuery: ReturnType<typeof usePromptQuery>;
}>) {
  const panels: Partial<Record<VisibilityTab, ReactNode>> = {
    trends: (
      <VisibilityTrends
        query={queries.trendQuery}
        visibilityQuery={queries.visibilityQuery}
        promptQuery={promptQuery}
        engineFilter={filters.engine}
        hasRuns={queries.hasRuns}
        isFiltered={filters.isTrendFiltered}
      />
    ),
    'mentions-citations': (
      <MentionsCitations
        query={queries.evidenceQuery}
        isFiltered={filters.isFiltered}
        onClearFilters={filters.clearEvidenceFilters}
        limit={EVIDENCE_LIMIT}
      />
    ),
    'query-fanout': (
      <FanoutEvidence
        query={queries.evidenceQuery}
        isFiltered={filters.isFiltered}
        onClearFilters={filters.clearEvidenceFilters}
        limit={EVIDENCE_LIMIT}
      />
    ),
  };
  return panels[filters.activeTab] ?? null;
}
