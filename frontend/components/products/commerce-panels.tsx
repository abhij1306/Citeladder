'use client';

import { useState, type ReactNode } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import type { StatusValue } from '@/components/ui/badge-variants';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Textarea } from '@/components/ui/input';
import { Select } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table';
import { commerceApi } from '@/lib/api/commerce';
import { queryKeys } from '@/lib/api/query-keys';
import type { CommerceTarget } from '@/lib/api/schemas/commerce-suite';
import { LaunchDialog } from '@/components/runs/launch-dialog';
import { useCompetitorDiscovery } from '@/lib/products/competitor-discovery';
import type { useCommerceQueries } from '@/lib/products/use-products-screen';

export type CommerceQueries = ReturnType<typeof useCommerceQueries>;
type Queries = CommerceQueries;

export function TargetSelect({
  label,
  targets,
  value,
  onChange,
  placeholder,
}: {
  label: string;
  targets: Array<{ label: string; target: CommerceTarget }>;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
}) {
  return (
    <Select aria-label={label} value={value} onChange={(event) => onChange(event.target.value)}>
      {placeholder ? (
        <option value="" disabled>
          {placeholder}
        </option>
      ) : null}
      {targets.map((item) => (
        <option
          key={`${item.target.kind}:${item.target.id}`}
          value={`${item.target.kind}:${item.target.id}`}
        >
          {item.label}
        </option>
      ))}
    </Select>
  );
}

/**
 * Discovery status as a sentence, not a status string dropped into one.
 * Interpolating the raw value produced "Discovery for this category is
 * succeeded", and `unavailable` read as success to anyone skimming.
 */
export function discoveryMessage(status: string, kind: string, errorCode: string): string {
  if (status === 'succeeded') return `Discovery finished for this ${kind}.`;
  if (status === 'cancelled') return `Discovery was cancelled for this ${kind}.`;
  if (status === 'failed') {
    if (errorCode === 'unusable_target') {
      return `This ${kind} needs a clearer name before competitors can be found.`;
    }
    if (errorCode === 'provider_unavailable') {
      return 'Competitor discovery is unavailable: the search provider is not configured.';
    }
    return `Discovery failed for this ${kind}${errorCode ? ` (${errorCode})` : ''}.`;
  }
  return `Finding competitors for this ${kind}…`;
}

export function availableTargets(query: Queries['catalog']) {
  if (!query.data) return [];
  return [
    ...query.data.categories.map((row) => ({
      label: row.name,
      target: { kind: 'category' as const, id: row.id },
    })),
    ...query.data.products.map((row) => ({
      label: row.name || row.canonical_url,
      target: { kind: 'product' as const, id: row.id },
    })),
  ];
}

/** The candidate's domain — what a person recognises as "who is this?". */
export function competitorHost(url: string): string {
  try {
    return new URL(url).hostname.replace(/^www\./, '');
  } catch {
    return url;
  }
}

const COMPETITOR_TONES: Record<string, StatusValue> = {
  approved: 'success',
  rejected: 'danger',
  excluded: 'danger',
  pending: 'info',
};

export function competitorTone(state: string): StatusValue {
  return COMPETITOR_TONES[state] ?? 'info';
}

/**
 * Loading / error / empty / ready for the candidate list.
 *
 * Zero candidates used to render an empty `<tbody>` under a full header, which
 * looks identical to a list that has not loaded — the state the user reported
 * as the panel "always pending".
 */
function renderCompetitors(
  query: Queries['competitors'],
  discovering: boolean,
  render: (rows: NonNullable<Queries['competitors']['data']>) => ReactNode,
): ReactNode {
  if (query.isError) return <Alert tone="danger">Competitors could not be loaded.</Alert>;
  if (query.isPending) return <Skeleton className="h-24 w-full" />;
  const rows = query.data ?? [];
  if (rows.length === 0) {
    return (
      <p className="text-muted py-8 text-center text-sm">
        {discovering
          ? 'Looking for competitors…'
          : 'No candidates yet. Run Discover to find competing brands for this target.'}
      </p>
    );
  }
  return render(rows);
}

