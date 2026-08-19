'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { Check } from 'lucide-react';
import { useReducedMotion } from 'motion/react';

import { LANDING_CONTENT } from '@/lib/marketing-content/landing';

import { Bus } from './agent-console/bus';
import { ChatWindow } from './agent-console/chat-window';
import {
  HOLD_MS,
  LOG_LIMIT,
  PROMPT_MS,
  SCRIPT,
  THINKING_MS,
  type Entry,
  type Phase,
} from './agent-console/data';
import { LayerRow } from './agent-console/layer-row';

export function AgentConsole() {
  const reduce = useReducedMotion() ?? false;
  const [active, setActive] = useState(0);
  const [phase, setPhase] = useState<Phase>('prompt');
  const [typed, setTyped] = useState('');
  const [reply, setReply] = useState('');
  const [log, setLog] = useState<Entry[]>([]);
  const [paused, setPaused] = useState(false);
  const nextId = useRef(0);
  const cursor = useRef(0);

  const push = useCallback(
    (layer: number, from: Entry['from'], text: string, justCommitted = false) => {
      nextId.current += 1;
      const entry = { id: nextId.current, layer, from, text, justCommitted };
      setLog((current) =>
        [
          ...current.map((item) => (item.justCommitted ? { ...item, justCommitted: false } : item)),
          entry,
        ].slice(-LOG_LIMIT),
      );
    },
    [],
  );

  useEffect(() => {
    cursor.current = 0;
  }, [active, phase]);

  useEffect(() => {
    if (reduce) return;
    const step = SCRIPT[active];
    if (!step) return;
    let settle: number | undefined;

    if (phase === 'prompt') {
      const id = window.setInterval(() => {
        cursor.current += 1;
        setTyped(step.prompt.slice(0, cursor.current));
        if (cursor.current >= step.prompt.length) {
          window.clearInterval(id);
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
    const id = window.setTimeout(() => {
      push(active, 'agent', step.reply, true);
      setReply('');
      setActive((current) => (current + 1) % SCRIPT.length);
      setPhase('prompt');
    }, HOLD_MS);
    return () => window.clearTimeout(id);
  }, [active, phase, paused, push, reduce]);

  const select = useCallback((index: number) => {
    cursor.current = 0;
    setActive(index);
    setPhase('prompt');
    setTyped('');
    setReply('');
  }, []);

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
