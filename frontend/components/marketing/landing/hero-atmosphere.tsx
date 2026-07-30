'use client';

import { m, useReducedMotion } from 'motion/react';

const EASE_IN_OUT = [0.45, 0, 0.55, 1] as const;

const FIELDS = [
  {
    className: 'bg-mkt-sky -top-20 -right-20 size-96',
    x: 48,
    y: -28,
    opacity: [0.3, 0.48],
    duration: 12,
  },
  {
    className: 'bg-mkt-evidence-soft top-8 -left-16 size-96',
    x: -40,
    y: 24,
    opacity: [0.28, 0.44],
    duration: 14,
  },
  {
    className: 'bg-mkt-amber-soft -bottom-20 left-1/3 size-96',
    x: 36,
    y: -24,
    opacity: [0.3, 0.46],
    duration: 13,
  },
];

export function HeroAtmosphere() {
  const reduceMotion = useReducedMotion();

  return (
    <div aria-hidden className="pointer-events-none absolute inset-0 overflow-hidden">
      {FIELDS.map((field) => (
        <m.span
          key={field.className}
          className={`${field.className} absolute rounded-full blur-2xl`}
          // Without this the reduced-motion branch renders at full opacity —
          // i.e. a HEAVIER wash than anyone else sees, which is backwards. The
          // animated branch starts on the same value, so nothing else moves.
          initial={{ opacity: field.opacity[0] }}
          animate={
            reduceMotion
              ? undefined
              : { x: [0, field.x], y: [0, field.y], scale: [1, 1.08], opacity: field.opacity }
          }
          transition={{
            duration: field.duration,
            ease: EASE_IN_OUT,
            repeat: Number.POSITIVE_INFINITY,
            repeatType: 'mirror',
          }}
        />
      ))}
    </div>
  );
}
