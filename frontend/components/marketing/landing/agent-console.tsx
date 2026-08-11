'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { ArrowUp, Check } from 'lucide-react';
import { useReducedMotion } from 'motion/react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';
import { cn } from '@/lib/utils';

import { LANDING_ICONS } from './landing-icons';

/**
 * The three intelligence layers prompt the Growth Agent, and the agent answers.
 * Each exchange is written from that layer's own capability list in
 * `LANDING_CONTENT.platform.modules` — nothing here claims a capability the
 * product page does not already state, and no exchange invents a metric.
 */
const SCRIPT = [
  {
    icon: 'site' as const,
    name: 'Site Intelligence',
    role: 'Crawls and classifies every page, then re-verifies after changes.',
    prompt: 'Recrawl complete — gap rules flagged uncovered questions on the service pages.',
    reply: 'Queuing an evidence-grounded brief for each gap. Saving a draft stays your decision.',
  },
  {
    icon: 'content' as const,
    name: 'Content Intelligence',
    role: 'Turns detected gaps into briefs, schema, and verified drafts.',
    prompt: 'Draft checked against project facts — no unsupported claims. Ready for schema.',
    reply: 'Generating FAQPage JSON-LD, then scheduling a post-publication verification pass.',
  },
  {
    icon: 'demand' as const,
    name: 'Demand Intelligence',
    role: 'Unifies Search Console, GA4, and AI visibility signals.',
    prompt: 'Search Console, GA4, and AI visibility are unified for this cluster.',
    reply: 'Reprioritizing the queue by actual impact. Every step lands in the audit log.',
  },
];

type Phase = 'prompt' | 'thinking' | 'hold';
type Entry = {
  id: number;
  layer: number;
  from: 'layer' | 'agent';
  text: string;
  /**
   * Set on the agent entry that was just committed from the live `reply`
   * bubble. The live bubble is suppressed against THIS flag rather than by
   * comparing the log tail to `SCRIPT[active].reply`: `push` and `setActive`
   * land in the same batch, so by the time that comparison ran `active` had
   * already advanced and it never matched — leaving the committed entry and
   * the live bubble both on screen for a frame. That double-render was the
   * flicker at the end of every exchange.
   */
  justCommitted?: boolean;
};

const PROMPT_MS = 22;
const THINKING_MS = 1000;
const HOLD_MS = 2200;
/** Only the newest exchange and a half stay on screen, so the window never grows. */
const LOG_LIMIT = 3;

