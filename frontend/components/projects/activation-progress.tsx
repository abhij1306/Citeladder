'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';

import {
  ActivityProgress,
  type ActivityStep,
  type ActivityStepState,
} from '@/components/ui/activity-progress';
import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { opportunitiesMutations, opportunitiesQueries } from '@/lib/api/opportunities';
import { queryKeys } from '@/lib/api/query-keys';
import { siteHealthQueries } from '@/lib/api/site-health';

const CRAWL_TERMINAL = new Set(['completed', 'partially_completed', 'failed', 'cancelled']);
const CRAWL_UNSUCCESSFUL = new Set(['failed', 'cancelled']);

type ActivationFacts = {
  pageLimit: number | null;
  crawl?: {
    status: string;
    discovery_status: string;
    visible_url_count: number;
    analyzed_count: number;
  };
  recommendationState: 'waiting_for_evidence' | 'queued' | 'refreshing' | 'ready' | 'delayed';
};

export function recommendationPollingInterval(
  crawlUnsuccessful: boolean,
  state: ActivationFacts['recommendationState'] | undefined,
): number | false {
  if (crawlUnsuccessful || state === 'ready' || state === 'delayed') return false;
  return 1500;
}

function pageReviewLabel(pageLimit: number | null): string {
  if (pageLimit) return `Reviewing up to ${pageLimit} useful pages`;
  return 'Reviewing useful pages';
}

function pageStepState(
  crawlUnsuccessful: boolean,
  discoveryComplete: boolean,
  crawlTerminal: boolean,
): ActivityStepState {
  if (crawlUnsuccessful && !discoveryComplete) return 'attention';
  if (discoveryComplete || crawlTerminal) return 'complete';
  return 'active';
}

function analyzedPageDetail(crawl: ActivationFacts['crawl'], crawlUnsuccessful: boolean) {
  if (crawlUnsuccessful) return 'The website review needs attention.';
  if (!crawl || crawl.analyzed_count === 0) return undefined;
  const noun = crawl.analyzed_count === 1 ? 'page' : 'pages';
  return `${crawl.analyzed_count} ${noun} checked`;
}

function clarityStepState(
  crawlUnsuccessful: boolean,
  crawlTerminal: boolean,
  discoveryComplete: boolean,
): ActivityStepState {
  if (crawlUnsuccessful) return 'attention';
  if (crawlTerminal) return 'complete';
  if (discoveryComplete) return 'active';
  return 'pending';
}

function recommendationStepState(
  ready: boolean,
  delayed: boolean,
  crawlTerminal: boolean,
  crawlUnsuccessful: boolean,
): ActivityStepState {
  if (ready) return 'complete';
  if (delayed) return 'attention';
  if (crawlTerminal && !crawlUnsuccessful) return 'active';
  return 'pending';
}

export function activationSteps({
  pageLimit,
  crawl,
  recommendationState,
}: ActivationFacts): ActivityStep[] {
  const crawlTerminal = Boolean(crawl && CRAWL_TERMINAL.has(crawl.status));
  const crawlUnsuccessful = Boolean(crawl && CRAWL_UNSUCCESSFUL.has(crawl.status));
  const discoveryComplete = Boolean(
    crawl && ['completed', 'sample_completed'].includes(crawl.discovery_status),
  );
  const ready = recommendationState === 'ready';
  const delayed = recommendationState === 'delayed';

  return [
    { id: 'project', label: 'Project created', state: 'complete' },
    {
      id: 'pages',
      label: pageReviewLabel(pageLimit),
      detail: crawl ? `${crawl.visible_url_count} useful pages found` : undefined,
      state: pageStepState(crawlUnsuccessful, discoveryComplete, crawlTerminal),
    },
    {
      id: 'clarity',
      label: 'Checking how clearly pages explain the business',
      detail: analyzedPageDetail(crawl, crawlUnsuccessful),
      state: clarityStepState(crawlUnsuccessful, crawlTerminal, discoveryComplete),
    },
    {
      id: 'recommendations',
      label: 'Prioritizing recommendations',
      state: recommendationStepState(ready, delayed, crawlTerminal, crawlUnsuccessful),
      detail: delayed ? 'This is taking longer than expected.' : undefined,
    },
    { id: 'ready', label: 'Ready', state: ready ? 'complete' : 'pending' },
  ];
}

export function ActivationProgress({
  projectId,
  crawlId,
  pageLimit,
}: Readonly<{ projectId: string; crawlId: string; pageLimit: number | null }>) {
  const queryClient = useQueryClient();
  const site = useQuery({
    ...siteHealthQueries.dashboard(projectId, crawlId),
    refetchInterval: (query) => {
      const status = query.state.data?.crawl?.status;
      return status && !CRAWL_TERMINAL.has(status) ? 1500 : false;
    },
  });
  const crawl = site.data?.crawl ?? undefined;
  const crawlUnsuccessful = Boolean(crawl && CRAWL_UNSUCCESSFUL.has(crawl.status));
  const recommendations = useQuery({
    ...opportunitiesQueries.summary(projectId),
    refetchInterval: (query) =>
      recommendationPollingInterval(crawlUnsuccessful, query.state.data?.activation_state),
  });
  const retry = useMutation({
    ...opportunitiesMutations.recompute(),
    onSuccess: () =>
      queryClient.invalidateQueries({ queryKey: queryKeys.opportunities.summary(projectId) }),
  });

  const recommendationState = recommendations.data?.activation_state ?? 'waiting_for_evidence';
  const ready = recommendationState === 'ready';
  const delayed = recommendationState === 'delayed';
  const steps = activationSteps({ pageLimit, crawl, recommendationState });

  return (
    <Card aria-label="Project setup progress">
      <CardContent className="grid gap-4">
        <div className="grid gap-1">
          <h2 className="text-foreground text-heading-sm">
            {ready ? 'Your first review is ready' : 'Preparing your first review'}
          </h2>
          <p className="text-secondary text-sm">
            You can keep using CiteLadder while this finishes automatically.
          </p>
        </div>
        <ActivityProgress label="First review progress" steps={steps} />
        {site.isError || recommendations.isError ? (
          <Alert tone="warning">Progress is temporarily unavailable. We will keep trying.</Alert>
        ) : null}
        {crawlUnsuccessful ? (
          <Alert tone="warning">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <span>We could not finish the website review automatically.</span>
              <Button asChild size="sm" variant="secondary">
                <Link href="/site-health">Review website status</Link>
              </Button>
            </div>
          </Alert>
        ) : null}
        {delayed ? (
          <div>
            <Button
              size="sm"
              variant="secondary"
              disabled={retry.isPending}
              onClick={() => retry.mutate({ projectId })}
            >
              {retry.isPending ? 'Trying again…' : 'Try recommendations again'}
            </Button>
          </div>
        ) : null}
      </CardContent>
    </Card>
  );
}
