import { cn } from '@/lib/utils';

/** Shared multi-select/filter chip recipe. */
export function filterChipClasses(active: boolean): string {
  return cn(
    'focus-ring inline-flex h-[var(--control-height-sm)] items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-[background-color,color,border-color] duration-[250ms] ease-standard',
    active
      ? 'border-accent-border bg-accent-soft text-accent-text'
      : 'border-border bg-panel text-secondary hover:border-border-strong hover:text-foreground',
  );
}
