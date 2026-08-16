'use client';

import { useQuery } from '@tanstack/react-query';
import { Check, Copy, Download, RefreshCw, Sparkles, TrendingUp, X } from 'lucide-react';
import Link from 'next/link';
import { type RefObject, useEffect, useMemo, useRef, useState } from 'react';

import { SkillPicker } from '@/components/content/skill-picker';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { eyebrowClasses } from '@/components/ui/eyebrow';
import { Textarea } from '@/components/ui/input';
import { Skeleton } from '@/components/ui/skeleton';
import { displayHeadingLgClasses } from '@/components/ui/typography';
import type { RunStatusValue } from '@/components/ui/badge-variants';
import { CONTENT_PROMPT_MAX_LEN, contentApi, type ContentSkillView } from '@/lib/api/content';
import { demandApi } from '@/lib/api/demand';
import { queryKeys } from '@/lib/api/query-keys';
import { ApiError, httpErrorStatus } from '@/lib/api/errors';
import { buildDemandBrief } from '@/lib/demand/content-brief';
import type {
  ContentGenerationDetail,
  ContentGenerationListItem,
  ContentGenerationStatus,
} from '@/lib/api/types';
import {
  isTerminalContentStatus,
  useContentGenerations,
} from '@/lib/content/use-content-generations';
import { ContentMarkdown } from '@/lib/content/markdown';
import { ICONS } from '@/lib/icons';
import { useActiveProject } from '@/lib/project/project-context';
import { saveBlob } from '@/lib/site-health/download';
import { cn } from '@/lib/utils';

/** Map an action failure to the user-facing message (409s are specific,
 * everything else generic). */
function actionErrorMessage(error: unknown): string {
  if (httpErrorStatus(error) === 409) {
    const body = error instanceof ApiError ? error.body : '';
    if (body.includes('provider_not_configured')) {
      return 'Content generation is not configured — a provider API key is missing.';
    }
    if (body.includes('cancel_not_allowed')) {
      return 'This generation already finished, so it can no longer be cancelled.';
    }
    if (body.includes('idempotency_conflict')) {
      return 'A different request was already submitted with this key. Please try again.';
    }
  }
  return 'Something went wrong while generating your content. You can try again.';
}

/** Content statuses rendered through the existing run-status badge family. */
const STATUS_BADGE: Record<ContentGenerationStatus, RunStatusValue> = {
  queued: 'queued',
  leased: 'queued',
  running: 'running',
  retry_wait: 'running',
  succeeded: 'completed',
  failed: 'failed',
  cancelled: 'cancelled',
};

/** Used only until the catalog loads and reports its own default. */
const FALLBACK_SKILL_ID = 'content_page';

/** No handoff in progress; every demand-brief outcome is spread from this. */
const IDLE_BRIEF = {
  brief: null as ReturnType<typeof buildDemandBrief> | null,
  loading: false,
  notFound: false,
  failed: false,
} as const;

function historyLabel(item: ContentGenerationListItem): string {
  return item.prompt_preview || 'Untitled generation';
}

/** The server-owned skill catalog. Static config, so it never refetches. */
function useSkillCatalog() {
  return useQuery({
    queryKey: queryKeys.content.skills(),
    queryFn: ({ signal }) => contentApi.listSkills({ signal }),
    staleTime: Infinity,
  });
}

/**
 * Rebuilds the brief for a demand signal arriving via `?demand_signal_id=`.
 *
 * Only the id travels in the URL; the numbers are read from the live snapshot
 * so a bookmarked link can never quote figures that have since been
 * recomputed.
 *
 * `notFound` and `failed` are distinct outcomes: the signal genuinely being
 * absent from the latest snapshot (recomputed away, or another project's) is
 * not the same as the request failing, and telling a user their signal is gone
 * because the network blipped sends them to rebuild work that still exists.
 */
function useDemandBrief(projectId: string, demandSignalId?: string | null) {
  const snapshot = useQuery({
    queryKey: ['demand', projectId, 'latest'],
    queryFn: ({ signal }) => demandApi.getLatest(projectId, { signal }),
    enabled: Boolean(demandSignalId),
  });
  const activeProject = useActiveProject();
  const signals = snapshot.data?.signals;
  const brandName = activeProject?.brand_name;

  // Memoised so the brief keeps a stable identity across renders — it seeds
  // the composer through an effect, which must not re-fire on every keystroke.
  const { isLoading, isError } = snapshot;

  return useMemo(() => {
    if (!demandSignalId) return IDLE_BRIEF;
    if (isLoading) return { ...IDLE_BRIEF, loading: true };
    // A failed request is not a missing signal.
    if (isError || !signals) return { ...IDLE_BRIEF, failed: true };

    const match = signals.find((item) => item.id === demandSignalId);
    if (!match) return { ...IDLE_BRIEF, notFound: true };
    return {
      ...IDLE_BRIEF,
      brief: buildDemandBrief(match, brandName ? { brand_name: brandName } : null),
    };
  }, [demandSignalId, signals, isLoading, isError, brandName]);
}

