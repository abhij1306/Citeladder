'use client';

import { useMutation, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { queryKeys } from '@/lib/api/query-keys';
import { visibilityApi } from '@/lib/api/visibility';
import type { ObservedCompetitor, PromptMetricItem } from '@/lib/api/types';

function movementDelta(delta: number | null): string {
  if (delta === null) return '';
  const sign = delta >= 0 ? '+' : '';
  return ` · ${sign}${delta.toFixed(1)}`;
}

export function PromptMovement({
  promptQuery,
}: Readonly<{
  promptQuery: UseQueryResult<PromptMetricItem[], unknown>;
}>) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Prompt movement</CardTitle>
      </CardHeader>
      <CardContent>
        {promptQuery.isError ? <Alert tone="danger">Could not load prompt scores.</Alert> : null}
        {promptQuery.data?.length ? (
          <ul className="border-border-subtle divide-border-subtle divide-y rounded-lg border">
            {promptQuery.data.slice(0, 5).map((item) => (
              <li key={item.id} className="grid gap-1 px-3 py-2 text-sm">
                <span className="text-foreground line-clamp-2">{item.prompt_text}</span>
                <span className="text-secondary">
                  {item.composite_score.toFixed(1)} score
                  {movementDelta(item.immediate_delta)}
                  {item.decline_confirmed ? ' · confirmed decline' : ''}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
        {!promptQuery.data?.length && !promptQuery.isLoading && !promptQuery.isError ? (
          <p className="text-muted text-sm">Prompt movement appears after a completed audit.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

export function CompetitorSuggestions({
  projectId,
  suggestionsQuery,
}: Readonly<{
  projectId: string;
  suggestionsQuery: UseQueryResult<ObservedCompetitor[], unknown>;
}>) {
  const queryClient = useQueryClient();
  const acceptMutation = useMutation({
    mutationFn: (candidateId: string) =>
      visibilityApi.acceptCompetitorSuggestion(projectId, candidateId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.visibility.competitorSuggestions(projectId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.list() });
      void queryClient.invalidateQueries({
        queryKey: queryKeys.projects.commandCenter(projectId),
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.visibility.all });
    },
  });

  return (
    <div className="flex flex-col gap-3 pt-2">
      <div>
        <h3 className="text-foreground text-sm font-semibold">Competitor suggestions</h3>
        <p className="text-muted mt-0.5 text-xs">
          Observed repeatedly in third-party citations. Verify relevance before adding.
        </p>
      </div>
      {suggestionsQuery.isError ? (
        <Alert tone="danger">Could not load competitor suggestions.</Alert>
      ) : null}
      {suggestionsQuery.data?.length ? (
        <ul className="border-border-subtle bg-panel divide-border-subtle divide-y rounded-md border shadow-sm">
          {suggestionsQuery.data.map((candidate) => (
            <li
              key={candidate.id}
              className="flex flex-wrap items-center justify-between gap-2 px-3.5 py-2.5 text-sm"
            >
              <div>
                <p className="text-foreground text-xs font-medium">{candidate.name}</p>
                <p className="text-muted text-2xs mt-0.5">
                  {candidate.domain} · {candidate.prompt_count} prompts / {candidate.engine_count}{' '}
                  engines
                </p>
              </div>
              <Button
                size="sm"
                variant="secondary"
                onClick={() => acceptMutation.mutate(candidate.id)}
                disabled={acceptMutation.isPending}
              >
                Add competitor
              </Button>
            </li>
          ))}
        </ul>
      ) : null}
      {!suggestionsQuery.data?.length && !suggestionsQuery.isLoading ? (
        <p className="text-muted text-xs">No repeated citation candidates yet.</p>
      ) : null}
      {acceptMutation.isError ? (
        <Alert tone="danger">Could not add that competitor. Try again.</Alert>
      ) : null}
    </div>
  );
}
