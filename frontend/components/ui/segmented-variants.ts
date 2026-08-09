import { cva } from 'class-variance-authority';

export const segmentedTrackVariants = cva(
  'border-border bg-background-alt inline-flex min-h-[var(--control-height-sm)] items-center gap-0.5 rounded-full border p-0.5',
);

export const segmentedItemVariants = cva(
  'focus-ring inline-flex h-[calc(var(--control-height-sm)-6px)] items-center justify-center rounded-full px-3 text-xs font-medium whitespace-nowrap transition-colors disabled:cursor-not-allowed disabled:opacity-50',
  {
    variants: {
      selected: {
        true: 'bg-panel text-foreground shadow-card',
        false: 'text-secondary enabled:hover:text-foreground',
      },
    },
    defaultVariants: { selected: false },
  },
);
