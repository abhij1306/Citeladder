import { ArrowUp } from 'lucide-react';

import { cn } from '@/lib/utils';

import { LANDING_ICONS } from '../landing-icons';

import { SCRIPT, type Entry, type Phase } from './data';

/** The agent window: a transcript the layers write into, and a live composer. */

function transcriptEntries(reduce: boolean, log: Entry[]) {
  if (!reduce) return log;
  return SCRIPT.flatMap((item, index) => [
    { id: index * 2, layer: index, from: 'layer' as const, text: item.prompt },
    { id: index * 2 + 1, layer: index, from: 'agent' as const, text: item.reply },
  ]);
}

function hasCommittedReply(reduce: boolean, log: Entry[]) {
  return !reduce && (log.at(-1)?.justCommitted ?? false);
}

function shouldShowLiveBubble(
  reduce: boolean,
  phase: Phase,
  reply: string,
  replyCommitted: boolean,
) {
  if (reduce || phase === 'prompt' || replyCommitted) return false;
  return phase !== 'hold' || reply.length > 0;
}

export function ChatWindow({
  active,
  phase,
  typed,
  reply,
  log,
  reduce,
  onHoverChange,
}: Readonly<{
  active: number;
  phase: Phase;
  typed: string;
  reply: string;
  log: Entry[];
  reduce: boolean;
  onHoverChange: (paused: boolean) => void;
}>) {
  const AgentIcon = LANDING_ICONS.agent;
  const step = SCRIPT[active];

  const entries = transcriptEntries(reduce, log);
  const replyCommitted = hasCommittedReply(reduce, log);
  const liveBubble = shouldShowLiveBubble(reduce, phase, reply, replyCommitted);

  return (
    <div
      data-testid="growth-agent-preview"
      onMouseEnter={() => onHoverChange(true)}
      onMouseLeave={() => onHoverChange(false)}
      className="app-type-scale bg-panel shadow-card flex h-full flex-col overflow-hidden rounded-sm"
    >
      <div className="border-border-subtle flex items-center gap-3 border-b px-4 py-3">
        <span className="bg-accent text-inverse flex size-8 shrink-0 items-center justify-center rounded-sm">
          <AgentIcon className="size-4.5" strokeWidth={1.75} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-display text-foreground text-sm font-semibold">Growth Agent</p>
          <p className="text-subtle text-2xs mt-0.5">
            Bounded orchestration · inspectable evidence
          </p>
        </div>
        <span className="text-success-text text-2xs inline-flex items-center gap-1.5 font-semibold">
          <span
            className={cn('bg-success-text size-1.5 rounded-full', !reduce && 'animate-pulse')}
            aria-hidden
          />
          Live
        </span>
      </div>

      {/* Newest exchange sits at the bottom; the mask fades whatever scrolls off
          the top instead of slicing a bubble in half.

          `content-visibility` is deliberately not used and the column is not
          re-keyed: the transcript is bottom-anchored, so when `LOG_LIMIT`
          evicts the oldest entry every surviving bubble shifts up one slot in
          the same commit that mounts the new one. Keying each bubble by its
          stable entry id (never by index) is what keeps those survivors as
          moves rather than unmount/remount pairs — the latter is what read as
          a flicker on every message. */}
      <div
        aria-live="polite"
        className="flex min-h-0 flex-1 flex-col justify-end gap-3 overflow-hidden [mask-image:linear-gradient(to_bottom,transparent,black_14%)] px-4 py-4"
      >
        {entries.map((entry) => (
          <Bubble key={entry.id} entry={entry} />
        ))}

        {/* ONE live bubble across both phases, rendered from a single condition.
            Thinking and replying are two states of the same pending agent
            message, so splitting them into two conditions left a gap: `phase`
            flips to 'reply' but `reply` is still '' until the first interval
            tick, so for that frame neither branch matched and the bubble
            unmounted entirely — the dots disappeared, one blank frame passed,
            then the text mounted. That gap was the "Analyzing → content" blink.
            Keeping it mounted and swapping only its contents removes it. */}
        {liveBubble && (
          <Bubble
            entry={{ id: -1, layer: active, from: 'agent', text: reply }}
            thinking={phase === 'thinking' || reply.length === 0}
          />
        )}
      </div>

      <div className="border-border-subtle bg-background-alt border-t p-3">
        <div className="border-border bg-panel flex items-center gap-3 rounded-lg border px-3.5 py-2.5 shadow-xs">
          <span className="text-subtle text-2xs shrink-0 font-semibold tracking-wide uppercase">
            {reduce ? 'Layers' : step?.name.split(' ')[0]}
          </span>
          <p className="text-secondary min-w-0 flex-1 truncate text-xs">
            {reduce ? 'Three layers stream evidence into the agent continuously.' : typed}
            {!reduce && phase === 'prompt' && (
              <span className="bg-accent ml-0.5 inline-block h-3.5 w-px animate-pulse align-middle" />
            )}
          </p>
          <span
            className={cn(
              'flex size-7 shrink-0 items-center justify-center rounded-md transition-colors duration-300',
              typed || reduce ? 'bg-accent text-inverse' : 'bg-background-alt text-subtle',
            )}
            aria-hidden
          >
            <ArrowUp className="size-3.5" strokeWidth={2.5} />
          </span>
        </div>
      </div>
    </div>
  );
}

function Bubble({ entry, thinking = false }: Readonly<{ entry: Entry; thinking?: boolean }>) {
  const layer = SCRIPT[entry.layer];
  const Icon = LANDING_ICONS[entry.from === 'agent' ? 'agent' : (layer?.icon ?? 'site')];
  const fromAgent = entry.from === 'agent';

  return (
    <div className={cn('flex items-start gap-2.5', !fromAgent && 'flex-row-reverse')}>
      <span
        className={cn(
          'flex size-6 shrink-0 items-center justify-center rounded-md',
          fromAgent ? 'bg-panel text-foreground shadow-xs' : 'bg-accent text-inverse',
        )}
      >
        <Icon className="size-3.5" strokeWidth={2} aria-hidden />
      </span>

      <div
        className={cn(
          'max-w-[82%] rounded-sm px-3.5 py-2.5 text-xs leading-relaxed',
          fromAgent ? 'bg-panel text-secondary shadow-sm' : 'bg-accent text-inverse shadow-sm',
        )}
      >
        {thinking ? (
          <span className="flex items-center gap-1.5 py-0.5">
            {[0, 1, 2].map((dot) => (
              <span
                key={dot}
                className={cn(
                  'size-1.5 animate-pulse rounded-full',
                  fromAgent ? 'bg-border-bold' : 'bg-inverse/70',
                )}
                style={{ animationDelay: `${dot * 160}ms` }}
              />
            ))}
            <span className={cn('ml-1', fromAgent ? 'text-subtle' : 'text-inverse/80')}>
              Analyzing evidence
            </span>
          </span>
        ) : (
          <>
            {!fromAgent && (
              <span className="text-2xs mb-1 block font-semibold opacity-80">{layer?.name}</span>
            )}
            {entry.text}
          </>
        )}
      </div>
    </div>
  );
}
