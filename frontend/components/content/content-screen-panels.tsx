import { Check, Copy, Download, RefreshCw, Sparkles, TrendingUp, X } from 'lucide-react';
import { type RefObject } from 'react';

import { SkillPicker } from '@/components/content/skill-picker';
import { Alert } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import { Textarea } from '@/components/ui/input';
import { CONTENT_PROMPT_MAX_LEN } from '@/lib/api/content';
import type { ContentGenerationDetail } from '@/lib/api/types';
import { ContentMarkdown } from '@/lib/content/markdown';
import { ICONS } from '@/lib/icons';

import { actionErrorMessage, type ContentSkillView } from './content-screen-data';

export function ContentComposer({
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
    <Card
      data-component-id="content-prompt-box"
      className="border-border/70 bg-panel shadow-card rounded-sm border p-6 sm:p-8"
    >
      <CardContent className="flex flex-col gap-5 p-0">
        <div className="grid gap-1">
          <span className="text-muted text-xs font-semibold tracking-wider uppercase">
            New generation
          </span>
          <h2 className="font-display text-foreground text-xl font-semibold tracking-tight">
            What can I help you create?
          </h2>
        </div>
        {opportunityId ? (
          <Alert tone="info">This draft will keep a link to the selected opportunity.</Alert>
        ) : null}
        {demandSource ? <DemandSource source={demandSource} /> : null}
        <Textarea
          ref={promptRef}
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
          disabled={generating}
          maxLength={CONTENT_PROMPT_MAX_LEN}
          rows={demandSource ? 10 : 4}
          aria-label="Describe the website content you want to create"
          placeholder="Describe the website content you want to create…"
          className="border-border/80 bg-background/50 focus:bg-panel rounded-sm p-4 text-sm leading-relaxed"
        />
        <SkillPicker
          skills={skills}
          value={skillId}
          onChange={onSkillChange}
          disabled={generating}
          loading={skillsLoading}
        />
        <div className="border-border/60 flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <div className="flex flex-wrap items-center gap-3">
            <Badge data-component-id="content-output-type" aria-label="Output type: Website page">
              Website page
            </Badge>
            <div
              data-component-id="content-website-context-required"
              className="text-muted inline-flex items-center gap-1.5 text-xs font-medium"
            >
              <Sparkles className="text-accent size-3.5" aria-hidden />
              Uses confirmed facts and crawl evidence when available
            </div>
          </div>
          <Button
            data-component-id="content-generate-button"
            disabled={!canGenerate}
            onClick={onGenerate}
            className="gap-2 shadow-xs"
          >
            <Sparkles className="size-4" aria-hidden /> Generate
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

function DemandSource({ source }: Readonly<{ source: string }>) {
  return (
    <div
      data-component-id="content-demand-source"
      className="border-accent-border bg-accent-soft/50 text-secondary flex items-start gap-2.5 rounded-sm border p-3.5 text-sm"
    >
      <TrendingUp className="text-accent-text mt-0.5 size-4 shrink-0" aria-hidden />
      <span>
        Brief written from the search demand signal{' '}
        <span className="text-foreground font-semibold">{source}</span>. Edit anything below before
        generating.
      </span>
    </div>
  );
}

export function GeneratingPanel({
  selectedId,
  cancelling,
  onCancel,
}: Readonly<{
  selectedId: string | null;
  cancelling: boolean;
  onCancel: (generationId: string) => void;
}>) {
  return (
    <Card
      data-component-id="content-generating-panel"
      className="border-border/70 bg-panel shadow-card rounded-sm border p-6"
    >
      <CardContent className="flex items-center gap-4 p-0">
        <div role="status" aria-label="Generating content" className="flex items-center gap-3">
          <ICONS.spinner className="text-accent size-5 animate-spin" aria-hidden />
          <span className="text-foreground text-sm font-medium">Generating your content…</span>
        </div>
        <div className="ml-auto">
          <Button
            variant="secondary"
            data-component-id="content-cancel-button"
            disabled={!selectedId || cancelling}
            onClick={() => selectedId && onCancel(selectedId)}
            size="sm"
          >
            Cancel
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function GenerationErrorPanel({
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
    <Card
      data-component-id="content-error-panel"
      className="border-danger/30 bg-danger-bg/50 shadow-card rounded-sm border p-6"
    >
      <CardContent className="flex flex-col gap-4 p-0">
        <div role="alert" className="text-danger-text flex items-start gap-2.5 text-sm">
          <ICONS.warning className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span className="leading-relaxed font-medium">
            {mutationError
              ? actionErrorMessage(mutationError)
              : 'Generation failed. You can edit your prompt and try again.'}
          </span>
        </div>
        <div className="flex gap-2.5 pt-1">
          {failedGenerationId ? (
            <Button
              data-component-id="content-retry-button"
              disabled={retrying}
              onClick={() => onTryAgain(failedGenerationId)}
              size="sm"
            >
              <RefreshCw className="mr-1.5 size-3.5" aria-hidden />
              Try again
            </Button>
          ) : null}
          <Button
            variant="secondary"
            data-component-id="content-dismiss-button"
            onClick={onDismiss}
            size="sm"
          >
            <X className="mr-1.5 size-3.5" aria-hidden />
            Dismiss
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}

export function GenerationResult({
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
    <Card
      data-component-id="content-result-card"
      className="border-border/70 bg-panel shadow-card rounded-sm border p-6 sm:p-8"
    >
      <CardContent className="flex flex-col gap-5 p-0">
        {detail.output_truncated ? (
          <div data-component-id="content-truncation-warning">
            <Alert tone="warning">
              The output hit the length limit and may be incomplete. Regenerate or shorten your
              prompt for a complete result.
            </Alert>
          </div>
        ) : null}
        <ResultBody detail={detail} />
        <ResultActions
          detail={detail}
          copied={copied}
          copyLabel={copyLabel}
          regenerating={regenerating}
          feedbackPending={feedbackPending}
          onCopy={onCopy}
          onExport={onExport}
          onRegenerate={onRegenerate}
          onFeedback={onFeedback}
        />
      </CardContent>
    </Card>
  );
}

function ResultBody({ detail }: Readonly<{ detail: ContentGenerationDetail }>) {
  return (
    <>
      <div data-component-id="content-result-body" className="py-2">
        <ContentMarkdown markdown={detail.output_text ?? ''} />
      </div>
      <p data-component-id="content-ai-disclaimer" className="text-muted text-sm leading-relaxed">
        AI-generated {detail.skill_id} — review and revise before publishing. Generated prose never
        becomes a project fact.
      </p>
      <div
        data-component-id="content-result-provenance"
        className="border-border/60 text-muted flex flex-wrap items-center gap-x-5 gap-y-2 border-t pt-4 font-mono text-xs"
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
    </>
  );
}

function ResultActions({
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
  onRegenerate: (id: string) => void;
  onFeedback: (id: string, feedback: 'accepted' | 'rejected') => void;
}>) {
  return (
    <div className="flex flex-wrap items-center gap-3 pt-2">
      <Button
        variant="secondary"
        size="md"
        data-component-id="content-copy-button"
        onClick={onCopy}
        className="shadow-xs"
      >
        {copied ? (
          <Check className="text-success mr-1.5 size-4" aria-hidden />
        ) : (
          <Copy className="mr-1.5 size-4" aria-hidden />
        )}
        {copyLabel}
      </Button>
      <Button
        variant="secondary"
        size="md"
        data-component-id="content-export-button"
        onClick={onExport}
        className="shadow-xs"
      >
        <Download className="mr-1.5 size-4" aria-hidden />
        Export Markdown
      </Button>
      <Button
        variant="secondary"
        size="md"
        data-component-id="content-regenerate-button"
        disabled={regenerating}
        onClick={() => onRegenerate(detail.id)}
        className="shadow-xs"
      >
        <RefreshCw className="mr-1.5 size-4" aria-hidden />
        Regenerate
      </Button>
      <div className="ms-auto flex items-center gap-2">
        {detail.feedback === null ? (
          <>
            <Button
              size="sm"
              disabled={feedbackPending}
              onClick={() => onFeedback(detail.id, 'accepted')}
            >
              Helpful
            </Button>
            <Button
              variant="secondary"
              size="sm"
              disabled={feedbackPending}
              onClick={() => onFeedback(detail.id, 'rejected')}
            >
              Not useful
            </Button>
          </>
        ) : (
          <span className="text-secondary text-sm font-medium">
            {detail.feedback === 'accepted' ? 'Marked helpful' : 'Marked not useful'}
          </span>
        )}
      </div>
    </div>
  );
}
