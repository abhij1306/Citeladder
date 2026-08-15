import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { OpportunityStatusBadge } from '@/components/opportunities/opportunity-status-badge';
import { useUpdateOpportunityStatus } from '@/components/opportunities/use-opportunity-status';
import { Button } from '@/components/ui/button';
import { MutationNotice } from '@/components/ui/mutation-notice';
import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import {
  opportunitiesMutations,
  opportunitiesQueries,
  type ExpectedCheck,
} from '@/lib/api/opportunities';
import type { OpportunityDetail, OpportunityStatus } from '@/lib/api/types';

export function OpportunityStatusFooter({
  detail,
  projectId,
}: Readonly<{ detail: OpportunityDetail; projectId: string }>) {
  const updateStatus = useUpdateOpportunityStatus(projectId, detail.id);
  const queryClient = useQueryClient();
  const declaration = useMutation({
    ...opportunitiesMutations.createImplementationEvent(),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: opportunitiesQueries.implementationEvents(projectId, detail.id).queryKey,
      }),
  });
  const declarations = useQuery(
    opportunitiesQueries.implementationEvents(projectId, detail.id),
  );
  const [idempotencyKey] = useState(
    () => globalThis.crypto?.randomUUID?.() ?? `${detail.id}-${Date.now()}`,
  );
  const change = (status: OpportunityStatus) => {
    updateStatus.mutate({ opportunityId: detail.id, status });
  };
  const targetId =
    typeof detail.evidence.site_url_id === 'string' ? detail.evidence.site_url_id : undefined;
  const siteRuleId =
    typeof detail.evidence.issue_rule_id === 'string'
      ? detail.evidence.issue_rule_id
      : detail.rule_id;
  const expectedCheck: ExpectedCheck =
    detail.opportunity_type === 'site'
      ? {
          kind: 'site_rule',
          ...(targetId ? { target_site_url_id: targetId } : {}),
          rule_id: siteRuleId,
          expected_outcome: 'pass',
        }
      : {
          kind: detail.opportunity_type === 'traffic' ? 'traffic_metric' : 'visibility_metric',
          metric: detail.opportunity_type === 'traffic' ? 'clicks' : 'visibility_score',
          direction: 'increase',
          expected_value: 1,
        };
  const persistedDeclaration = declarations.data?.items.find(
    (item) => item.opportunity_id === detail.id,
  );
  const implementation = declaration.data ?? persistedDeclaration;

  return (
    <footer className="border-border-subtle grid gap-2 border-t px-4 py-3">
      {updateStatus.isError ? (
        // A4: a 4xx (e.g. the opportunity was superseded by a newer recompute)
        // renders the backend message verbatim; transient failures offer retry.
        <MutationNotice
          notice={mutationNoticeForError(updateStatus.error, { action: 'update the status' })}
          onRetry={() => {
            // Re-attempt the exact failed transition, never a guessed one.
            if (updateStatus.variables) updateStatus.mutate(updateStatus.variables);
          }}
        />
      ) : null}
      {declaration.isError ? (
        <MutationNotice
          notice={mutationNoticeForError(declaration.error, {
            action: 'declare this implementation',
          })}
          onRetry={() => {
            if (declaration.variables) declaration.mutate(declaration.variables);
          }}
        />
      ) : null}
      {implementation ? (
        <p
          className={`${
            implementation.state === 'verified'
              ? 'text-success-text'
              : implementation.state === 'contradicted'
                ? 'text-danger-text'
                : 'text-muted'
          } text-xs`}
        >
          {implementation.state === 'declared'
            ? 'Declared for verification.'
            : `Verification: ${implementation.state}.`}
          {implementation.limitations.length > 0
            ? ` ${implementation.limitations.join(' ')}`
            : null}
        </p>
      ) : null}
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-2xs text-muted">Status</span>
          <OpportunityStatusBadge status={detail.status} />
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="secondary"
            size="sm"
            disabled={declaration.isPending || Boolean(implementation)}
            onClick={() =>
              declaration.mutate({
                projectId,
                idempotencyKey,
                input: {
                  opportunity_id: detail.id,
                  target_site_url_ids: targetId ? [targetId] : [],
                  declared_implemented_at: new Date().toISOString(),
                  expected_checks: [expectedCheck],
                },
              })
            }
          >
            I implemented this
          </Button>
          {detail.status === 'open' ? (
            <>
              <Button
                variant="secondary"
                size="sm"
                disabled={updateStatus.isPending}
                onClick={() => change('dismissed')}
              >
                Dismiss
              </Button>
              <Button
                size="sm"
                disabled={updateStatus.isPending}
                onClick={() => change('in_progress')}
              >
                Mark in progress
              </Button>
            </>
          ) : null}
          {detail.status === 'in_progress' ? (
            <>
              <Button
                variant="secondary"
                size="sm"
                disabled={updateStatus.isPending}
                onClick={() => change('dismissed')}
              >
                Dismiss
              </Button>
              <Button
                size="sm"
                disabled={updateStatus.isPending}
                onClick={() => change('resolved')}
              >
                Mark resolved
              </Button>
            </>
          ) : null}
          {detail.status === 'dismissed' || detail.status === 'resolved' ? (
            <Button
              variant="secondary"
              size="sm"
              disabled={updateStatus.isPending}
              onClick={() => change('open')}
            >
              Reopen
            </Button>
          ) : null}
        </div>
      </div>
    </footer>
  );
}
