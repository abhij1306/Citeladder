import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { inputClasses, Textarea } from '@/components/ui/input';
import type { CommerceCandidate } from '@/lib/api/types';
import { formatUtcTimestamp } from '@/lib/format';

type SourceKind = 'csv' | 'json' | 'url';

function sourcePlaceholder(kind: SourceKind): string {
  if (kind === 'url') return 'One product or category URL per line';
  if (kind === 'json') return '[{ "name": "Product", "sku": "SKU-1" }]';
  return 'name,sku,price,currency,url\nProduct,SKU-1,99,USD,https://example.com/product';
}

function DiscoveryActions({
  source,
  sourceKind,
  isPreviewing,
  isCreating,
  canCreateUpload,
  onPreview,
  onCreate,
}: Readonly<{
  source: string;
  sourceKind: SourceKind;
  isPreviewing: boolean;
  isCreating: boolean;
  canCreateUpload: boolean;
  onPreview: () => void;
  onCreate: () => void;
}>) {
  if (sourceKind === 'url') {
    return (
      <Button variant="primary" onClick={onCreate} disabled={!source.trim() || isCreating}>
        {isCreating ? 'Creating…' : 'Create discovery run'}
      </Button>
    );
  }
  return (
    <>
      <Button variant="secondary" onClick={onPreview} disabled={!source.trim() || isPreviewing}>
        Preview candidates
      </Button>
      <Button
        variant="primary"
        onClick={onCreate}
        disabled={!source.trim() || isCreating || !canCreateUpload}
      >
        {isCreating ? 'Creating…' : 'Create discovery run'}
      </Button>
    </>
  );
}

function SourceFeedback({
  invalidJson,
  feedback,
  preview,
}: Readonly<{
  invalidJson: boolean;
  feedback: { tone: 'danger'; message: string } | null;
  preview:
    | {
        accepted: unknown[];
        duplicates: unknown[];
        errors: { row: number; field: string; message: string }[];
        truncated: boolean;
      }
    | undefined;
}>) {
  return (
    <>
      {invalidJson ? (
        <p className="text-danger text-sm">JSON input must be an array of candidate objects.</p>
      ) : null}
      {feedback ? <p className="text-danger text-sm">{feedback.message}</p> : null}
      {preview ? (
        <div className="grid gap-1 text-sm">
          <p>
            {preview.accepted.length} accepted · {preview.duplicates.length} duplicate rows ·{' '}
            {preview.errors.length} errors{preview.truncated ? ' · truncated' : ''}
          </p>
          {preview.errors.map((error) => (
            <p key={`${error.row}-${error.field}`} className="text-danger">
              Row {error.row}: {error.field} — {error.message}
            </p>
          ))}
        </div>
      ) : null}
    </>
  );
}

export function DiscoverySourceCard({
  source,
  sourceKind,
  setSource,
  setSourceKind,
  isPreviewing,
  isCreating,
  canCreateUpload,
  preview,
  feedback,
  onPreview,
  onCreate,
}: Readonly<{
  source: string;
  sourceKind: SourceKind;
  setSource: (value: string) => void;
  setSourceKind: (value: SourceKind) => void;
  isPreviewing: boolean;
  isCreating: boolean;
  canCreateUpload: boolean;
  preview:
    | {
        accepted: unknown[];
        duplicates: unknown[];
        errors: { row: number; field: string; message: string }[];
        truncated: boolean;
      }
    | undefined;
  feedback: { tone: 'danger'; message: string } | null;
  onPreview: () => void;
  onCreate: () => void;
}>) {
  const invalidJson = Boolean(
    sourceKind === 'json' && source.trim() && !canCreateUpload && !preview,
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>Discover products</CardTitle>
        <CardDescription>
          Preview CSV or JSON candidates, or queue product URLs. Discovery evidence remains
          reviewable before it reaches the catalog.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-3">
        <label className="text-foreground grid gap-1 text-sm">
          <span>Input type</span>
          <select
            className={inputClasses}
            value={sourceKind}
            onChange={(event) => setSourceKind(event.target.value as SourceKind)}
          >
            <option value="csv">CSV</option>
            <option value="json">JSON rows</option>
            <option value="url">Product URLs</option>
          </select>
        </label>
        <Textarea
          aria-label="Discovery input"
          value={source}
          onChange={(event) => setSource(event.target.value)}
          placeholder={sourcePlaceholder(sourceKind)}
        />
        <DiscoveryActions
          source={source}
          sourceKind={sourceKind}
          isPreviewing={isPreviewing}
          isCreating={isCreating}
          canCreateUpload={canCreateUpload}
          onPreview={onPreview}
          onCreate={onCreate}
        />
        <SourceFeedback invalidJson={invalidJson} feedback={feedback} preview={preview} />
      </CardContent>
    </Card>
  );
}

