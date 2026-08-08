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

type Phase = 'prompt' | 'thinking' | 'reply' | 'hold';
type Entry = { id: number; layer: number; from: 'layer' | 'agent'; text: string };

const PROMPT_MS = 22;
const REPLY_MS = 15;
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

  const push = useCallback((layer: number, from: Entry['from'], text: string) => {
    nextId.current += 1;
    const entry = { id: nextId.current, layer, from, text };
    setLog((current) => [...current, entry].slice(-LOG_LIMIT));
  }, []);

  // One timer per phase. Every branch returns its own cleanup, so a click that
  // jumps to another layer mid-sentence cancels the run in flight.
  useEffect(() => {
    if (reduce) return;
    const step = SCRIPT[active];
    if (!step) return;

    if (phase === 'prompt') {
      let index = 0;
      const id = window.setInterval(() => {
        index += 1;
        setTyped(step.prompt.slice(0, index));
        if (index >= step.prompt.length) {
          window.clearInterval(id);
          window.setTimeout(() => {
            setTyped('');
            push(active, 'layer', step.prompt);
            setPhase('thinking');
          }, 480);
        }
      }, PROMPT_MS);
      return () => window.clearInterval(id);
    }

    if (phase === 'thinking') {
      const id = window.setTimeout(() => setPhase('reply'), THINKING_MS);
      return () => window.clearTimeout(id);
    }

    if (phase === 'reply') {
      let index = 0;
      const id = window.setInterval(() => {
        index += 1;
        setReply(step.reply.slice(0, index));
        if (index >= step.reply.length) {
          window.clearInterval(id);
          setPhase('hold');
        }
      }, REPLY_MS);
      return () => window.clearInterval(id);
    }

    // hold — the one place the cycle waits, and the one place hover pauses it.
    if (paused) return;
    const id = window.setTimeout(() => {
      setReply('');
      push(active, 'agent', step.reply);
      setActive((current) => (current + 1) % SCRIPT.length);
      setPhase('prompt');
    }, HOLD_MS);
    return () => window.clearTimeout(id);
  }, [active, phase, paused, push, reduce]);

  const select = useCallback((index: number) => {
    setActive(index);
    setPhase('prompt');
    setTyped('');
    setReply('');
  }, []);

  return (
    <div className="relative w-full xl:aspect-[2/1]">
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
      className={cn(
        'focus-visible:ring-accent/60 group flex w-full items-start gap-3.5 rounded-xl px-4 py-5 text-left transition-colors duration-300 focus-visible:ring-2 focus-visible:outline-none xl:my-auto',
        active ? 'bg-accent-subtle/60' : 'hover:bg-background-alt/70',
      )}
    >
      <span
        className={cn(
          'flex size-9 shrink-0 items-center justify-center rounded-lg transition-colors duration-300',
          active
            ? 'bg-accent text-inverse shadow-xs'
            : 'bg-background-alt text-subtle group-hover:text-accent-text',
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
 * The viewBox is 192x600 and the element is 16% x 100% of a 1200x600 stage, so
 * the ratio matches exactly and nothing is stretched — the dots stay round. The
 * `pipeline-stream` class is what globals.css uses to hide SMIL dots under
 * `prefers-reduced-motion`.
 */
function Bus({ active, reduce }: Readonly<{ active: number; reduce: boolean }>) {
  const routes = [
    'M 0 100 H 60 A 24 24 0 0 1 84 124 V 276 A 24 24 0 0 0 108 300 H 186',
    'M 0 300 H 186',
    'M 0 500 H 60 A 24 24 0 0 0 84 476 V 324 A 24 24 0 0 1 108 300 H 186',
  ];
  // Constant dot speed, so the bent routes simply take longer to arrive.
  const durations = [3, 1.55, 3];

  return (
    <svg
      aria-hidden
      viewBox="0 0 192 600"
      fill="none"
      className="pipeline-stream absolute inset-y-0 left-[30%] hidden h-full w-[16%] xl:block"
    >
      {routes.map((d, index) => (
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
                dur={`${durations[index]}s`}
                begin={`${(slot * (durations[index] ?? 3)) / 3}s`}
                repeatCount="indefinite"
              />
            </circle>
          ))}
        </g>
      ))}

      {/* The merged trunk, drawn solid over the dashed routes it carries. */}
      <path d="M 108 300 H 186" className="stroke-accent" strokeWidth="2" />
      <polygon points="182,292 196,300 182,308" className="fill-accent" />
      <circle
        cx="108"
        cy="300"
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

  return (
    <div
      onMouseEnter={() => onHoverChange(true)}
      onMouseLeave={() => onHoverChange(false)}
      className="bg-panel border-border shadow-elevated flex h-full flex-col overflow-hidden rounded-2xl border"
    >
      <div className="border-border-subtle flex items-center gap-3 border-b px-5 py-3.5">
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
          the top instead of slicing a bubble in half. */}
      <div
        aria-live="polite"
        className="flex min-h-0 flex-1 flex-col justify-end gap-3 overflow-hidden [mask-image:linear-gradient(to_bottom,transparent,black_14%)] px-5 py-4"
      >
        {entries.map((entry) => (
          <Bubble key={entry.id} entry={entry} />
        ))}

        {!reduce && phase === 'thinking' && (
          <Bubble entry={{ id: -1, layer: active, from: 'agent', text: '' }} thinking />
        )}
        {!reduce && phase !== 'thinking' && reply && (
          <Bubble entry={{ id: -2, layer: active, from: 'agent', text: reply }} caret />
        )}
      </div>

      <div className="border-border-subtle bg-background-alt/60 border-t px-5 py-4">
        <div className="border-border bg-panel flex items-center gap-3 rounded-lg border px-3.5 py-2.5">
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

function Bubble({
  entry,
  thinking = false,
  caret = false,
}: Readonly<{ entry: Entry; thinking?: boolean; caret?: boolean }>) {
  const layer = SCRIPT[entry.layer];
  const Icon = LANDING_ICONS[entry.from === 'agent' ? 'agent' : (layer?.icon ?? 'site')];
  const fromAgent = entry.from === 'agent';

  return (
    <div className={cn('flex items-start gap-2.5', fromAgent ? '' : 'flex-row-reverse')}>
      <span
        className={cn(
          'flex size-6 shrink-0 items-center justify-center rounded-md',
          fromAgent ? 'bg-accent text-inverse' : 'bg-accent-subtle text-accent-text',
        )}
      >
        <Icon className="size-3.5" strokeWidth={2} aria-hidden />
      </span>

      <div
        className={cn(
          'max-w-[82%] rounded-xl px-3.5 py-2.5 text-xs leading-relaxed',
          fromAgent ? 'bg-background-alt text-secondary' : 'bg-accent text-inverse',
        )}
      >
        {thinking ? (
          <span className="flex items-center gap-1.5 py-0.5">
            {[0, 1, 2].map((dot) => (
              <span
                key={dot}
                className="bg-subtle size-1.5 animate-pulse rounded-full"
                style={{ animationDelay: `${dot * 160}ms` }}
              />
            ))}
            <span className="text-subtle ml-1">Analyzing evidence</span>
          </span>
        ) : (
          <>
            {!fromAgent && (
              <span className="text-2xs mb-1 block font-semibold opacity-80">{layer?.name}</span>
            )}
            {entry.text}
            {caret && (
              <span className="bg-secondary ml-0.5 inline-block h-3 w-px animate-pulse align-middle" />
            )}
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
