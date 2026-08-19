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
  const declaration = useImplementationDeclaration(projectId, detail.id);
  const declarations = useQuery(opportunitiesQueries.implementationEvents(projectId, detail.id));
  const [idempotencyKey] = useState(
    () => globalThis.crypto?.randomUUID?.() ?? `${detail.id}-${Date.now()}`,
  );
  const implementation =
    declaration.data ?? declarations.data?.items.find((item) => item.opportunity_id === detail.id);
  const declare = () => declaration.mutate(declarationPayload(detail, projectId, idempotencyKey));

  return (
    <footer className="border-border-subtle grid gap-2 border-t px-4 py-3">
      <MutationErrors updateStatus={updateStatus} declaration={declaration} />
      <ImplementationState implementation={implementation} />
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <span className="text-2xs text-muted">Status</span>
          <OpportunityStatusBadge status={detail.status} />
        </div>
        <StatusActions
          detail={detail}
          implementation={implementation}
          declarationPending={declaration.isPending}
          updatePending={updateStatus.isPending}
          onDeclare={declare}
          onChange={(status) => updateStatus.mutate({ opportunityId: detail.id, status })}
        />
      </div>
    </footer>
  );
}

function useImplementationDeclaration(projectId: string, opportunityId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    ...opportunitiesMutations.createImplementationEvent(),
    onSuccess: () =>
      queryClient.invalidateQueries({
        queryKey: opportunitiesQueries.implementationEvents(projectId, opportunityId).queryKey,
      }),
  });
}

function declarationPayload(detail: OpportunityDetail, projectId: string, idempotencyKey: string) {
  const targetId =
    typeof detail.evidence.site_url_id === 'string' ? detail.evidence.site_url_id : undefined;
  return {
    projectId,
    idempotencyKey,
    input: {
      opportunity_id: detail.id,
      target_site_url_ids: targetId ? [targetId] : [],
      declared_implemented_at: new Date().toISOString(),
      expected_checks: [expectedCheck(detail, targetId)],
    },
  };
}

function expectedCheck(detail: OpportunityDetail, targetId: string | undefined): ExpectedCheck {
  if (detail.opportunity_type === 'site')
    return {
      kind: 'site_rule',
      ...(targetId ? { target_site_url_id: targetId } : {}),
      rule_id:
        typeof detail.evidence.issue_rule_id === 'string'
          ? detail.evidence.issue_rule_id
          : detail.rule_id,
      expected_outcome: 'pass',
    };
  const traffic = detail.opportunity_type === 'traffic';
  return {
    kind: traffic ? 'traffic_metric' : 'visibility_metric',
    metric: traffic ? 'clicks' : 'visibility_score',
    direction: 'increase',
    expected_value: 1,
  };
}

function MutationErrors({
  updateStatus,
  declaration,
}: Readonly<{
  updateStatus: ReturnType<typeof useUpdateOpportunityStatus>;
  declaration: ReturnType<typeof useImplementationDeclaration>;
}>) {
  return (
    <>
      {updateStatus.isError ? (
        <MutationNotice
          notice={mutationNoticeForError(updateStatus.error, { action: 'update the status' })}
          onRetry={() => updateStatus.variables && updateStatus.mutate(updateStatus.variables)}
        />
      ) : null}
      {declaration.isError ? (
        <MutationNotice
          notice={mutationNoticeForError(declaration.error, {
            action: 'declare this implementation',
          })}
          onRetry={() => declaration.variables && declaration.mutate(declaration.variables)}
        />
      ) : null}
    </>
  );
}

function ImplementationState({
  implementation,
}: Readonly<{ implementation: { state: string; limitations: string[] } | undefined }>) {
  if (!implementation) return null;
  const color =
    implementation.state === 'verified'
      ? 'text-success-text'
      : implementation.state === 'contradicted'
        ? 'text-danger-text'
        : 'text-muted';
  return (
    <p className={`${color} text-xs`}>
      {implementation.state === 'declared'
        ? 'Declared for verification.'
        : `Verification: ${implementation.state}.`}
      {implementation.limitations.length ? ` ${implementation.limitations.join(' ')}` : null}
    </p>
  );
}

function StatusActions({
  detail,
  implementation,
  declarationPending,
  updatePending,
  onDeclare,
  onChange,
}: Readonly<{
  detail: OpportunityDetail;
  implementation: unknown;
  declarationPending: boolean;
  updatePending: boolean;
  onDeclare: () => void;
  onChange: (status: OpportunityStatus) => void;
}>) {
  const controls = statusControls(detail.status, onChange, updatePending);
  return (
    <div className="flex items-center gap-2">
      <Button
        variant="secondary"
        size="sm"
        disabled={declarationPending || Boolean(implementation)}
        onClick={onDeclare}
      >
        I implemented this
      </Button>
      {controls}
    </div>
  );
}

function statusControls(
  status: OpportunityStatus,
  onChange: (status: OpportunityStatus) => void,
  pending: boolean,
) {
  if (status === 'open')
    return (
      <>
        <Button
          variant="secondary"
          size="sm"
          disabled={pending}
          onClick={() => onChange('dismissed')}
        >
          Dismiss
        </Button>
        <Button size="sm" disabled={pending} onClick={() => onChange('in_progress')}>
          Mark in progress
        </Button>
      </>
    );
  if (status === 'in_progress')
    return (
      <>
        <Button
          variant="secondary"
          size="sm"
          disabled={pending}
          onClick={() => onChange('dismissed')}
        >
          Dismiss
        </Button>
        <Button size="sm" disabled={pending} onClick={() => onChange('resolved')}>
          Mark resolved
        </Button>
      </>
    );
  return (
    <Button variant="secondary" size="sm" disabled={pending} onClick={() => onChange('open')}>
      Reopen
    </Button>
  );
}