export function DiscoveryRunsCard({
  runs,
  loading,
  onSelect,
}: Readonly<{
  runs: { id: string; input_kind: string; created_at: string; status: string }[];
  loading: boolean;
  onSelect: (id: string) => void;
}>) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Discovery runs</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2">
        {runs.map((run) => (
          <button
            key={run.id}
            type="button"
            className="hover:bg-surface-hover flex items-center justify-between rounded-sm p-2 text-left"
            onClick={() => onSelect(run.id)}
          >
            <span>
              {run.input_kind} · {formatUtcTimestamp(run.created_at)}
            </span>
            <Badge>{run.status}</Badge>
          </button>
        ))}
        {loading ? <p className="text-muted text-sm">Loading runs…</p> : null}
        {!loading && !runs.length ? (
          <p className="text-muted text-sm">No discovery runs yet.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}

function CandidateCard({
  candidate,
  selectedTarget,
  setSelectedTarget,
  busy,
  error,
  onDecide,
}: Readonly<{
  candidate: CommerceCandidate;
  selectedTarget: string;
  setSelectedTarget: (target: string) => void;
  busy: boolean;
  error: string | null;
  onDecide: (status: 'accepted' | 'rejected') => void;
}>) {
  const targetMatches = candidate.matches.filter((match) => match.target_id);
  const candidateName = typeof candidate.identity.name === 'string' ? candidate.identity.name : '—';
  return (
    <div className="border-border grid gap-2 rounded-sm border p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <strong>{candidateName}</strong>
        <Badge>
          {candidate.matches.some((match) => match.review_required)
            ? 'Review required'
            : 'Ready for review'}
        </Badge>
      </div>
      <p className="text-muted">
        Confidence {candidate.extraction_confidence.toFixed(2)} · artifact {candidate.artifact_id}
      </p>
      {candidate.matches.map((match, index) => (
        <p key={`${candidate.id}-${index}`} className="text-muted">
          {match.target_kind}: {match.confidence.toFixed(2)} —{' '}
          {match.reasons.join(', ') || 'No deterministic match reason'}
        </p>
      ))}
      {targetMatches.length ? (
        <label className="text-foreground grid gap-1">
          <span>Catalog target</span>
          <select
            aria-label={`Match target for ${candidateName}`}
            className={inputClasses}
            value={selectedTarget}
            onChange={(event) => setSelectedTarget(event.target.value)}
          >
            <option value="">Create a new catalog product</option>
            {targetMatches.map((match) => (
              <option key={match.target_id ?? match.target_kind} value={match.target_id!}>
                {match.target_kind} · {match.target_id} · {match.confidence.toFixed(2)}
                {match.review_required ? ' · review required' : ''}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      <div className="flex gap-2">
        <Button size="sm" variant="primary" onClick={() => onDecide('accepted')} disabled={busy}>
          Accept / review
        </Button>
        <Button size="sm" variant="ghost" onClick={() => onDecide('rejected')} disabled={busy}>
          Reject
        </Button>
      </div>
      {error ? <p className="text-danger">{error}</p> : null}
    </div>
  );
}

export function CandidateCards({
  kind,
  candidates,
  selectedTargets,
  setSelectedTarget,
  busy,
  errorCandidateId,
  error,
  onDecide,
}: Readonly<{
  kind: 'own' | 'competitor';
  candidates: CommerceCandidate[];
  selectedTargets: Record<string, string>;
  setSelectedTarget: (candidateId: string, target: string) => void;
  busy: boolean;
  errorCandidateId: string | undefined;
  error: string | null;
  onDecide: (candidate: CommerceCandidate, status: 'accepted' | 'rejected') => void;
}>) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{kind === 'own' ? 'Own candidates' : 'Competitor candidates'}</CardTitle>
      </CardHeader>
      <CardContent className="grid gap-2">
        {candidates.map((candidate) => (
          <CandidateCard
            key={candidate.id}
            candidate={candidate}
            selectedTarget={selectedTargets[candidate.id] ?? ''}
            setSelectedTarget={(target) => setSelectedTarget(candidate.id, target)}
            busy={busy}
            error={errorCandidateId === candidate.id ? error : null}
            onDecide={(status) => onDecide(candidate, status)}
          />
        ))}
        {!candidates.length ? (
          <p className="text-muted text-sm">No {kind} candidates in this selection.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
