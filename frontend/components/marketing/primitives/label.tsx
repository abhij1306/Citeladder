import type { ReactNode } from 'react';

import { cn } from '@/lib/utils';

/**
 * The "meta" role: small (12/16), semibold labels with tabular numerals
 * (`font-mono tabular-nums`) — the same numeric recipe every figure in the
 * app renders with, so numbers align and read as data. The default ink is
 * `text-mkt-ink-muted` (paper/surface-only — on sunken/wash bands callers
 * pass `text-mkt-ink-soft`); kickers layer `uppercase` on top. Codifying
 * the recipe as one component is why every label on the surface matches.
 */
export function Meta({
  children,
  className,
  as: Tag = 'span',
}: Readonly<{ children: ReactNode; className?: string; as?: 'span' | 'p' | 'div' }>) {
  return (
    <Tag
      className={cn(
        'text-mkt-meta text-mkt-ink-muted font-mono font-semibold tabular-nums',
        className,
      )}
    >
      {children}
    </Tag>
  );
}

/**
 * Section opener: a proof-blue dot with a halo, then the label. The dot is
 * the only decorative use of the accent on paper — everywhere else colour
 * has to mean a state.
 */
export function Eyebrow({
  children,
  className,
}: Readonly<{ children: ReactNode; className?: string }>) {
  return (
    <span
      className={cn(
        'text-mkt-meta text-mkt-ink-soft inline-flex items-center gap-2.5 font-semibold',
        className,
      )}
    >
      <span className="bg-mkt-proof ring-mkt-proof-soft size-1.5 shrink-0 rounded-full ring-5" />
      {children}
    </span>
  );
}

/**
 * "Evidence capture active" — a live indicator with a slow pulse. Used only
 * where something genuinely is running in the depicted scene.
 */
export function LiveDot({ children }: Readonly<{ children: ReactNode }>) {
  return (
    <span className="text-mkt-meta text-mkt-ink-soft inline-flex items-center gap-2 font-mono uppercase tabular-nums">
      <span className="bg-mkt-evidence animate-mkt-pulse size-1.5 shrink-0 rounded-full" />
      {children}
    </span>
  );
}
