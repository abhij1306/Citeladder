import { ArrowUp, BookOpen, Check, FileText, Search } from 'lucide-react';

import { cn } from '@/lib/utils';

import {
  PhaseItem,
  PreviewBadge,
  PRIMARY_SURFACE,
  SUPPORTING_SURFACE,
  ScreenHeader,
  type PreviewProps,
  useTypedPreview,
} from './shared';

const CONTENT_PROMPT = 'Create an FAQ brief for our admissions pages.';
const CONTENT_QUESTIONS = [
  'What documents are required?',
  'When are applications reviewed?',
  'Can international students apply?',
] as const;

export function ContentPreview({ phase, reduceMotion }: PreviewProps) {
  const typedPrompt = useTypedPreview(CONTENT_PROMPT, phase === 0, reduceMotion);

  return (
    <div data-preview-layer="content" className="p-4 sm:p-5">
      <ScreenHeader
        icon={<FileText className="size-4" aria-hidden />}
        title="Content Intelligence"
        description="A conversational workspace for grounded briefs, FAQs, drafts, and review."
        action={<PreviewBadge tone="success">Project facts connected</PreviewBadge>}
      />

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.45fr)_minmax(250px,0.75fr)]">
        <section className={cn(PRIMARY_SURFACE, 'flex min-h-[500px] flex-col overflow-hidden')}>
          <div className="border-border flex flex-wrap items-start justify-between gap-3 border-b px-4 py-3">
            <div>
              <div className="flex items-center gap-2">
                <h4 className="text-foreground text-sm font-semibold">Admissions content</h4>
                <PreviewBadge tone={phase >= 3 ? 'success' : 'info'}>
                  {phase >= 3 ? 'Ready for review' : 'Working'}
                </PreviewBadge>
              </div>
              <p className="text-subtle mt-1 text-xs">7 evidence records in context</p>
            </div>
            <span className="text-muted text-xs">Conversation</span>
          </div>
          <div className="flex flex-1 flex-col justify-end gap-3 p-4">
            {phase >= 1 ? (
              <div className="bg-accent text-inverse shadow-card ml-auto max-w-[78%] rounded-lg px-4 py-3 text-[13px] leading-relaxed">
                {CONTENT_PROMPT}
              </div>
            ) : null}

            {phase >= 1 ? (
              <div className="border-border bg-panel shadow-card max-w-[88%] rounded-lg border px-4 py-3">
                <div className="text-accent-text flex items-center gap-2 text-xs font-medium">
                  <Search className="size-3.5" aria-hidden />
                  Read Site Health gaps
                </div>
                <p className="text-secondary mt-2 text-[13px] leading-relaxed">
                  I found three uncovered admissions questions and matched them to persisted project
                  evidence.
                </p>
              </div>
            ) : null}

            {phase >= 2 ? (
              <div className="border-border bg-panel shadow-card max-w-[88%] rounded-lg border px-4 py-3">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-foreground text-sm font-semibold">Admissions FAQ brief</p>
                  <PreviewBadge tone="success">Grounded</PreviewBadge>
                </div>
                <div className="mt-3 grid gap-2">
                  {CONTENT_QUESTIONS.map((question) => (
                    <div key={question} className="text-secondary flex items-center gap-2 text-xs">
                      <Check className="text-success-text size-3.5 shrink-0" aria-hidden />
                      {question}
                    </div>
                  ))}
                </div>
              </div>
            ) : null}

            {phase >= 3 ? (
              <div className="flex max-w-[88%] flex-wrap items-center gap-2">
                <span className="border-border-strong bg-panel text-secondary inline-flex h-8 items-center rounded-sm border px-3 text-xs font-medium shadow-xs">
                  View evidence
                </span>
                <span className="bg-accent text-inverse inline-flex h-8 items-center rounded-sm px-3 text-xs font-medium shadow-xs">
                  Review brief
                </span>
              </div>
            ) : null}
          </div>
          <div className="border-border bg-background-alt border-t p-3">
            <div className="border-border-strong bg-panel text-muted flex h-10 items-center gap-3 rounded-md border px-3 text-[13px] shadow-xs">
              <span className="min-w-0 flex-1 truncate">
                {phase === 0 ? typedPrompt : 'Ask Content Intelligence…'}
                {phase === 0 && typedPrompt.length < CONTENT_PROMPT.length ? (
                  <span
                    className="bg-accent ml-0.5 inline-block h-4 w-px align-middle"
                    aria-hidden
                  />
                ) : null}
              </span>
              <span className="bg-accent text-inverse grid size-7 place-items-center rounded-md">
                <ArrowUp className="size-3.5" aria-hidden />
              </span>
            </div>
          </div>
        </section>

        <section className={cn(SUPPORTING_SURFACE, 'p-4')}>
          <div className="flex items-center gap-2">
            <BookOpen className="text-accent-text size-4" aria-hidden />
            <h4 className="text-foreground text-sm font-semibold">Evidence guardrail</h4>
          </div>
          <div className="mt-4 grid gap-3">
            {[
              ['Project facts', '4 assertions'],
              ['Owned pages', '3 sources'],
              ['Unsupported claims', phase >= 2 ? 'None found' : 'Checking'],
              ['Schema parity', phase >= 3 ? 'Matched' : 'Queued'],
            ].map(([label, value], index) => (
              <PhaseItem
                key={label}
                visible={phase >= Math.min(index, 3)}
                className="flex items-center justify-between gap-3"
              >
                <span className="text-muted text-xs">{label}</span>
                <span className="text-foreground text-xs font-medium">{value}</span>
              </PhaseItem>
            ))}
          </div>
          <div className="border-border mt-4 border-t pt-4">
            <p className="text-subtle text-[11px] leading-relaxed">
              Saving content remains a human decision. The preview stops at review.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
