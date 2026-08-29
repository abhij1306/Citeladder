import { Check, Copy, Download, RefreshCw } from 'lucide-react';
import Link from 'next/link';

import { Alert } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { Card, CardContent } from '@/components/ui/card';
import type { ContentFeedbackReason, ContentGenerationDetail } from '@/lib/api/types';
import { ContentMarkdown } from '@/lib/content/markdown';

export function GenerationResult({
  detail,
  copied,
  copyLabel,
  regenerating,
  feedbackPending,
  reasonOpen,
  onCopy,
  onExport,
  onRegenerate,
  onFeedback,
  onRejectClick,
}: Readonly<{
  detail: ContentGenerationDetail;
  copied: boolean;
  copyLabel: string;
  regenerating: boolean;
  feedbackPending: boolean;
  reasonOpen: boolean;
  onCopy: () => void;
  onExport: () => void;
  onRegenerate: (generationId: string) => void;
  onFeedback: (
    generationId: string,
    feedback: 'accepted' | 'rejected',
    reason?: ContentFeedbackReason,
  ) => void;
  onRejectClick: () => void;
}>) {
  return (
    <Card
      data-component-id="content-result-card"
      className="border-border bg-panel shadow-card min-w-0 rounded-sm border p-[var(--card-padding)]"
    >
      <CardContent className="flex flex-col gap-[var(--workspace-gap)] p-0">
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
          onRejectClick={onRejectClick}
        />
        {reasonOpen && detail.feedback === null ? (
          <FeedbackReasonPicker
            disabled={feedbackPending}
            onSelect={(reason) => onFeedback(detail.id, 'rejected', reason)}
          />
        ) : null}
      </CardContent>
    </Card>
  );
}

function ResultBody({ detail }: Readonly<{ detail: ContentGenerationDetail }>) {
  return (
    <>
      <div data-component-id="content-result-body" className="min-w-0 py-2">
        <ContentMarkdown markdown={detail.output_text ?? ''} />
      </div>
      <p data-component-id="content-ai-disclaimer" className="text-muted text-sm leading-relaxed">
        AI-generated {detail.skill_id} — review and revise before publishing. Generated prose never
        becomes a project fact.
      </p>
      <div
        data-component-id="content-result-provenance"
        className="border-border text-muted flex flex-wrap items-center gap-x-2 border-t pt-4 text-xs"
      >
        {groundedWithLabel(detail)}
      </div>
    </>
  );
}

/** One quiet line: what this draft was actually grounded with. */
function groundedWithLabel(detail: ContentGenerationDetail): string {
  const pages = detail.grounding_summary.crawl_page_count;
  if (pages > 0) {
    return `Grounded with: website crawl · ${pages} ${pages === 1 ? 'page' : 'pages'}`;
  }
  if (detail.grounding_summary.brand_fields.length > 0) {
    return 'Grounded with: brand context';
  }
  return 'Grounded with: no site evidence available';
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
  onRejectClick,
}: Readonly<{
  detail: ContentGenerationDetail;
  copied: boolean;
  copyLabel: string;
  regenerating: boolean;
  feedbackPending: boolean;
  onCopy: () => void;
  onExport: () => void;
  onRegenerate: (id: string) => void;
  onFeedback: (
    id: string,
    feedback: 'accepted' | 'rejected',
    reason?: ContentFeedbackReason,
  ) => void;
  onRejectClick: () => void;
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
      {detail.opportunity_id ? (
        <Button asChild variant="secondary" size="md">
          <Link href={`/opportunities?opportunity_id=${detail.opportunity_id}`}>
            Return to opportunity
          </Link>
        </Button>
      ) : null}
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
              data-component-id="content-reject-button"
              disabled={feedbackPending}
              onClick={onRejectClick}
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

const FEEDBACK_REASONS: ReadonlyArray<{ value: ContentFeedbackReason; label: string }> = [
  { value: 'too_generic', label: 'Too generic' },
  { value: 'wrong_tone', label: 'Wrong tone' },
  { value: 'missed_topic', label: 'Missed the topic' },
  { value: 'incorrect_facts', label: 'Incorrect facts' },
  { value: 'other', label: 'Other' },
];

/**
 * Why a draft missed. Shown only after "Not useful" is pressed, so the
 * common path stays a single click and the reason never becomes a required
 * field standing between the user and dismissing a bad result.
 */
function FeedbackReasonPicker({
  disabled,
  onSelect,
}: Readonly<{
  disabled: boolean;
  onSelect: (reason: ContentFeedbackReason) => void;
}>) {
  return (
    <div
      data-component-id="content-feedback-reasons"
      className="border-border flex flex-wrap items-center gap-2 border-t pt-4"
    >
      <span className="text-secondary text-sm font-medium">Why?</span>
      {FEEDBACK_REASONS.map((reason) => (
        <button
          key={reason.value}
          type="button"
          disabled={disabled}
          onClick={() => onSelect(reason.value)}
          className="border-border text-secondary hover:border-accent-border hover:text-accent-text focus-ring disabled:text-muted rounded-full border px-3 py-1.5 text-xs transition-colors disabled:cursor-not-allowed"
        >
          {reason.label}
        </button>
      ))}
    </div>
  );
}
