import { cva } from 'class-variance-authority';

export const segmentedTrackVariants = cva(
  'border-border bg-background-alt inline-flex min-h-[var(--control-height-sm)] items-center gap-0.5 rounded-[var(--radius-control)] border p-0.5',
);

export const segmentedItemVariants = cva(
  'focus-ring inline-flex h-[calc(var(--control-height-sm)-6px)] items-center justify-center rounded-[calc(var(--radius-control)-2px)] px-3 text-xs font-medium whitespace-nowrap transition-[background-color,color,box-shadow] disabled:cursor-not-allowed disabled:opacity-50',
  {
    variants: {
      selected: {
        true: 'bg-panel text-foreground shadow-xs',
        false: 'text-secondary enabled:hover:bg-well enabled:hover:text-foreground',
      },
    },
    defaultVariants: { selected: false },
  },
);