export function AgentConsole() {
  const reduce = useReducedMotion() ?? false;

  const [active, setActive] = useState(0);
  const [phase, setPhase] = useState<Phase>('prompt');
  const [typed, setTyped] = useState('');
  const [reply, setReply] = useState('');
  const [log, setLog] = useState<Entry[]>([]);
  const [paused, setPaused] = useState(false);
  const nextId = useRef(0);
  /**
   * How far the current sentence has typed. This is a ref, not a local in the
   * effect: `paused` is a dependency, so hovering the console re-runs the
   * effect mid-sentence, and a local counter would reset to 0 and visibly
   * retype from the first character. Cleared whenever a run genuinely starts
   * over (a new layer, or a new phase).
   */
  const cursor = useRef(0);

  const push = useCallback(
    (layer: number, from: Entry['from'], text: string, justCommitted = false) => {
      nextId.current += 1;
      const entry = { id: nextId.current, layer, from, text, justCommitted };
      setLog((current) =>
        // The previous commit flag is cleared as the next entry lands, so only
        // ever one entry carries it.
        [
          ...current.map((item) => (item.justCommitted ? { ...item, justCommitted: false } : item)),
          entry,
        ].slice(-LOG_LIMIT),
      );
    },
    [],
  );

  /**
   * A new sentence starts at character zero. Keyed on layer and phase only —
   * deliberately NOT on `paused`, which is the whole point: hovering must not
   * rewind the sentence being typed. Runs before the typing effect below, so
   * that effect always sees a cursor belonging to the phase it is starting.
   */
  useEffect(() => {
    cursor.current = 0;
  }, [active, phase]);

  // One timer per phase. Every branch returns its own cleanup, so a click that
  // jumps to another layer mid-sentence cancels the run in flight.
  useEffect(() => {
    if (reduce) return;
    const step = SCRIPT[active];
    if (!step) return;

    // The trailing timer of the prompt phase, cleared alongside its interval.
    let settle: number | undefined;

    if (phase === 'prompt') {
      // Resume where the last run left off rather than restarting the sentence.
      const id = window.setInterval(() => {
        cursor.current += 1;
        setTyped(step.prompt.slice(0, cursor.current));
        if (cursor.current >= step.prompt.length) {
          window.clearInterval(id);
          // Captured so the cleanup can cancel it: left dangling, this fires
          // after a layer switch and pushes a duplicate bubble into the new run.
          settle = window.setTimeout(() => {
            setTyped('');
            push(active, 'layer', step.prompt);
            setPhase('thinking');
          }, 480);
        }
      }, PROMPT_MS);
      return () => {
        window.clearInterval(id);
        if (settle !== undefined) window.clearTimeout(settle);
      };
    }

    if (phase === 'thinking') {
      const id = window.setTimeout(() => {
        setReply(step.reply);
        setPhase('hold');
      }, THINKING_MS);
      return () => window.clearTimeout(id);
    }
  }, [active, phase, push, reduce]);

  useEffect(() => {
    if (reduce || paused || phase !== 'hold') return;
    const step = SCRIPT[active];
    if (!step) return;

    // Hold is the only phase hover may pause. Keeping it in its own effect
    // prevents hover changes from restarting prompt or thinking timers.
    const id = window.setTimeout(() => {
      // Commit and clear in one batch. `push` appends the finished reply while
      // `setReply('')` retires the live bubble; the render below suppresses the
      // live bubble on this tick so the text never renders twice or blinks out.
      push(active, 'agent', step.reply, true);
      setReply('');
      setActive((current) => (current + 1) % SCRIPT.length);
      setPhase('prompt');
    }, HOLD_MS);
    return () => window.clearTimeout(id);
  }, [active, phase, paused, push, reduce]);

  const select = useCallback((index: number) => {
    // Reset here too: clicking the row that is already typing changes neither
    // `active` nor `phase`, so the reset effect above would not re-run.
    cursor.current = 0;
    setActive(index);
    setPhase('prompt');
    setTyped('');
    setReply('');
  }, []);

  // 5:2 rather than 2:1 — the transcript is bottom-anchored, so any height
  // beyond what the messages need became dead space at the top of the stage.
  return (
    <div className="relative w-full xl:aspect-[5/2]">
      <Bus active={active} reduce={reduce} />

      <div className="grid gap-8 xl:block xl:gap-0">
        <div className="divide-border-subtle grid divide-y xl:absolute xl:inset-y-0 xl:left-0 xl:w-[30%] xl:grid-rows-3 xl:divide-y-0">
          {SCRIPT.map((step, index) => (
            <LayerRow
              key={step.name}
              step={step}
              index={index}
              active={index === active}
              reduce={reduce}
              onSelect={select}
            />
          ))}
        </div>

        <div className="xl:absolute xl:top-[4%] xl:left-[46%] xl:h-[92%] xl:w-[54%]">
          <ChatWindow
            active={active}
            phase={phase}
            typed={typed}
            reply={reply}
            log={log}
            reduce={reduce}
            onHoverChange={setPaused}
          />
        </div>
      </div>
    </div>
  );
}

/**
 * A layer, as a row rather than a card: an icon, a name, what it emits. The
 * active row is carried by an accent wash and its filled mark, never a border.
 */
