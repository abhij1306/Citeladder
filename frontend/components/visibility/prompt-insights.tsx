'use client';

import { useMutation, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { queryKeys } from '@/lib/api/query-keys';
import { visibilityApi } from '@/lib/api/visibility';
import type { ObservedCompetitor, PromptMetricItem } from '@/lib/api/types';

export function PromptInsights({
  projectId,
  promptQuery,
  suggestionsQuery,
}: Readonly<{
  projectId: string;
  promptQuery: UseQueryResult<PromptMetricItem[], unknown>;
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
      void queryClient.invalidateQueries({ queryKey: queryKeys.visibility.all });
    },
  });

  return (
    <div className="grid gap-3 lg:grid-cols-2">
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
                    {item.immediate_delta === null
                      ? ''
                      : ` · ${item.immediate_delta >= 0 ? '+' : ''}${item.immediate_delta.toFixed(1)}`}
                    {item.decline_confirmed ? ' · confirmed decline' : ''}
                  </span>
                </li>
              ))}
            </ul>
          ) : !promptQuery.isLoading ? (
            <p className="text-muted text-sm">Prompt movement appears after a completed audit.</p>
          ) : null}
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Competitor suggestions</CardTitle>
        </CardHeader>
        <CardContent className="grid gap-3">
          <p className="text-muted text-xs">
            Observed repeatedly in third-party citations. Verify relevance before adding.
          </p>
          {suggestionsQuery.isError ? (
            <Alert tone="danger">Could not load competitor suggestions.</Alert>
          ) : null}
          {suggestionsQuery.data?.length ? (
            <ul className="border-border-subtle divide-border-subtle divide-y rounded-lg border">
              {suggestionsQuery.data.map((candidate) => (
                <li
                  key={candidate.id}
                  className="flex flex-wrap items-center justify-between gap-2 px-3 py-2 text-sm"
                >
                  <div>
                    <p className="text-foreground font-medium">{candidate.name}</p>
                    <p className="text-secondary text-xs">
                      {candidate.domain} · {candidate.prompt_count} prompts /{' '}
                      {candidate.engine_count} engines
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
          ) : !suggestionsQuery.isLoading ? (
            <p className="text-muted text-sm">No repeated citation candidates yet.</p>
          ) : null}
          {acceptMutation.isError ? (
            <Alert tone="danger">Could not add that competitor. Try again.</Alert>
          ) : null}
        </CardContent>
      </Card>
    </div>
  );
}
