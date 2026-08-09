'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useId, useState } from 'react';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/input';
import { siteIntelligenceApi, type CorrectionCreateInput } from '@/lib/api/site-intelligence';
import { queryKeys } from '@/lib/api/query-keys';
import type { ContradictionGroup, KnowledgeAssertionItem } from '@/lib/api/types';

function correctionInput(side: KnowledgeAssertionItem): CorrectionCreateInput['value'] | null {
  if (side.value_type === 'number' || side.value_type === 'money') {
    return side.numeric_value;
  }
  if (side.value_type === 'boolean') {
    if (side.normalized_value === 'true') return true;
    if (side.normalized_value === 'false') return false;
    return null;
  }
  if (side.value_type === 'object') return null;
  return side.raw_value.trim() || side.normalized_value || null;
}

export function displayValue(value: Record<string, unknown>, fallback: string): string {
  if (typeof value.normalized_value === 'string') return value.normalized_value;
  if (typeof value.canonical_name === 'string') return value.canonical_name;
  return fallback;
}

function correctedLabel(group: ContradictionGroup): string {
  const value = group.correction?.corrected_value;
  if (!value) return 'Corrected value';
  return displayValue(value, 'Corrected value');
}

function mutationMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : 'The correction could not be saved. Check the value and try again.';
}

export function ContradictionDecision({
  projectId,
  group,
}: Readonly<{ projectId: string; group: ContradictionGroup }>) {
  const queryClient = useQueryClient();
  const reasonId = useId();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reason, setReason] = useState('');

  const refreshKnowledge = () =>
    queryClient.invalidateQueries({ queryKey: queryKeys.siteIntelligence.all });
  const create = useMutation({
    mutationFn: (side: KnowledgeAssertionItem) => {
      const value = correctionInput(side);
      if (value === null) throw new Error('This value type cannot be corrected inline yet.');
      return siteIntelligenceApi.createCorrection(projectId, {
        target_kind: 'assertion',
        target_id: side.id,
        value,
        effective_scope: 'project',
        unit: side.unit,
        currency: side.currency,
        reason: reason.trim(),
      });
    },
    onSuccess: async () => {
      setSelectedId(null);
      setReason('');
      await refreshKnowledge();
    },
  });
  const withdraw = useMutation({
    mutationFn: () => {
      if (!group.correction) throw new Error('No active correction is available to withdraw.');
      return siteIntelligenceApi.withdrawCorrection(projectId, group.correction.id, reason.trim());
    },
    onSuccess: async () => {
      setReason('');
      await refreshKnowledge();
    },
  });

  const pending = create.isPending || withdraw.isPending;
  const error = create.error ?? withdraw.error;
  const selected = group.sides.find((side) => side.id === selectedId);
  const canSubmit = Boolean(selected && reason.trim()) && !pending;

  return (
    <div className="grid min-w-0 gap-3">
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <span className="text-foreground min-w-0 text-sm break-words">
          {group.subject.canonical_name}
        </span>
        <code className="text-muted text-2xs break-all">{group.predicate_id}</code>
        <Badge
          variant="status"
          value={group.resolution_state === 'corrected' ? 'success' : 'danger'}
        >
          {group.resolution_state === 'corrected'
            ? 'corrected'
            : `${group.sides.length} conflicting values`}
        </Badge>
      </div>

      <ul className="grid gap-2" aria-label={`Observed values for ${group.predicate_id}`}>
        {group.sides.map((side) => {
          const supported = correctionInput(side) !== null;
          return (
            <li
              key={side.id}
              className="border-border-subtle grid min-w-0 gap-2 border-b pb-2 last:border-0 last:pb-0 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-center"
            >
              <div className="min-w-0">
                <p className="text-foreground text-sm break-words">{side.normalized_value}</p>
                <p className="text-muted text-2xs">
                  {side.temporal_state} · {side.evidence_refs.length} source(s)
                </p>
              </div>
              {group.resolution_state === 'corrected' ? null : (
                <Button
                  variant={selectedId === side.id ? 'primary' : 'secondary'}
                  size="sm"
                  disabled={!supported || pending}
                  aria-pressed={selectedId === side.id}
                  onClick={() => {
                    create.reset();
                    withdraw.reset();
                    setSelectedId(side.id);
                  }}
                >
                  {supported ? 'Use this value' : 'Unsupported inline'}
                </Button>
              )}
            </li>
          );
        })}
      </ul>

      {group.resolution_state === 'corrected' ? (
        <div className="bg-success-bg grid gap-3 rounded-md p-3">
          <div className="min-w-0">
            <p className="text-foreground text-sm break-words">{correctedLabel(group)}</p>
            <p className="text-muted text-2xs break-words">
              Project correction · {group.correction?.reason}
            </p>
          </div>
          <div className="grid gap-1.5">
            <label htmlFor={reasonId} className="text-secondary text-xs font-medium">
              Reason for withdrawal
            </label>
            <Textarea
              id={reasonId}
              value={reason}
              maxLength={1000}
              disabled={pending}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Explain why the derived value should become effective again."
            />
            <Button
              variant="secondary"
              size="sm"
              className="justify-self-start"
              disabled={!reason.trim() || pending}
              onClick={() => withdraw.mutate()}
            >
              {withdraw.isPending ? 'Withdrawing…' : 'Withdraw correction'}
            </Button>
          </div>
        </div>
      ) : selected ? (
        <div className="bg-background-alt grid gap-3 rounded-md p-3">
          <p className="text-secondary text-sm">
            This project-wide correction will survive later crawls. The observed values remain
            available as evidence.
          </p>
          <div className="grid gap-1.5">
            <label htmlFor={reasonId} className="text-secondary text-xs font-medium">
              Why is this the effective value?
            </label>
            <Textarea
              id={reasonId}
              value={reason}
              maxLength={1000}
              disabled={pending}
              onChange={(event) => setReason(event.target.value)}
              placeholder="Record the source or business reason for this correction."
            />
          </div>
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={!canSubmit} onClick={() => create.mutate(selected)}>
              {create.isPending ? 'Saving…' : 'Save correction'}
            </Button>
            <Button
              variant="ghost"
              size="sm"
              disabled={pending}
              onClick={() => {
                create.reset();
                withdraw.reset();
                setSelectedId(null);
                setReason('');
              }}
            >
              Cancel
            </Button>
          </div>
        </div>
      ) : null}

      {error ? <Alert tone="danger">{mutationMessage(error)}</Alert> : null}
    </div>
  );
}