function LayerRow({
  step,
  index,
  active,
  reduce,
  onSelect,
}: Readonly<{
  step: (typeof SCRIPT)[number];
  index: number;
  active: boolean;
  reduce: boolean;
  onSelect: (index: number) => void;
}>) {
  const Icon = LANDING_ICONS[step.icon];

  return (
    <button
      type="button"
      onClick={() => onSelect(index)}
      aria-pressed={active}
      /* Each row is a real card, so the copy sits ON a surface rather than
         floating on the section background. Resting state is the sunken grey
         well; the selected row lifts to a white panel with the accent border —
         the tonal jump is what makes "which layer is streaming" readable at a
         glance, rather than relying on the status text alone. */
      className={cn(
        'focus-visible:ring-accent/60 group flex w-full items-start gap-3.5 rounded-xl border px-4 py-5 text-left transition-[background-color,border-color,box-shadow] duration-300 focus-visible:ring-2 focus-visible:outline-none xl:my-auto',
        active
          ? 'bg-panel border-accent-border shadow-card'
          : 'bg-well border-border-subtle hover:bg-panel hover:border-border hover:shadow-xs',
      )}
    >
      <span
        className={cn(
          'flex size-9 shrink-0 items-center justify-center rounded-lg transition-colors duration-300',
          active
            ? 'bg-accent text-inverse shadow-xs'
            : // On the grey resting card the chip needs a white fill to read as
              // a chip at all; `bg-background-alt` would blend into the card.
              'bg-panel border-border-subtle text-subtle group-hover:text-accent-text border',
        )}
      >
        <Icon className="size-4.5" strokeWidth={1.75} aria-hidden />
      </span>

      <span className="min-w-0 flex-1">
        <span
          className={cn(
            'font-display block text-sm font-semibold transition-colors duration-300',
            active ? 'text-accent-text' : 'text-foreground',
          )}
        >
          {step.name}
        </span>
        <span className="text-muted mt-1 block text-xs leading-relaxed">{step.role}</span>
        <span
          className={cn(
            'text-2xs mt-2 inline-flex items-center gap-1.5 font-semibold transition-opacity duration-300',
            active ? 'text-accent-text opacity-100' : 'text-subtle opacity-0 xl:opacity-100',
          )}
        >
          <span
            className={cn(
              'size-1.5 rounded-full',
              active ? 'bg-accent' : 'bg-border-strong',
              active && !reduce && 'animate-pulse',
            )}
            aria-hidden
          />
          {active ? 'Streaming to agent' : 'Idle'}
        </span>
      </span>
    </button>
  );
}

/**
 * The converging bus. Three straight runs leave the rows, the outer two bend
 * into the centre line, and one trunk carries the merged stream into the agent.
 *
 * The viewBox is 192x480 and the element is 16% x 100% of a 1200x480 stage (the
 * 5:2 ratio above), so the ratio matches exactly and nothing is stretched — the
 * dots stay round. Every y here is the former 600-tall geometry scaled by 0.8;
 * the corner radius stays 24 because a scaled arc would no longer be circular.
 * The `pipeline-stream` class is what globals.css uses to hide SMIL dots under
 * `prefers-reduced-motion`.
 */
const BUS_ROUTES = [
  'M 0 80 H 60 A 24 24 0 0 1 84 104 V 216 A 24 24 0 0 0 108 240 H 186',
  'M 0 240 H 186',
  'M 0 400 H 60 A 24 24 0 0 0 84 376 V 264 A 24 24 0 0 1 108 240 H 186',
] as const;
// Constant dot speed, so the bent routes simply take longer to arrive.
const BUS_DURATIONS = [3, 1.55, 3] as const;

