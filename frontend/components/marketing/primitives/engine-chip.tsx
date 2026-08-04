import { cn } from '@/lib/utils';

import { ENGINES, type EngineKey } from './engine-data';
import { EngineLogo } from './engine-logo';

/**
 * Provider identity. Exactly the engines CiteLadder audits — one approved
 * transport per engine (backend/app/core/config/provider_catalog.py). Keeping
 * the roster in one place stops pages from inventing providers to fill a
 * row — the deck's "never fabricate scale" rule, made structural. Referral
 * sources the analytics surface can detect (Perplexity, Microsoft Copilot,
 * Google AI Overview) are NOT engines and never appear here.
 */
export function EngineChip({
  engine,
  className,
}: Readonly<{ engine: EngineKey; className?: string }>) {
  const { label, tile } = ENGINES[engine];
  return (
    <span
      className={cn(
        'border-border-subtle bg-panel inline-flex items-center gap-4 rounded-md text-sm',
        'border px-4 py-4 font-semibold',
        className,
      )}
    >
      <span
        aria-hidden
        className={cn(
          'text-inverse grid size-5 shrink-0 place-items-center rounded-md',
          'text-2xs font-medium',
          tile,
        )}
      >
        <EngineLogo engine={engine} className="size-3" />
      </span>
      {label}
    </span>
  );
}
