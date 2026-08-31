import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import Link from 'next/link';

import { OpportunityStatusBadge } from '@/components/opportunities/opportunity-status-badge';
import { useUpdateOpportunityStatus } from '@/components/opportunities/use-opportunity-status';
import { Button } from '@/components/ui/button';
import { MutationNotice } from '@/components/ui/mutation-notice';
import { mutationNoticeForError } from '@/lib/api/mutation-notice';
import { opportunitiesMutations, opportunitiesQueries } from '@/lib/api/opportunities';
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
    <div className="grid gap-2">
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
    </div>
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
      generation_id: detail.linked_generations.find((item) => item.status === 'succeeded')?.id,
      declared_implemented_at: new Date().toISOString(),
      expected_checks: [],
    },
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
}: Readonly<{
  implementation:
    | {
        state: string;
        limitations: string[];
        verification_events?: Array<{ result: Record<string, unknown> }>;
      }
    | undefined;
}>) {
  if (!implementation) return null;
  const color =
    implementation.state === 'verified'
      ? 'text-success-text'
      : implementation.state === 'contradicted'
        ? 'text-danger-text'
        : 'text-muted';
  const latest = implementation.verification_events?.at(-1);
  const result = latest?.result;
  const legs = result && typeof result === 'object' && 'legs' in result ? result.legs : null;
  return (
    <div className={`${color} grid gap-1 text-xs`}>
      <p>
        {implementation.state === 'declared'
          ? 'Declared for verification.'
          : `Verification: ${implementation.state}.`}
        {implementation.limitations.length ? ` ${implementation.limitations.join(' ')}` : null}
      </p>
      {legs && typeof legs === 'object'
        ? Object.entries(legs).map(([name, leg]) => (
            <p key={name}>
              {name.replaceAll('_', ' ')}: {legState(leg)}
            </p>
          ))
        : null}
      <GapChanges result={result} />
      <Link className="focus-ring w-fit underline underline-offset-2" href="/runs">
        Run a comparable audit
      </Link>
    </div>
  );
}

function GapChanges({ result }: Readonly<{ result: Record<string, unknown> | undefined }>) {
  const changes = result?.gap_changes;
  if (!changes || typeof changes !== 'object' || !('state' in changes)) return null;
  if (changes.state !== 'available') return <p>Gap comparison: not run</p>;
  const count = (key: string) => {
    const value = key in changes ? changes[key as keyof typeof changes] : null;
    return Array.isArray(value) ? value.length : 0;
  };
  return (
    <p>
      Gaps: {count('no_longer_observed')} no longer observed · {count('persistent')} persistent ·{' '}
      {count('new')} new
    </p>
  );
}

function legState(value: unknown): string {
  if (!value || typeof value !== 'object' || !('state' in value)) return 'unavailable';
  return String(value.state).replaceAll('_', ' ');
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