export function CompetitorsPanel({ projectId, queries }: { projectId: string; queries: Queries }) {
  const client = useQueryClient();
  const targets = availableTargets(queries.catalog);
  const [selected, setSelected] = useState('');
  const current =
    targets.find((row) => `${row.target.kind}:${row.target.id}` === selected) ?? targets[0];
  const refresh = () =>
    client.invalidateQueries({ queryKey: queryKeys.commerce.competitors(projectId) });
  const { tasks, discover } = useCompetitorDiscovery(projectId);
  const decide = useMutation({
    mutationFn: ({ id, decision }: { id: string; decision: 'approved' | 'rejected' }) =>
      commerceApi.decideCompetitor(projectId, id, decision),
    onSuccess: refresh,
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Competitor candidates</CardTitle>
        <CardDescription>
          Discovery is optional and evidence-backed. Candidates do not enter measurement until
          approved.
        </CardDescription>
        {current ? (
          <div className="flex gap-2">
            <TargetSelect
              label="Competitor discovery target"
              targets={targets}
              value={`${current.target.kind}:${current.target.id}`}
              onChange={setSelected}
            />
            <Button onClick={() => discover.mutate([current.target])} disabled={discover.isPending}>
              Discover
            </Button>
          </div>
        ) : (
          <p>Project a catalog before discovering competitors.</p>
        )}
        {discover.isError || decide.isError ? (
          <Alert tone="danger">The competitor update failed. Please try again.</Alert>
        ) : null}
        {tasks.map((task) => (
          <Alert key={task.id} tone={task.status === 'failed' ? 'danger' : 'info'}>
            {discoveryMessage(task.status, task.target.kind, task.error_code)}
          </Alert>
        ))}
      </CardHeader>
      <CardContent>
        {renderCompetitors(queries.competitors, discover.isPending, (rows) => (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Candidate</TableHead>
                <TableHead>Target</TableHead>
                <TableHead>State</TableHead>
                <TableHead>Decision</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {rows.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>
                    <a className="text-link font-medium" href={row.canonical_url}>
                      {competitorHost(row.canonical_url)}
                    </a>
                    {row.product_name ? (
                      <span className="text-muted block truncate text-xs">{row.product_name}</span>
                    ) : null}
                  </TableCell>
                  <TableCell>{row.target_kind}</TableCell>
                  <TableCell>
                    <Badge variant="status" value={competitorTone(row.state)}>
                      {row.state}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex gap-2">
                      <Button
                        size="sm"
                        disabled={discover.isPending || decide.isPending}
                        onClick={() => decide.mutate({ id: row.id, decision: 'approved' })}
                      >
                        Approve
                      </Button>
                      <Button
                        size="sm"
                        variant="secondary"
                        disabled={discover.isPending || decide.isPending}
                        onClick={() => decide.mutate({ id: row.id, decision: 'rejected' })}
                      >
                        Reject
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        ))}
      </CardContent>
    </Card>
  );
}

export function BuyerPromptsPanel({ projectId, queries }: { projectId: string; queries: Queries }) {
  const client = useQueryClient();
  const targets = availableTargets(queries.catalog);
  const [selected, setSelected] = useState('');
  const [text, setText] = useState('');
  const [launchOpen, setLaunchOpen] = useState(false);
  const current =
    targets.find((row) => `${row.target.kind}:${row.target.id}` === selected) ?? targets[0];
  const refresh = () =>
    client.invalidateQueries({ queryKey: queryKeys.commerce.buyerPrompts(projectId) });
  const manual = useMutation({
    mutationFn: () => commerceApi.addBuyerPrompt(projectId, current.target, text),
    onSuccess: async () => {
      setText('');
      await refresh();
    },
  });
  const generate = useMutation({
    mutationFn: () => commerceApi.generateBuyerPrompts(projectId, [current.target], 5),
    onSuccess: refresh,
  });
  const decide = useMutation({
    mutationFn: ({ id, approved }: { id: string; approved: boolean }) =>
      commerceApi.decideBuyerPrompt(projectId, id, approved),
    onSuccess: refresh,
  });
  const approvedPromptIds = approvedPromptsForTarget(
    queries.buyerPrompts.data ?? [],
    current?.target,
  );
  const writePending = [manual.isPending, generate.isPending].some(Boolean);
  const actionPending = [manual.isPending, generate.isPending, decide.isPending].some(Boolean);
  const updateFailed = [manual.isError, generate.isError, decide.isError].some(Boolean);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Buyer prompts</CardTitle>
        <CardDescription>
          Generated prompts are disabled until explicit approval. Manual entry remains available
          when no model is configured.
        </CardDescription>
        {current ? (
          <>
            <TargetSelect
              label="Buyer prompt target"
              targets={targets}
              value={`${current.target.kind}:${current.target.id}`}
              onChange={setSelected}
            />
            <Textarea
              aria-label="Manual buyer prompt"
              value={text}
              onChange={(event) => setText(event.target.value)}
              placeholder="What would a buyer ask?"
            />
            <div className="flex gap-2">
              <Button disabled={!text.trim() || writePending} onClick={() => manual.mutate()}>
                Add manually
              </Button>
              <Button variant="secondary" disabled={writePending} onClick={() => generate.mutate()}>
                Generate 5
              </Button>
              <Button
                disabled={!approvedPromptIds.length || writePending}
                onClick={() => setLaunchOpen(true)}
              >
                Review estimate and launch
              </Button>
            </div>
            <LaunchDialog
              open={launchOpen}
              onOpenChange={setLaunchOpen}
              projectId={projectId}
              fixedPromptIds={approvedPromptIds}
              promptSelectionLabel={`${approvedPromptIds.length} approved prompts for ${current.label}`}
              auditScope="commerce"
            />
          </>
        ) : (
          <p>Project a catalog before creating buyer prompts.</p>
        )}
        {updateFailed ? (
          <Alert tone="danger">The buyer-prompt update failed. Please try again.</Alert>
        ) : null}
      </CardHeader>
      <CardContent>
        <BuyerPromptsContent
          query={queries.buyerPrompts}
          actionPending={actionPending}
          onToggle={(id, approved) => decide.mutate({ id, approved })}
        />
      </CardContent>
    </Card>
  );
}

function approvedPromptsForTarget(
  prompts: NonNullable<Queries['buyerPrompts']['data']>,
  target?: CommerceTarget,
) {
  if (!target) return [];
  return prompts
    .filter((row) => row.enabled && row.target.kind === target.kind && row.target.id === target.id)
    .map((row) => row.id);
}

function BuyerPromptsContent({
  query,
  actionPending,
  onToggle,
}: {
  query: Queries['buyerPrompts'];
  actionPending: boolean;
  onToggle: (id: string, approved: boolean) => void;
}) {
  if (query.isError) return <Alert tone="danger">Buyer prompts could not be loaded.</Alert>;
  if (query.isPending) return <p>Loading persisted buyer prompts…</p>;
  if (!query.isSuccess) return null;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Prompt</TableHead>
          <TableHead>Target</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Approval</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {query.data.map((row) => (
          <TableRow key={row.id}>
            <TableCell>{row.text}</TableCell>
            <TableCell>{row.target.kind}</TableCell>
            <TableCell>{row.enabled ? 'Approved' : 'Draft'}</TableCell>
            <TableCell>
              <Button
                size="sm"
                disabled={actionPending}
                onClick={() => onToggle(row.id, !row.enabled)}
              >
                {row.enabled ? 'Disable' : 'Approve'}
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}

export { ShelfPanel } from './shelf-panel';
