'use client';

import { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { commerceApi } from '@/lib/api/commerce';
import { queryKeys } from '@/lib/api/query-keys';
import type { CommerceTarget } from '@/lib/api/schemas/commerce-suite';
import { LaunchDialog } from '@/components/runs/launch-dialog';

import type { CommerceQueries } from './commerce-queries';

function forTarget(
  rows: NonNullable<CommerceQueries['buyerPrompts']['data']>,
  target: CommerceTarget,
) {
  return rows.filter((row) => row.target.kind === target.kind && row.target.id === target.id);
}

export function TargetPrompts({
  projectId,
  target,
  targetLabel,
  query,
}: Readonly<{
  projectId: string;
  target: CommerceTarget;
  targetLabel: string;
  query: CommerceQueries['buyerPrompts'];
}>) {
  const client = useQueryClient();
  const [text, setText] = useState('');
  const [launchOpen, setLaunchOpen] = useState(false);
  const refresh = () =>
    client.invalidateQueries({ queryKey: queryKeys.commerce.buyerPrompts(projectId) });
  const generate = useMutation({
    mutationFn: () => commerceApi.generateBuyerPrompts(projectId, [target], 5),
    onSuccess: refresh,
  });
  const manual = useMutation({
    mutationFn: () => commerceApi.addBuyerPrompt(projectId, target, text),
    onSuccess: async () => {
      setText('');
      await refresh();
    },
  });
  const decide = useMutation({
    mutationFn: ({ id, approved }: { id: string; approved: boolean }) =>
      commerceApi.decideBuyerPrompt(projectId, id, approved),
    onSuccess: refresh,
  });
  const rows = query.data ? forTarget(query.data, target) : [];
  const approvedIds = rows.filter((row) => row.enabled).map((row) => row.id);
  const busy = [generate.isPending, manual.isPending, decide.isPending].some(Boolean);
  const failed = [generate.isError, manual.isError, decide.isError].some(Boolean);
  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="grid gap-1">
            <CardTitle>Prompts that measure it</CardTitle>
            <CardDescription>
              Generated prompts stay disabled until you approve them.
            </CardDescription>
          </div>
          <div className="flex gap-2">
            <Button variant="secondary" disabled={busy} onClick={() => generate.mutate()}>
              {generate.isPending ? 'Generating…' : 'Generate 5'}
            </Button>
            <Button disabled={!approvedIds.length || busy} onClick={() => setLaunchOpen(true)}>
              Review and launch
            </Button>
          </div>
        </div>
        {failed ? (
          <Alert tone="danger">The buyer-prompt update failed. Please try again.</Alert>
        ) : null}
        <LaunchDialog
          open={launchOpen}
          onOpenChange={setLaunchOpen}
          projectId={projectId}
          fixedPromptIds={approvedIds}
          promptSelectionLabel={`${approvedIds.length} approved prompts for ${targetLabel}`}
          auditScope="commerce"
        />
      </CardHeader>
      <CardContent className="grid gap-3">
        <PromptRows
          query={query}
          rows={rows}
          pending={busy}
          onToggle={(id, approved) => decide.mutate({ id, approved })}
        />
        {/* Manual entry is the fallback for an unconfigured model, so it is
            folded away rather than given equal billing beside Generate. */}
        <details className="text-sm">
          <summary className="text-secondary cursor-pointer">Add a prompt manually</summary>
          <div className="grid gap-2 pt-2">
            <Textarea
              aria-label="Manual buyer prompt"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="best instant read thermometer for grilling under $50"
            />
            <div>
              <Button size="sm" disabled={!text.trim() || busy} onClick={() => manual.mutate()}>
                Add prompt
              </Button>
            </div>
          </div>
        </details>
      </CardContent>
    </Card>
  );
}

function PromptRows({
  query,
  rows,
  pending,
  onToggle,
}: Readonly<{
  query: CommerceQueries['buyerPrompts'];
  rows: NonNullable<CommerceQueries['buyerPrompts']['data']>;
  pending: boolean;
  onToggle: (id: string, approved: boolean) => void;
}>) {
  if (query.isError) return <Alert tone="danger">Buyer prompts could not be loaded.</Alert>;
  if (query.isPending) return <Skeleton className="h-24 w-full" />;
  if (!rows.length) {
    return (
      <p className="text-muted py-6 text-center text-sm">
        No prompts yet for this target. Generate a set, or add one manually.
      </p>
    );
  }
  return (
    <ul className="divide-border-subtle grid divide-y">
      {rows.map((row) => (
        <li key={row.id} className="flex flex-wrap items-center gap-3 py-2">
          <span className="text-secondary min-w-0 flex-1">{row.text}</span>
          <Button
            size="sm"
            variant={row.enabled ? 'secondary' : 'primary'}
            disabled={pending}
            onClick={() => onToggle(row.id, !row.enabled)}
          >
            {row.enabled ? 'Disable' : 'Approve'}
          </Button>
        </li>
      ))}
    </ul>
  );
}
