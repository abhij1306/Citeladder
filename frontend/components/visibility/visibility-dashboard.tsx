'use client';

import type { ReactNode } from 'react';
import { useQuery } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { ProjectsStatCard } from '@/components/projects/projects-stat-card';
import { ActiveRunBanner } from '@/components/visibility/active-run-banner';
import { DashboardSkeleton } from '@/components/visibility/dashboard-skeleton';
import { VisibilityEmptyState } from '@/components/visibility/empty-state';
import { FanoutEvidence } from '@/components/visibility/fanout-evidence';
import { MentionsCitations } from '@/components/visibility/mentions-citations';
import { VisibilityOverview } from '@/components/visibility/visibility-overview';
import { VisibilityTabs } from '@/components/visibility/visibility-tabs';
import { VisibilityToolbar } from '@/components/visibility/visibility-toolbar';
import { VisibilityTrends } from '@/components/visibility/visibility-trends';
import { useProjectContext } from '@/lib/project/project-context';
import { queryKeys } from '@/lib/api/query-keys';
import { visibilityApi } from '@/lib/api/visibility';
import {
  EVIDENCE_LIMIT,
  useVisibilityFilters,
  useVisibilityQueries,
} from '@/lib/visibility/use-visibility-dashboard';

/**
 * Visibility workspace container (F9, four-tab IA).
 *
 * Resolves the active project (F5 context) and orchestrates one workspace
 * shell: a shared filter bar (`visibility-toolbar.tsx`) above an accessible
 * tablist (`visibility-tabs.tsx`) with exactly four panels — Overview, Trends,
 * Mentions & Citations, and Query Fanout. Tab/filter state lives in
 * `useVisibilityFilters` (URL-synced `?tab=`); the per-tab queries live in
 * `useVisibilityQueries` (only the relevant query runs per tab). When an
 * evidence request has both `audit_id` and a date bound, the backend
 * intersects them.
 */
export function VisibilityDashboard() {
  const { activeProject, isLoading: isProjectLoading } = useProjectContext();
  const projectId = activeProject?.id ?? null;

  const filters = useVisibilityFilters();
  const {
    auditsQuery,
    runOptions,
    activeRun,
    activeRunId,
    hasRuns,
    visibilityQuery,
    trendQuery,
    brandHistory,
    evidenceQuery,
    promptOptions,
  } = useVisibilityQueries(projectId, filters);

  const promptQuery = useQuery({
    queryKey: queryKeys.visibility.prompts(projectId ?? '', activeRunId ?? undefined),
    queryFn: ({ signal }) =>
      visibilityApi.getPromptMetrics(projectId ?? '', activeRunId ?? undefined, { signal }),
    enabled: filters.activeTab === 'overview' && Boolean(projectId) && Boolean(activeRunId),
  });
  const suggestionsQuery = useQuery({
    queryKey: queryKeys.visibility.competitorSuggestions(projectId ?? ''),
    queryFn: ({ signal }) => visibilityApi.listCompetitorSuggestions(projectId ?? '', { signal }),
    enabled: filters.activeTab === 'overview' && Boolean(projectId),
  });

  const isBootstrapping = isProjectLoading || (Boolean(projectId) && auditsQuery.isLoading);

  if (isBootstrapping) {
    return <DashboardSkeleton />;
  }

  if (!projectId) {
    return <Alert tone="info">Select or create a project to see its AI-visibility results.</Alert>;
  }

  if (auditsQuery.isError) {
    return (
      <Alert tone="danger">
        Could not load this project&apos;s runs. Check your connection and try again.
      </Alert>
    );
  }

  // A project with no dashboard-ready runs has nothing to project — but a run
  // that is still in progress must be visible here (the audits query keeps
  // polling), not silently absent until it completes.
  if (!hasRuns) {
    return (
      <div className="grid gap-6">
        {activeRun ? <ActiveRunBanner run={activeRun} /> : null}
        <VisibilityEmptyState hasActiveRun={Boolean(activeRun)} />
      </div>
    );
  }

  let panel: ReactNode;
  if (filters.activeTab === 'trends') {
    panel = (
      <VisibilityTrends query={trendQuery} hasRuns={hasRuns} isFiltered={filters.isTrendFiltered} />
    );
  } else if (filters.activeTab === 'mentions-citations') {
    panel = (
      <MentionsCitations
        query={evidenceQuery}
        isFiltered={filters.isFiltered}
        onClearFilters={filters.clearEvidenceFilters}
        limit={EVIDENCE_LIMIT}
      />
    );
  } else if (filters.activeTab === 'query-fanout') {
    panel = (
      <FanoutEvidence
        query={evidenceQuery}
        isFiltered={filters.isFiltered}
        onClearFilters={filters.clearEvidenceFilters}
        limit={EVIDENCE_LIMIT}
      />
    );
  } else {
    panel = (
      <VisibilityOverview
        query={visibilityQuery}
        engineFilter={filters.engine}
        brandName={activeProject?.brand_name || activeProject?.name || 'Your brand'}
        brandHistory={brandHistory}
        projectId={projectId}
        promptQuery={promptQuery}
        suggestionsQuery={suggestionsQuery}
      />
    );
  }

  return (
    <div className="grid gap-6">
      {activeRun ? <ActiveRunBanner run={activeRun} /> : null}
      {/* Renders only for multi-project workspaces — see the component. */}
      <ProjectsStatCard />
      <VisibilityToolbar
        activeTab={filters.activeTab}
        runs={runOptions}
        selectedRunId={filters.selectedRunId}
        onSelectRun={filters.setSelectedRunId}
        engine={filters.engine}
        onChangeEngine={filters.setEngine}
        promptOptions={promptOptions}
        promptId={filters.promptId}
        onChangePrompt={filters.setPromptId}
        range={filters.range}
        onChangeRange={filters.setRange}
        granularity={filters.granularity}
        onChangeGranularity={filters.setGranularity}
        cohort={filters.cohort}
        onChangeCohort={filters.setCohort}
      />
      <VisibilityTabs activeTab={filters.activeTab} onSelectTab={filters.selectTab} panel={panel} />
    </div>
  );
}