function Bus({ active, reduce }: Readonly<{ active: number; reduce: boolean }>) {
  return (
    <svg
      aria-hidden
      viewBox="0 0 192 480"
      fill="none"
      className="pipeline-stream absolute inset-y-0 left-[30%] hidden h-full w-[16%] xl:block"
    >
      {BUS_ROUTES.map((d, index) => (
        <g key={d}>
          <path
            d={d}
            strokeWidth={index === active ? 2 : 1.25}
            strokeDasharray="4 5"
            className={cn(
              'transition-[stroke,stroke-width] duration-500',
              index === active ? 'stroke-accent' : 'stroke-border-strong',
            )}
          />
          {[0, 1, 2].map((slot) => (
            <circle
              key={slot}
              r={index === active ? 3 : 2}
              className={cn(
                'fill-accent transition-opacity duration-500',
                index === active ? 'opacity-100' : 'opacity-30',
              )}
            >
              <animateMotion
                path={d}
                dur={`${BUS_DURATIONS[index]}s`}
                begin={`${(slot * (BUS_DURATIONS[index] ?? 3)) / 3}s`}
                repeatCount="indefinite"
              />
            </circle>
          ))}
        </g>
      ))}

      {/* The merged trunk, drawn solid over the dashed routes it carries. Its
          y is the stage centre — 240 in the 480-tall box, matching the routes. */}
      <path d="M 108 240 H 186" className="stroke-accent" strokeWidth="2" />
      <polygon points="182,232 196,240 182,248" className="fill-accent" />
      <circle
        cx="108"
        cy="240"
        r="4"
        className={cn('fill-accent', !reduce && 'animate-pulse')}
        aria-hidden
      />
    </svg>
  );
}

/** The agent window: a transcript the layers write into, and a live composer. */
function ChatWindow({
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

  // Reduced motion gets the whole conversation at once, with no timers running.
  const entries: Entry[] = reduce
    ? SCRIPT.flatMap((item, index) => [
        { id: index * 2, layer: index, from: 'layer' as const, text: item.prompt },
        { id: index * 2 + 1, layer: index, from: 'agent' as const, text: item.reply },
      ])
    : log;

  /**
   * True on the tick where the complete reply has been appended to the log but
   * the live `reply` string has not yet cleared. Without this the same sentence
   * renders as two bubbles under different keys, so React unmounts one and
   * mounts the other — the text visibly blinks at the end of every exchange.
   */
  const replyCommitted = !reduce && (log.at(-1)?.justCommitted ?? false);

  /**
   * The pending agent message is on screen from the moment thinking starts
   * until the complete reply is committed to the log — one continuous mount,
   * with no frame in between where it is absent. The assistant response is
   * inserted whole after thinking; only the user-side composer types.
   */
  const liveBubble =
    !reduce && phase !== 'prompt' && !replyCommitted && !(phase === 'hold' && reply.length === 0);

  return (
    <div
      data-testid="growth-agent-preview"
      onMouseEnter={() => onHoverChange(true)}
      onMouseLeave={() => onHoverChange(false)}
      className="app-type-scale bg-panel shadow-card flex h-full flex-col overflow-hidden rounded-xl"
    >
      <div className="border-border-subtle flex items-center gap-3 border-b px-4 py-3">
        <span className="bg-accent text-inverse flex size-8 shrink-0 items-center justify-center rounded-lg">
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
          'max-w-[82%] rounded-xl px-3.5 py-2.5 text-xs leading-relaxed',
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

/** The verified guarantees the agent operates under, shown beneath the stage. */
export function AgentGuarantees() {
  const agent = LANDING_CONTENT.platform.modules.find((module) => module.icon === 'agent');
  if (!agent) return null;

  return (
    <ul className="mx-auto grid w-full max-w-5xl gap-x-8 gap-y-3 sm:grid-cols-2 lg:grid-cols-4">
      {agent.features.map((feature) => (
        <li key={feature} className="text-secondary flex items-start gap-2 text-xs leading-snug">
          <Check className="text-accent-text mt-0.5 size-3.5 shrink-0 stroke-[2.5]" aria-hidden />
          <span>{feature}</span>
        </li>
      ))}
    </ul>
  );
}
