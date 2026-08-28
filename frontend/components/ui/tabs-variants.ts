import { cva } from 'class-variance-authority';

export const tabListVariants = cva(
  "relative flex w-full max-w-full flex-nowrap gap-1 overflow-x-auto [scrollbar-width:none] before:absolute before:inset-x-0 before:bottom-0 before:h-px before:bg-border before:content-[''] [&::-webkit-scrollbar]:hidden",
);

export const tabItemVariants = cva(
  'focus-ring relative inline-flex h-10 shrink-0 items-center rounded-t-md px-3 text-sm font-medium whitespace-nowrap transition-colors',
  {
    variants: {
      selected: {
        true: "text-accent-text after:absolute after:inset-x-2 after:bottom-0 after:h-0.5 after:rounded-full after:bg-accent after:content-['']",
        false: 'text-secondary hover:bg-background-alt hover:text-foreground',
      },
    },
    defaultVariants: { selected: false },
  },
);