/**
 * Content screen (prompt-box-first, designs `content-*.html`): one composer
 * with an output-type chip + required Website context, and four
 * states — ready, generating (locked composer + Cancel), result (sanitised
 * Markdown + provenance + truncation warning + Copy/Regenerate), error
 * (editable prompt + Try again + Dismiss preserving the prompt).
 */
export function ContentScreen({
  opportunityId,
  demandSignalId,
}: Readonly<{ opportunityId?: string | null; demandSignalId?: string | null }>) {
  const activeProject = useActiveProject();
  const projectId = activeProject?.id ?? null;

  if (!projectId) {
    return (
      <Card>
        <CardContent className="flex flex-col items-start gap-3 py-8">
          <p className="text-secondary text-sm">
            Create a project first — content generation needs a project and its website.
          </p>
          <Link
            href="/projects"
            className="text-accent-text text-sm font-medium underline underline-offset-4"
          >
            Go to Projects
          </Link>
        </CardContent>
      </Card>
    );
  }

  // `key` remounts on project switch so all transient state (prompt, toggle,
  // selection, mutation surfaces) resets — no cross-project bleed-through.
  return (
    <ProjectContentScreen
      key={projectId}
      projectId={projectId}
      opportunityId={opportunityId}
      demandSignalId={demandSignalId}
    />
  );
}

