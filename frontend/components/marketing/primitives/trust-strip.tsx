import { KeyRound, Lock, ShieldCheck } from 'lucide-react';

import { cn } from '@/lib/utils';

/**
 * The three standing guarantees, shown wherever a visitor is deciding rather
 * than browsing (hero, pricing, enterprise). Each one is a fact the product
 * can be held to, not a slogan.
 */
const CLAIMS = [
  { Icon: KeyRound, label: 'Bring your own API keys' },
  { Icon: Lock, label: 'Encrypted at rest' },
  { Icon: ShieldCheck, label: 'No LLM-as-judge scoring' },
] as const;

export function TrustStrip({ className }: Readonly<{ className?: string }>) {
  return (
    <ul className={cn('flex flex-wrap items-center gap-x-6 gap-y-3', className)}>
      {CLAIMS.map(({ Icon, label }) => (
        <li key={label} className="text-mkt-sm text-mkt-ink-muted flex items-center gap-2">
          <Icon aria-hidden strokeWidth={2} className="text-mkt-ink-soft size-4 shrink-0" />
          {label}
        </li>
      ))}
    </ul>
  );
}
