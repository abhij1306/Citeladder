'use client';

import { useMemo, useState } from 'react';

import type { CommerceCandidate, CommerceCandidateInput } from '@/lib/api/types';
import type { useCommerceDiscovery } from '@/lib/products/use-products-screen';

import { CandidateCards, DiscoveryRunsCard, DiscoverySourceCard } from './commerce-discovery-view';

type Discovery = ReturnType<typeof useCommerceDiscovery>;
type SourceKind = 'csv' | 'json' | 'url';

function parseJsonRows(value: string): CommerceCandidateInput[] | null {
  try {
    const parsed: unknown = JSON.parse(value);
    return Array.isArray(parsed) ? (parsed as CommerceCandidateInput[]) : null;
  } catch {
    return null;
  }
}

function groupCandidates(candidateData: CommerceCandidate[] | undefined) {
  const groups = { own: [] as CommerceCandidate[], competitor: [] as CommerceCandidate[] };
  for (const candidate of candidateData ?? []) groups[candidate.candidate_kind].push(candidate);
  return groups;
}

function errorMessage(error: unknown): string | null {
  return error instanceof Error
    ? error.message
    : error
      ? 'The request could not be completed.'
      : null;
}

/** Discovery controller. Source submission and candidate decisions are rendered by focused views. */
export function CommerceDiscoveryPanel({
  projectId: _projectId,
  queries,
}: Readonly<{ projectId: string; queries: Discovery }>) {
  const [source, setSource] = useState('');
  const [sourceKind, setSourceKind] = useState<SourceKind>('csv');
  const [previewFingerprint, setPreviewFingerprint] = useState<string | null>(null);
  const [selectedTargets, setSelectedTargets] = useState<Record<string, string>>({});
  const inputFingerprint = `${sourceKind}\u0000${source}`;
  const parsedJsonRows = sourceKind === 'json' ? parseJsonRows(source) : null;
  const currentPreview =
    previewFingerprint === inputFingerprint ? queries.previewMutation.data : undefined;
  const candidates = useMemo(
    () => groupCandidates(queries.candidatesQuery.data),
    [queries.candidatesQuery.data],
  );
  const canCreateUpload = Boolean(currentPreview?.accepted.length || parsedJsonRows?.length);
  const feedback = queries.previewMutation.error
    ? { tone: 'danger' as const, message: errorMessage(queries.previewMutation.error) ?? '' }
    : queries.createMutation.error
      ? { tone: 'danger' as const, message: errorMessage(queries.createMutation.error) ?? '' }
      : null;

  const previewSource = async () => {
    if (sourceKind === 'url') return;
    const body = sourceKind === 'json' ? { rows: parsedJsonRows ?? [] } : { csv_text: source };
    await queries.previewMutation.mutateAsync(body);
    setPreviewFingerprint(inputFingerprint);
  };
  const createRun = async () => {
    if (sourceKind === 'url') {
      const source_urls = source
        .split(/\r?\n/)
        .map((url) => url.trim())
        .filter(Boolean);
      await queries.createMutation.mutateAsync({ input_kind: 'url', source_urls });
      return;
    }
    await queries.createMutation.mutateAsync({
      input_kind: 'upload',
      rows: currentPreview?.accepted ?? parsedJsonRows ?? [],
    });
  };
  const decide = (candidate: CommerceCandidate, status: 'accepted' | 'rejected') => {
    queries.decisionMutation.mutate({
      candidateId: candidate.id,
      body:
        status === 'accepted'
          ? { status, target_id: selectedTargets[candidate.id] || null }
          : { status },
    });
  };

  return (
    <div className="grid gap-4" data-testid="commerce-discover-panel">
      <DiscoverySourceCard
        source={source}
        sourceKind={sourceKind}
        setSource={setSource}
        setSourceKind={setSourceKind}
        isPreviewing={queries.previewMutation.isPending}
        isCreating={queries.createMutation.isPending}
        canCreateUpload={canCreateUpload}
        preview={currentPreview}
        feedback={feedback}
        onPreview={() => void previewSource()}
        onCreate={() => void createRun()}
      />
      <DiscoveryRunsCard
        runs={queries.runsQuery.data ?? []}
        loading={queries.runsQuery.isLoading}
        onSelect={queries.setSelectedRunId}
      />
      {(['own', 'competitor'] as const).map((kind) => (
        <CandidateCards
          key={kind}
          kind={kind}
          candidates={candidates[kind]}
          selectedTargets={selectedTargets}
          setSelectedTarget={(candidateId, target) =>
            setSelectedTargets((current) => ({ ...current, [candidateId]: target }))
          }
          busy={queries.decisionMutation.isPending}
          errorCandidateId={queries.decisionMutation.variables?.candidateId}
          error={errorMessage(queries.decisionMutation.error)}
          onDecide={decide}
        />
      ))}
    </div>
  );
}