function ContentComposer({
  prompt,
  promptRef,
  opportunityId,
  demandSource,
  generating,
  skillId,
  skills,
  skillsLoading,
  canGenerate,
  onPromptChange,
  onSkillChange,
  onGenerate,
}: Readonly<{
  prompt: string;
  promptRef: RefObject<HTMLTextAreaElement | null>;
  opportunityId?: string | null;
  /** Provenance label when the brief was seeded from a demand signal. */
  demandSource?: string | null;
  generating: boolean;
  skillId: string;
  skills: readonly ContentSkillView[];
  skillsLoading: boolean;
  canGenerate: boolean;
  onPromptChange: (value: string) => void;
  onSkillChange: (value: string) => void;
  onGenerate: () => void;
}>) {
  return (
    <Card data-component-id="content-prompt-box">
      <CardContent className="flex flex-col gap-3 py-5">
        <div className="grid gap-1">
          <span className={eyebrowClasses}>New generation</span>
          <h2 className={displayHeadingLgClasses}>What can I help you create?</h2>
        </div>
        {opportunityId ? (
          <Alert tone="info">This draft will keep a link to the selected opportunity.</Alert>
        ) : null}
        {demandSource ? (
          <div
            data-component-id="content-demand-source"
            className="border-accent-border bg-accent-soft/40 text-secondary flex items-start gap-2 rounded-md border p-2.5 text-xs"
          >
            <TrendingUp className="text-accent-text mt-0.5 size-3.5 shrink-0" aria-hidden />
            <span>
              Brief written from the search demand signal{' '}
              <span className="text-foreground font-medium">{demandSource}</span>. Edit anything
              below before generating.
            </span>
          </div>
        ) : null}
        <Textarea
          ref={promptRef}
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
          disabled={generating}
          maxLength={CONTENT_PROMPT_MAX_LEN}
          rows={demandSource ? 10 : 4}
          aria-label="Describe the website content you want to create"
          placeholder="Describe the website content you want to create…"
        />
        <SkillPicker
          skills={skills}
          value={skillId}
          onChange={onSkillChange}
          disabled={generating}
          loading={skillsLoading}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Badge data-component-id="content-output-type" aria-label="Output type: Website page">
            Website page
          </Badge>
          <div
            data-component-id="content-website-context-required"
            className="text-secondary inline-flex items-center gap-2 text-xs font-medium"
          >
            <Sparkles className="size-3" aria-hidden />
            Uses confirmed facts and crawl evidence when available
          </div>
          <div className="ml-auto">
            <Button
              data-component-id="content-generate-button"
              disabled={!canGenerate}
              onClick={onGenerate}
            >
              Generate
            </Button>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function GeneratingPanel({
  selectedId,
  cancelling,
  onCancel,
}: Readonly<{
  selectedId: string | null;
  cancelling: boolean;
  onCancel: (generationId: string) => void;
}>) {
  return (
    <Card data-component-id="content-generating-panel">
      <CardContent className="flex items-center gap-4 py-6">
        <div role="status" aria-label="Generating content" className="flex items-center gap-3">
          <ICONS.spinner className="text-accent size-5 animate-spin" aria-hidden />
          <span className="text-secondary text-sm">Generating your content…</span>
        </div>
        <div className="ml-auto">
          <Button
            variant="secondary"
            data-component-id="content-cancel-button"
            disabled={!selectedId || cancelling}
            onClick={() => selectedId && onCancel(selectedId)}
          >
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function GenerationErrorPanel({
  mutationError,
  failedGenerationId,
  retrying,
  onTryAgain,
  onDismiss,
}: Readonly<{
  mutationError: unknown;
  failedGenerationId: string | null;
  retrying: boolean;
  onTryAgain: (generationId: string) => void;
  onDismiss: () => void;
}>) {
  return (
    <Card data-component-id="content-error-panel">
      <CardContent className="flex flex-col gap-3 py-5">
        <div role="alert" className="text-danger-text flex items-start gap-2 text-sm">
          <ICONS.warning className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            {mutationError
              ? actionErrorMessage(mutationError)
              : 'Generation failed. You can edit your prompt and try again.'}
          </span>
        </div>
        <div className="flex gap-2">
          {failedGenerationId ? (
            <Button
              data-component-id="content-retry-button"
              disabled={retrying}
              onClick={() => onTryAgain(failedGenerationId)}
            >
              <RefreshCw className="mr-1.5 size-4" aria-hidden />
              Try again
            </Button>
          ) : null}
          <Button
            variant="secondary"
            data-component-id="content-dismiss-button"
            onClick={onDismiss}
          >
            <X className="mr-1.5 size-4" aria-hidden />
            Dismiss
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function GenerationResult({
  detail,
  copied,
  copyLabel,
  regenerating,
  feedbackPending,
  onCopy,
  onExport,
  onRegenerate,
  onFeedback,
}: Readonly<{
  detail: ContentGenerationDetail;
  copied: boolean;
  copyLabel: string;
  regenerating: boolean;
  feedbackPending: boolean;
  onCopy: () => void;
  onExport: () => void;
  onRegenerate: (generationId: string) => void;
  onFeedback: (generationId: string, feedback: 'accepted' | 'rejected') => void;
}>) {
  return (
    <Card data-component-id="content-result-card">
      <CardContent className="flex flex-col gap-4 py-5">
        {detail.output_truncated ? (
          <div data-component-id="content-truncation-warning">
            <Alert tone="warning">
              The output hit the length limit and may be incomplete. Regenerate or shorten your
              prompt for a complete result.
            </Alert>
          </div>
        ) : null}
        <div data-component-id="content-result-body">
          <ContentMarkdown markdown={detail.output_text ?? ''} />
        </div>
        <p data-component-id="content-ai-disclaimer" className="text-secondary text-xs">
          AI-generated {detail.skill_id} — review and revise before publishing. Generated prose
          never becomes a project fact.
        </p>
        <div
          data-component-id="content-result-provenance"
          className="border-border-subtle text-muted text-2xs flex flex-wrap items-center gap-x-4 gap-y-1 border-t pt-3 font-mono"
        >
          <span>Requested model: {detail.requested_model}</span>
          {detail.returned_model ? <span>Returned model: {detail.returned_model}</span> : null}
          <span>
            Grounding:{' '}
            {detail.grounding_status === 'included'
              ? `${detail.grounding_summary.allowed_fact_count} confirmed facts · ${detail.grounding_summary.crawl_fragment_count} crawl fragments`
              : detail.grounding_status === 'conflicting'
                ? 'Conflicting facts omitted'
                : 'Unavailable — ungrounded draft'}
          </span>
        </div>
        <div className="flex gap-2">
          <Button variant="secondary" data-component-id="content-copy-button" onClick={onCopy}>
            {copied ? (
              <Check className="mr-1.5 size-4" aria-hidden />
            ) : (
              <Copy className="mr-1.5 size-4" aria-hidden />
            )}
            {copyLabel}
          </Button>
          <Button variant="secondary" data-component-id="content-export-button" onClick={onExport}>
            <Download className="mr-1.5 size-4" aria-hidden />
            Export Markdown
          </Button>
          <Button
            variant="secondary"
            data-component-id="content-regenerate-button"
            disabled={regenerating}
            onClick={() => onRegenerate(detail.id)}
          >
            <RefreshCw className="mr-1.5 size-4" aria-hidden />
            Regenerate
          </Button>
          {detail.feedback === null ? (
            <>
              <Button disabled={feedbackPending} onClick={() => onFeedback(detail.id, 'accepted')}>
                Helpful
              </Button>
              <Button
                variant="secondary"
                disabled={feedbackPending}
                onClick={() => onFeedback(detail.id, 'rejected')}
              >
                Not useful
              </Button>
            </>
          ) : (
            <span className="text-secondary self-center text-sm">
              {detail.feedback === 'accepted' ? 'Marked helpful' : 'Marked not useful'}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}

function GenerationHistory({
  items,
  loading,
  selectedId,
  onSelect,
}: Readonly<{
  items: ContentGenerationListItem[];
  loading: boolean;
  selectedId: string | null;
  onSelect: (generationId: string) => void;
}>) {
  return (
    <section data-component-id="content-history" className="flex flex-col gap-2">
      <div className="grid gap-1">
        <span className={eyebrowClasses}>History</span>
        <h2 className={displayHeadingLgClasses}>Recent generations</h2>
      </div>
      {loading ? (
        <Skeleton className="h-24 w-full" />
      ) : items.length === 0 ? (
        <p className="text-secondary text-sm">No generations yet.</p>
      ) : (
        <ul className="flex flex-col gap-1">
          {items.map((item) => (
            <li key={item.id}>
              <button
                type="button"
                onClick={() => onSelect(item.id)}
                className={cn(
                  'focus-ring hover:bg-background-alt flex w-full items-center gap-3 rounded-md border px-3 py-2 text-left text-sm transition-colors',
                  item.id === selectedId
                    ? 'border-accent-border bg-accent-soft/40'
                    : 'border-border',
                )}
              >
                <span className="text-foreground min-w-0 flex-1 truncate">
                  {historyLabel(item)}
                </span>
                <Badge variant="run-status" value={STATUS_BADGE[item.status]}>
                  {item.status.replace('_', ' ')}
                </Badge>
              </button>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function ProjectContentScreen({
  projectId,
  opportunityId,
  demandSignalId,
}: Readonly<{
  projectId: string;
  opportunityId?: string | null;
  demandSignalId?: string | null;
}>) {
  const [prompt, setPrompt] = useState('');
  // `null` = the user has not chosen, so the catalog's default applies. A
  // concrete initial value would instead pin the selection to a stale id.
  const [chosenSkillId, setChosenSkillId] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);
  const [copyFailed, setCopyFailed] = useState(false);
  const promptRef = useRef<HTMLTextAreaElement | null>(null);

  const skillCatalog = useSkillCatalog();
  const skills = skillCatalog.data?.skills ?? [];
  const demand = useDemandBrief(projectId, demandSignalId);

  // Seed the composer from the demand brief exactly once. Keyed on the brief's
  // prompt text so a later recompute does not overwrite the user's edits.
  const seededRef = useRef<string | null>(null);
  useEffect(() => {
    const brief = demand.brief;
    if (!brief || seededRef.current === brief.prompt) return;
    seededRef.current = brief.prompt;
    setPrompt(brief.prompt);
    setChosenSkillId(brief.suggestedSkillId);
  }, [demand.brief]);

  const {
    listQuery,
    detailQuery,
    selectedId,
    setSelectedId,
    enqueueMutation,
    regenerateMutation,
    tryAgainMutation,
    cancelMutation,
    feedbackMutation,
  } = useContentGenerations(projectId, undefined, opportunityId);

  const detail: ContentGenerationDetail | null = detailQuery.data ?? null;
  const generating = Boolean(
    (detail && !isTerminalContentStatus(detail.status)) || enqueueMutation.isPending,
  );
  const failed = detail?.status === 'failed';
  const succeeded = detail?.status === 'succeeded';

  const mutationError =
    enqueueMutation.error ??
    regenerateMutation.error ??
    tryAgainMutation.error ??
    feedbackMutation.error ??
    null;
  const showErrorPanel = !generating && (Boolean(mutationError) || failed);

  useEffect(() => {
    if (showErrorPanel) promptRef.current?.focus();
  }, [showErrorPanel]);

  const trimmed = prompt.trim();
  // The catalog owns the default, and an id it no longer offers (a stale
  // selection after a catalog change) must not be sent for the backend to
  // reject — in both cases fall back to the catalog's own default.
  const catalogDefault = skillCatalog.data?.default_skill_id ?? FALLBACK_SKILL_ID;
  const effectiveSkillId =
    chosenSkillId && (skills.length === 0 || skills.some((s) => s.id === chosenSkillId))
      ? chosenSkillId
      : catalogDefault;
  const canGenerate = trimmed.length > 0 && trimmed.length <= CONTENT_PROMPT_MAX_LEN && !generating;

  const handleGenerate = () => {
    if (!canGenerate) return;
    cancelMutation.reset();
    feedbackMutation.reset();
    enqueueMutation.mutate({ prompt: trimmed, skillId: effectiveSkillId });
  };

  const handleDismiss = () => {
    // Clears only the transient error surface; prompt text survives.
    enqueueMutation.reset();
    regenerateMutation.reset();
    tryAgainMutation.reset();
    cancelMutation.reset();
    feedbackMutation.reset();
    setSelectedId(null);
  };

  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, []);

  const handleCopy = async () => {
    if (!detail?.output_text) return;
    if (timerRef.current) clearTimeout(timerRef.current);
    try {
      // Clipboard access can be denied (permissions policy, insecure
      // context) — surface a visible failure instead of an unhandled reject.
      await navigator.clipboard.writeText(detail.output_text);
      setCopyFailed(false);
      setCopied(true);
      timerRef.current = setTimeout(() => setCopied(false), 2000);
    } catch {
      setCopied(false);
      setCopyFailed(true);
      timerRef.current = setTimeout(() => setCopyFailed(false), 2000);
    }
  };

  const handleExport = () => {
    if (!detail?.output_text) return;
    saveBlob(
      new Blob([detail.output_text], { type: 'text/markdown;charset=utf-8' }),
      `content-${detail.id.slice(0, 8)}.md`,
    );
  };

  let copyLabel = 'Copy';
  if (copied) copyLabel = 'Copied';
  else if (copyFailed) copyLabel = 'Copy failed';

  return (
    <div className="grid gap-6">
      {demand.notFound ? (
        <Alert tone="warning">
          That demand signal is no longer in the latest snapshot — it may have been recomputed away.
          Start from a current signal on Search Demand, or write your own brief below.
        </Alert>
      ) : null}
      {demand.failed ? (
        <Alert tone="danger">
          Search demand could not be loaded, so the brief for this signal could not be built. The
          signal itself may still exist — reload to try again, or write your own brief below.
        </Alert>
      ) : null}
      <ContentComposer
        prompt={prompt}
        promptRef={promptRef}
        opportunityId={opportunityId}
        demandSource={demand.brief?.sourceLabel ?? null}
        generating={generating}
        skillId={effectiveSkillId}
        skills={skills}
        skillsLoading={skillCatalog.isLoading}
        canGenerate={canGenerate}
        onPromptChange={setPrompt}
        onSkillChange={setChosenSkillId}
        onGenerate={handleGenerate}
      />

      {generating ? (
        <GeneratingPanel
          selectedId={selectedId}
          cancelling={cancelMutation.isPending}
          onCancel={(generationId) => cancelMutation.mutate(generationId)}
        />
      ) : null}

      {showErrorPanel ? (
        <GenerationErrorPanel
          mutationError={mutationError}
          failedGenerationId={failed && detail ? detail.id : null}
          retrying={tryAgainMutation.isPending}
          onTryAgain={(generationId) => tryAgainMutation.mutate(generationId)}
          onDismiss={handleDismiss}
        />
      ) : null}

      {!generating && succeeded && detail?.output_text ? (
        <GenerationResult
          detail={detail}
          copied={copied}
          copyLabel={copyLabel}
          regenerating={regenerateMutation.isPending}
          feedbackPending={feedbackMutation.isPending}
          onCopy={handleCopy}
          onExport={handleExport}
          onRegenerate={(generationId) => regenerateMutation.mutate(generationId)}
          onFeedback={(generationId, feedback) =>
            feedbackMutation.mutate({ generationId, feedback })
          }
        />
      ) : null}

      <GenerationHistory
        items={listQuery.data ?? []}
        loading={listQuery.isLoading}
        selectedId={selectedId}
        onSelect={setSelectedId}
      />
    </div>
  );
}
