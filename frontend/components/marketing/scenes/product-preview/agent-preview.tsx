import {
  ArrowUp,
  Check,
  CheckCircle2,
  ListChecks,
  MessageSquareText,
  RefreshCw,
  ShieldCheck,
  Sparkles,
} from 'lucide-react';

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

const AGENT_PROMPT = 'What should we improve next?';
const AGENT_TOOL_STEPS = [
  ['Read Site findings', '12 evidence-backed gaps'],
  ['Read Demand signals', 'GSC, GA4, AI Visibility'],
  ['Prioritize next steps', 'Deterministic priority order'],
  ['Request review', 'No external action taken'],
] as const;

export function AgentPreview({ phase, reduceMotion }: PreviewProps) {
  const typedPrompt = useTypedPreview(AGENT_PROMPT, phase === 0, reduceMotion);

  return (
    <div data-preview-layer="agent" className="p-4 sm:p-5">
      <ScreenHeader
        icon={<Sparkles className="size-4" aria-hidden />}
        title="Growth Agent"
        description="Bounded orchestration over typed Site, Content, and Demand tools."
        action={
          <PreviewBadge tone={phase >= 3 ? 'success' : 'info'}>
            {phase >= 3 ? 'Roadmap ready' : 'Working'}
          </PreviewBadge>
        }
      />

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1.35fr)_minmax(270px,0.75fr)]">
        <section className={cn(PRIMARY_SURFACE, 'flex min-h-[390px] flex-col overflow-hidden')}>
          <div className="border-border flex items-center gap-3 border-b px-4 py-3">
            <span className="bg-accent-soft text-accent-text grid size-7 place-items-center rounded-md">
              <MessageSquareText className="size-3.5" />
            </span>
            <div>
              <h4 className="text-foreground text-sm font-semibold">Growth planning</h4>
              <p className="text-subtle mt-0.5 text-[11px]">Selective context · project scoped</p>
            </div>
          </div>
          <div className="flex-1 p-4">
            {phase >= 1 ? (
              <div className="bg-accent text-inverse shadow-card mb-4 ml-auto max-w-[78%] rounded-lg px-4 py-3 text-[13px] leading-relaxed">
                {AGENT_PROMPT}
              </div>
            ) : null}
            <div className="grid gap-2.5">
              {AGENT_TOOL_STEPS.map(([label, detail], index) => (
                <PhaseItem key={label} visible={phase >= index} className="flex items-center gap-3">
                  <span
                    className={cn(
                      'grid size-6 shrink-0 place-items-center rounded-full',
                      phase > index || phase === 3
                        ? 'bg-success-bg text-success-text'
                        : 'bg-info-bg text-info-text',
                    )}
                  >
                    {phase > index || phase === 3 ? (
                      <Check className="size-3.5" />
                    ) : (
                      <RefreshCw className="size-3 animate-spin" />
                    )}
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-secondary text-xs font-medium">{label}</p>
                    <p className="text-subtle mt-0.5 truncate text-[11px]">{detail}</p>
                  </div>
                  <span className="text-subtle text-[11px] tabular-nums">
                    {phase > index ? `${index + 1}s` : ''}
                  </span>
                </PhaseItem>
              ))}
            </div>

            <PhaseItem
              visible={phase >= 3}
              className="bg-background-alt border-border shadow-card mt-4 rounded-lg border p-4"
            >
              <div className="flex items-center gap-2">
                <CheckCircle2 className="text-success-text size-4" />
                <p className="text-foreground text-sm font-semibold">Recommended next action</p>
              </div>
              <p className="text-secondary mt-2 text-[13px] leading-relaxed">
                Close the admissions question gap with an evidence-backed FAQ brief, then verify it
                after publication.
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                <PreviewBadge>Site evidence</PreviewBadge>
                <PreviewBadge>Demand signal</PreviewBadge>
                <PreviewBadge>Pack rule</PreviewBadge>
              </div>
            </PhaseItem>
          </div>
          <div className="border-border bg-background-alt border-t p-3">
            <div className="border-border-strong bg-panel text-muted flex h-10 items-center gap-3 rounded-md border px-3 text-[13px] shadow-xs">
              <span className="min-w-0 flex-1 truncate">
                {phase === 0 ? typedPrompt : 'Ask Growth Agent…'}
                {phase === 0 && typedPrompt.length < AGENT_PROMPT.length ? (
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
          <div className="flex items-center justify-between gap-3">
            <h4 className="text-foreground text-sm font-semibold">Priority roadmap</h4>
            <ListChecks className="text-muted size-4" />
          </div>
          <div className="mt-3 grid gap-2.5">
            {[
              ['Admissions FAQ coverage', 'Site + Demand'],
              ['Program proof gaps', 'Site'],
              ['Citation-ready comparisons', 'Demand + Content'],
            ].map(([title, source], index) => (
              <PhaseItem
                key={title}
                visible={phase >= Math.min(index + 1, 3)}
                className="bg-panel border-border rounded-md border p-3 shadow-xs"
              >
                <div className="flex items-start gap-3">
                  <span className="text-accent-text text-xs font-semibold tabular-nums">
                    {index + 1}
                  </span>
                  <div className="min-w-0">
                    <p className="text-secondary text-xs font-medium">{title}</p>
                    <p className="text-subtle mt-1 text-[11px]">{source} · evidence linked</p>
                  </div>
                </div>
              </PhaseItem>
            ))}
          </div>
          <PhaseItem visible={phase >= 3} className="mt-4 grid grid-cols-2 gap-2">
            <span className="border-border-strong bg-panel text-secondary inline-flex h-8 items-center justify-center rounded-sm border text-xs font-medium shadow-xs">
              View evidence
            </span>
            <span className="bg-accent text-inverse inline-flex h-8 items-center justify-center rounded-sm text-xs font-medium shadow-xs">
              Review brief
            </span>
          </PhaseItem>
          <div className="border-border mt-4 flex items-start gap-2 border-t pt-3">
            <ShieldCheck className="text-success-text mt-0.5 size-3.5 shrink-0" />
            <p className="text-subtle text-[11px] leading-relaxed">
              The agent explains and prepares. You decide when content is saved or an audit runs.
            </p>
          </div>
        </section>
      </div>
    </div>
  );
}
